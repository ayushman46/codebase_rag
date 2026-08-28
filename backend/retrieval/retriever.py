import asyncio
import logging
import re
from collections import defaultdict
from typing import Dict, List

from config import ModelConfigurationError, settings
from ingest.embedder import EmbeddingUnavailableError, embed_query

logger = logging.getLogger(__name__)

FILE_PATH_PATTERN = re.compile(
    r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:"
    r"py|js|jsx|ts|tsx|java|go|rs|rb|php|c|cc|cpp|cxx|h|hpp|cs|swift|kt|kts|scala|"
    r"sql|sh|bash|zsh|ps1|yaml|yml|json|toml|ini|cfg|conf|md|rst|txt|html|css|scss|"
    r"sass|less|xml|graphql|gql|proto|dockerfile"
    r"))(?![\w.-])",
    re.IGNORECASE,
)
EXPLORATORY_REPOSITORY_PATTERN = re.compile(
    r"\b(?:overview|architecture|high[- ]level|purpose|different|difference|compare|comparison|"
    r"unique|distinguish|what makes|how does .*? work|about (?:this|the)|explain|describe)\b",
    re.IGNORECASE,
)
MAX_CHUNKS_PER_FILE = 2


def extract_requested_file_paths(query: str) -> list[str]:
    """Return distinct source paths explicitly named in a question."""
    paths: list[str] = []
    for match in FILE_PATH_PATTERN.finditer(query):
        path = match.group(1).lstrip("./")
        if path and path not in paths:
            paths.append(path)
    return paths


def is_exploratory_repository_question(query: str, requested_paths: list[str]) -> bool:
    """Use an index overview for high-level questions, never file requests."""
    return not requested_paths and bool(EXPLORATORY_REPOSITORY_PATTERN.search(query))


def select_diverse_chunks(candidates: list[Dict], limit: int, excluded_ids: set[str] | None = None) -> list[Dict]:
    """Keep evidence useful across files instead of letting one file dominate."""
    excluded_ids = excluded_ids or set()
    selected: list[Dict] = []
    selected_ids = set(excluded_ids)
    per_file = defaultdict(int)

    for chunk in candidates:
        chunk_id = chunk["id"]
        file_path = chunk["file_path"]
        if chunk_id in selected_ids or per_file[file_path] >= MAX_CHUNKS_PER_FILE:
            continue
        selected.append(chunk)
        selected_ids.add(chunk_id)
        per_file[file_path] += 1
        if len(selected) == limit:
            return selected

    # Fill the remaining slots only after every relevant file had a chance to
    # appear. This preserves deep answers when a single file truly dominates.
    for chunk in candidates:
        if chunk["id"] in selected_ids:
            continue
        selected.append(chunk)
        selected_ids.add(chunk["id"])
        if len(selected) == limit:
            break
    return selected


async def retrieve_context(supabase_client, repo_id: str, query: str, top_k: int = 8) -> List[Dict]:
    # Start database-only retrieval immediately. Query embeddings are hosted
    # work, so doing this first avoids making keyword search wait on NVIDIA.
    loop = asyncio.get_running_loop()

    def fetch_sparse():
        return supabase_client.rpc('match_chunks_sparse', {
            'p_repo_id': repo_id,
            'p_query': query,
            'p_limit': 20
        }).execute()

    requested_paths = extract_requested_file_paths(query)
    include_overview = is_exploratory_repository_question(query, requested_paths)

    def fetch_readme():
        return supabase_client.table('chunks').select('id, file_path, start_line, end_line, language, content')\
            .eq('repo_id', repo_id)\
            .ilike('file_path', '%readme.md%')\
            .limit(1).execute()

    def fetch_file_chunks(file_path: str):
        # A path containing a directory is exact. A bare filename matches the
        # repository suffix so `schema.sql` can locate either `schema.sql` or
        # `sql/schema.sql`.
        path_filter = file_path if '/' in file_path else f'%{file_path}'
        return supabase_client.table('chunks').select(
            'id, file_path, start_line, end_line, language, symbols, content'
        ).eq('repo_id', repo_id).ilike('file_path', path_filter).order('start_line').limit(top_k).execute()

    def fetch_overview_chunks():
        """Fetch a small, deterministic sample of real source for broad questions."""
        return supabase_client.table('chunks').select(
            'id, file_path, start_line, end_line, language, symbols, content'
        ).eq('repo_id', repo_id).order('file_path').order('start_line').limit(
            settings.overview_retrieval_candidates
        ).execute()

    sparse_task = loop.run_in_executor(None, fetch_sparse)
    readme_task = loop.run_in_executor(None, fetch_readme) if include_overview else None
    overview_task = loop.run_in_executor(None, fetch_overview_chunks) if include_overview else None
    file_tasks = [loop.run_in_executor(None, fetch_file_chunks, path) for path in requested_paths]

    # Embed the query when NVIDIA is available. A repository may have been
    # indexed during a temporary embedding outage, in which case sparse search
    # still provides source-grounded evidence instead of failing the chat.
    try:
        query_emb = await asyncio.to_thread(embed_query, query)
    except (EmbeddingUnavailableError, ModelConfigurationError):
        logger.warning("NVIDIA query embedding unavailable; falling back to keyword retrieval")
        query_emb = None
    
    def fetch_dense():
        return supabase_client.rpc('match_chunks_dense', {
            'p_repo_id': repo_id,
            'p_query_embedding': query_emb,
            'p_limit': 20
        }).execute()

    retrieval_tasks = [sparse_task, *file_tasks]
    if query_emb is not None:
        retrieval_tasks.insert(0, loop.run_in_executor(None, fetch_dense))
    if readme_task is not None:
        retrieval_tasks.append(readme_task)
    if overview_task is not None:
        retrieval_tasks.append(overview_task)
    results = await asyncio.gather(*retrieval_tasks)
    if query_emb is not None:
        dense_res, sparse_res, *remaining_results = results
    else:
        sparse_res, *remaining_results = results
        dense_res = None
    
    dense_chunks = dense_res.data if dense_res is not None else []
    sparse_chunks = sparse_res.data or []
    if include_overview:
        *file_results, readme_res, overview_res = remaining_results
        readme_chunks = readme_res.data or []
        overview_chunks = overview_res.data or []
    else:
        file_results = remaining_results
        readme_chunks = []
        overview_chunks = []
    requested_chunk_map = {
        chunk["id"]: chunk for result in file_results for chunk in (result.data or [])
    }
    requested_chunks = list(requested_chunk_map.values())
    requested_chunks.sort(key=lambda chunk: (chunk["file_path"], chunk["start_line"]))

    # 3. Reciprocal Rank Fusion
    scores = {}
    chunk_map = {}
    
    for rank, c in enumerate(dense_chunks):
        c_id = c['id']
        chunk_map[c_id] = c
        scores[c_id] = scores.get(c_id, 0) + (1.0 / (60 + rank))
        
    for rank, c in enumerate(sparse_chunks):
        c_id = c['id']
        if c_id not in chunk_map:
            chunk_map[c_id] = c
        scores[c_id] = scores.get(c_id, 0) + (1.0 / (60 + rank))
        
    # Sort by RRF score, then make the final result file-diverse.
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    ranked_chunks = [chunk_map[c_id] for c_id in sorted_ids]
    ranked_ids = {chunk["id"] for chunk in ranked_chunks}
    if include_overview:
        # Retrieval remains the first choice. The overview merely supplies
        # real, cited source coverage when broad wording has no lexical match.
        ranked_chunks.extend(chunk for chunk in overview_chunks if chunk["id"] not in ranked_ids)
    requested_ids = {chunk["id"] for chunk in requested_chunks}
    final_chunks = requested_chunks[:top_k]
    if len(final_chunks) < top_k:
        final_chunks.extend(
            select_diverse_chunks(ranked_chunks, top_k - len(final_chunks), requested_ids)
        )

    # Use the README only as a broad-question architectural anchor. It must
    # never displace requested source-file evidence.
    if readme_chunks:
        readme = readme_chunks[0]
        if not any(chunk['id'] == readme['id'] for chunk in final_chunks):
            final_chunks = [readme] + final_chunks[:max(0, top_k - 1)]
    return final_chunks
