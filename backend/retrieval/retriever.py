"""Hybrid, source-grounded retrieval over Turso chunks."""

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
    # Keep this deliberately narrow. Technical questions such as "explain
    # authentication" need implementation evidence, not an automatically
    # injected README. This is only for genuinely repository-wide questions.
    r"(?:\bwhat is (?:this|the) (?:project|repository|codebase)\b|"
    r"\b(?:give|show|provide)\b.{0,32}\b(?:overview|architecture|high[- ]level)\b|"
    r"\b(?:overall|high[- ]level)\s+(?:architecture|overview)\b|"
    r"\b(?:what makes|how is)\b.{0,56}\b(?:different|unique)\b|"
    r"\b(?:purpose|about)\s+(?:this|the)\s+(?:project|repository|codebase)\b)",
    re.IGNORECASE,
)
WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
MAX_CHUNKS_PER_FILE = 2
IMPACT_QUESTION_PATTERN = re.compile(
    r"\b(?:what\s+(?:breaks|is\s+affected)|impact|depend(?:s|encies|ent)|affected\s+files?)\b|"
    r"\bif\s+.+\s+(?:changes?|is\s+removed|is\s+renamed)\b",
    re.IGNORECASE,
)

# Codebases often name authentication modules `auth`, not `authentication`.
# These small, domain-specific expansions improve keyword retrieval without
# treating a broad README as proof for an implementation-level answer.
RETRIEVAL_TERM_ALIASES = {
    "authentication": ("auth", "login", "oauth", "session"),
    "authorization": ("authorize", "auth", "permission", "role"),
    "authenticate": ("auth", "login", "oauth", "session"),
    "authorize": ("authorization", "auth", "permission", "role"),
    "signin": ("sign_in", "login", "oauth", "auth"),
    "login": ("auth", "signin", "oauth", "session"),
}

EVIDENCE_WORKFLOWS = {
    "general": {
        "label": "Repository question",
        "focus": "Answer the question from the most directly relevant source files.",
        "terms": (),
        "path_hints": (),
    },
    "onboarding": {
        "label": "New engineer onboarding",
        "focus": "Explain the entry points, main flow, configuration, and first files a new engineer should read.",
        "terms": ("entrypoint", "main", "app", "config", "route", "service", "readme"),
        "path_hints": ("readme", "main", "app", "config", "route", "server", "index"),
    },
    "security": {
        "label": "Security review",
        "focus": "Trace authentication, authorization, trust boundaries, secrets, validation, and externally reachable handlers.",
        "terms": ("auth", "authentication", "authorization", "permission", "token", "session", "secret", "middleware", "webhook", "upload", "cors", "route", "validate", "sanitize"),
        "path_hints": ("auth", "middleware", "security", "permission", "token", "session", "config", "route", "api", "test"),
    },
    "architecture": {
        "label": "Architecture interview",
        "focus": "Describe components, boundaries, data flow, persistence, and integration points without inventing relationships.",
        "terms": ("module", "package", "service", "route", "config", "schema", "model", "database", "worker", "queue"),
        "path_hints": ("app", "api", "backend", "service", "worker", "config", "schema", "model"),
    },
    "contributor": {
        "label": "Open-source contributor",
        "focus": "Point to local development, tests, conventions, CI, and the smallest safe change surface.",
        "terms": ("contributing", "readme", "test", "tests", "ci", "workflow", "package", "script", "config"),
        "path_hints": ("contribut", "test", "spec", "ci", "workflow", "package", "readme"),
    },
    "due_diligence": {
        "label": "Technical due diligence",
        "focus": "Summarize deployment, dependencies, license, tests, configuration, and operational risks supported by the index.",
        "terms": ("license", "readme", "deploy", "docker", "config", "dependency", "test", "ci", "security"),
        "path_hints": ("license", "readme", "docker", "deploy", "config", "test", "ci", "package"),
    },
}


def extract_requested_file_paths(query: str) -> list[str]:
    paths: list[str] = []
    for match in FILE_PATH_PATTERN.finditer(query):
        path = match.group(1).lstrip("./")
        if path and path not in paths:
            paths.append(path)
    return paths


def is_exploratory_repository_question(query: str, requested_paths: list[str]) -> bool:
    return not requested_paths and bool(EXPLORATORY_REPOSITORY_PATTERN.search(query))


def is_impact_question(query: str) -> bool:
    return bool(IMPACT_QUESTION_PATTERN.search(query))


def select_diverse_chunks(candidates: list[Dict], limit: int, excluded_ids: set[str] | None = None) -> list[Dict]:
    excluded_ids = excluded_ids or set()
    selected: list[Dict] = []
    selected_ids = set(excluded_ids)
    per_file = defaultdict(int)
    for chunk in candidates:
        chunk_id, file_path = chunk["id"], chunk["file_path"]
        if chunk_id in selected_ids or per_file[file_path] >= MAX_CHUNKS_PER_FILE:
            continue
        selected.append(chunk)
        selected_ids.add(chunk_id)
        per_file[file_path] += 1
        if len(selected) == limit:
            return selected
    for chunk in candidates:
        if chunk["id"] in selected_ids:
            continue
        selected.append(chunk)
        selected_ids.add(chunk["id"])
        if len(selected) == limit:
            break
    return selected


def search_terms(query: str) -> list[str]:
    """Keep sparse matching resilient to punctuation and provider-unavailable embeddings."""
    terms = [word.lower() for word in WORD_PATTERN.findall(query) if len(word) >= 3]
    for term in list(terms):
        terms.extend(RETRIEVAL_TERM_ALIASES.get(term, ()))
    return list(dict.fromkeys(terms))[:10]


def build_evidence_plan(query: str, workflow: str = "general") -> dict:
    """Create a deterministic retrieval plan that is visible to the client.

    The plan guides sparse retrieval and gives the answer/UI an honest account
    of what was targeted. It does not claim that every target exists in a
    repository; absent targets remain an explicit evidence limitation.
    """
    profile = EVIDENCE_WORKFLOWS.get(workflow, EVIDENCE_WORKFLOWS["general"])
    terms = list(dict.fromkeys([*search_terms(query), *profile["terms"]]))[:20]
    return {
        "workflow": workflow if workflow in EVIDENCE_WORKFLOWS else "general",
        "label": profile["label"],
        "focus": profile["focus"],
        "search_terms": terms,
        "path_hints": list(profile["path_hints"]),
        "requested_files": extract_requested_file_paths(query),
    }


async def sparse_search(store, repo_id: str, query: str, limit: int = 20, plan: dict | None = None) -> list[Dict]:
    terms = list(dict.fromkeys([*search_terms(query), *(plan or {}).get("search_terms", [])]))[:20]
    if not terms:
        return []
    # FTS5 is maintained with triggers in turso/00_init.sql. It avoids a
    # repository-wide LIKE scan for ordinary natural-language questions. Keep
    # the LIKE implementation as a compatibility fallback for databases that
    # were created before this migration.
    fts_expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
    try:
        return await store.fetch_all(
            "SELECT c.id, c.file_path, c.start_line, c.end_line, c.language, c.symbols, c.content, "
            "bm25(chunks_fts) AS score FROM chunks_fts "
            "JOIN chunks c ON c.rowid = chunks_fts.rowid "
            "WHERE chunks_fts MATCH ? AND c.repo_id = ? "
            "ORDER BY score ASC, c.file_path ASC, c.start_line ASC LIMIT ?",
            [fts_expression, repo_id, limit],
        )
    except Exception as error:
        logger.warning("Turso FTS unavailable; using bounded keyword fallback (%s)", type(error).__name__)
    score_parts = ["CASE WHEN lower(content) LIKE ? OR lower(file_path) LIKE ? THEN 1 ELSE 0 END" for _ in terms]
    matching_parts = ["(lower(content) LIKE ? OR lower(file_path) LIKE ?)" for _ in terms]
    score_args = [value for term in terms for value in (f"%{term}%", f"%{term}%")]
    sql = (
        "SELECT id, file_path, start_line, end_line, language, symbols, content, "
        f"({' + '.join(score_parts)}) AS score FROM chunks WHERE repo_id = ? AND ({' OR '.join(matching_parts)}) "
        "ORDER BY score DESC, file_path ASC, start_line ASC LIMIT ?"
    )
    return await store.fetch_all(sql, [*score_args, repo_id, *score_args, limit])


async def dense_search(store, repo_id: str, query_embedding: list[float], limit: int = 20) -> list[Dict]:
    """Use Turso's native cosine-distance function; query filtering preserves tenant isolation."""
    import json
    return await store.fetch_all(
        "SELECT id, file_path, start_line, end_line, language, symbols, content, "
        "vector_distance_cos(embedding, vector32(?)) AS distance "
        "FROM chunks WHERE repo_id = ? AND embedding IS NOT NULL ORDER BY distance ASC LIMIT ?",
        [json.dumps(query_embedding), repo_id, limit],
    )


async def requested_file_chunks(store, repo_id: str, file_path: str, limit: int) -> list[Dict]:
    exact_or_suffix = file_path if "/" in file_path else f"%/{file_path}"
    return await store.fetch_all(
        "SELECT id, file_path, start_line, end_line, language, symbols, content FROM chunks "
        "WHERE repo_id = ? AND (file_path = ? OR file_path LIKE ?) ORDER BY file_path, start_line LIMIT ?",
        [repo_id, file_path, exact_or_suffix, limit],
    )


async def path_hint_chunks(store, repo_id: str, hint: str, limit: int = 2) -> list[Dict]:
    """Fetch a small representative sample for an evidence-plan path hint."""
    return await store.fetch_all(
        "SELECT id, file_path, start_line, end_line, language, symbols, content FROM chunks "
        "WHERE repo_id = ? AND lower(file_path) LIKE ? ORDER BY file_path, start_line LIMIT ?",
        [repo_id, f"%{hint.lower()}%", limit],
    )


async def dependent_file_chunks(store, repo_id: str, target_paths: list[str], limit: int = 20) -> list[Dict]:
    """Retrieve files that import a target according to the resolved graph."""
    if not target_paths:
        return []
    target_conditions = []
    target_args = []
    for path in target_paths:
        target_conditions.append("(d.target_file = ? OR d.target_file LIKE ?)")
        target_args.extend([path, f"%/{path}"])
    return await store.fetch_all(
        "SELECT DISTINCT c.id, c.file_path, c.start_line, c.end_line, c.language, c.symbols, c.content "
        "FROM repo_dependencies d JOIN chunks c ON c.repo_id = d.repo_id AND c.file_path = d.source_file "
        f"WHERE d.repo_id = ? AND ({' OR '.join(target_conditions)}) "
        "ORDER BY c.file_path, c.start_line LIMIT ?",
        [repo_id, *target_args, limit],
    )


async def retrieve_context(store, repo_id: str, query: str, top_k: int = 8, workflow: str = "general") -> List[Dict]:
    requested_paths = extract_requested_file_paths(query)
    include_overview = is_exploratory_repository_question(query, requested_paths)
    evidence_plan = build_evidence_plan(query, workflow)

    sparse_task = asyncio.create_task(sparse_search(store, repo_id, query, plan=evidence_plan))
    file_tasks = [asyncio.create_task(requested_file_chunks(store, repo_id, path, top_k)) for path in requested_paths]
    plan_tasks = [
        asyncio.create_task(path_hint_chunks(store, repo_id, hint))
        for hint in evidence_plan.get("path_hints", [])[:8]
    ]
    readme_task = (
        asyncio.create_task(store.fetch_all(
            "SELECT id, file_path, start_line, end_line, language, symbols, content FROM chunks "
            "WHERE repo_id = ? AND lower(file_path) LIKE '%readme.md' ORDER BY start_line LIMIT 1", [repo_id]
        )) if include_overview else None
    )
    overview_task = (
        asyncio.create_task(store.fetch_all(
            "SELECT id, file_path, start_line, end_line, language, symbols, content FROM chunks "
            "WHERE repo_id = ? ORDER BY file_path, start_line LIMIT ?", [repo_id, settings.overview_retrieval_candidates]
        )) if include_overview else None
    )

    try:
        query_embedding = await asyncio.to_thread(embed_query, query)
        dense_task = asyncio.create_task(dense_search(store, repo_id, query_embedding))
    except (EmbeddingUnavailableError, ModelConfigurationError):
        logger.warning("NVIDIA query embedding unavailable; falling back to keyword retrieval")
        dense_task = None

    pending = [sparse_task, *file_tasks, *plan_tasks]
    if dense_task:
        pending.insert(0, dense_task)
    if readme_task:
        pending.append(readme_task)
    if overview_task:
        pending.append(overview_task)
    results = await asyncio.gather(*pending, return_exceptions=True)

    successful = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("A retrieval strategy failed for %s (%s)", repo_id, type(result).__name__)
            successful.append([])
        else:
            successful.append(result)
    cursor = 0
    dense_chunks = successful[cursor] if dense_task else []
    cursor += 1 if dense_task else 0
    sparse_chunks = successful[cursor]
    cursor += 1
    file_results = successful[cursor:cursor + len(file_tasks)]
    cursor += len(file_tasks)
    plan_results = successful[cursor:cursor + len(plan_tasks)]
    cursor += len(plan_tasks)
    readme_chunks = successful[cursor] if readme_task else []
    cursor += 1 if readme_task else 0
    overview_chunks = successful[cursor] if overview_task else []

    def annotate(chunk: Dict, method: str, reason: str) -> Dict:
        enriched = dict(chunk)
        enriched["_retrieval_methods"] = list(dict.fromkeys([*(enriched.get("_retrieval_methods") or []), method]))
        enriched["_retrieval_reasons"] = list(dict.fromkeys([*(enriched.get("_retrieval_reasons") or []), reason]))
        enriched["_evidence_plan"] = evidence_plan
        return enriched

    requested_map = {
        chunk["id"]: annotate(chunk, "requested_file", "Explicit file path requested in the question")
        for rows in file_results for chunk in rows
    }
    requested_chunks = sorted(requested_map.values(), key=lambda chunk: (chunk["file_path"], chunk["start_line"]))
    planned_map: dict[str, Dict] = {}
    for hint, rows in zip(evidence_plan.get("path_hints", [])[:8], plan_results):
        for chunk in rows:
            planned_map[chunk["id"]] = annotate(
                chunk,
                "workflow_target",
                f"Evidence-plan target matching the '{hint}' path hint",
            )
    scores: dict[str, float] = {}
    chunk_map: dict[str, Dict] = {}
    for chunk in requested_chunks:
        chunk_map[chunk["id"]] = chunk
        scores[chunk["id"]] = 2.0
    for chunk in planned_map.values():
        chunk_map[chunk["id"]] = chunk
        scores[chunk["id"]] = scores.get(chunk["id"], 0) + 0.015
    for source, method, reason in (
        (dense_chunks, "semantic", "Semantic similarity to the question"),
        (sparse_chunks, "keyword", "Keyword match in file path or source content"),
    ):
        for rank, chunk in enumerate(source):
            annotated = annotate(chunk_map.get(chunk["id"], chunk), method, reason)
            chunk_map[chunk["id"]] = annotated
            scores[chunk["id"]] = scores.get(chunk["id"], 0) + 1.0 / (60 + rank + 1)
            if any(hint in str(chunk.get("file_path", "")).lower() for hint in evidence_plan["path_hints"]):
                scores[chunk["id"]] += 0.01
    ranked_chunks = [chunk_map[chunk_id] for chunk_id in sorted(scores, key=scores.get, reverse=True)]

    # Impact questions get one extra, explicitly labelled pass over the
    # resolved dependency graph. If no file is named, use only a few directly
    # matched files as targets; unresolved package aliases are never invented.
    dependency_chunks: list[Dict] = []
    if is_impact_question(query):
        target_paths = list(requested_paths)
        if not target_paths:
            target_paths = list(dict.fromkeys(chunk["file_path"] for chunk in sparse_chunks[:3]))
        try:
            dependency_chunks = await dependent_file_chunks(store, repo_id, target_paths)
        except Exception as error:
            logger.warning("Dependency impact retrieval unavailable for %s (%s)", repo_id, type(error).__name__)
        for chunk in dependency_chunks:
            annotated = annotate(
                chunk_map.get(chunk["id"], chunk),
                "dependency",
                "Depends on a directly matched file in the indexed repository graph",
            )
            chunk_map[chunk["id"]] = annotated
            scores[chunk["id"]] = scores.get(chunk["id"], 0) + 0.02
        ranked_chunks = [chunk_map[chunk_id] for chunk_id in sorted(scores, key=scores.get, reverse=True)]
    # Broad overview evidence is a fallback, never an automatic citation. If
    # dense or sparse retrieval has direct evidence, that evidence remains the
    # entire source set. This prevents README.md from appearing beside an
    # implementation question merely because it contains words like "explain".
    if include_overview and not ranked_chunks:
        fallback_by_id: dict[str, Dict] = {}
        for chunk in [*readme_chunks, *overview_chunks]:
            fallback_by_id.setdefault(chunk["id"], annotate(chunk, "overview", "Repository-wide overview fallback; no direct term match"))
        ranked_chunks = list(fallback_by_id.values())

    requested_ids = {chunk["id"] for chunk in requested_chunks}
    final_chunks = requested_chunks[:top_k]
    if len(final_chunks) < top_k:
        final_chunks.extend(select_diverse_chunks(ranked_chunks, top_k - len(final_chunks), requested_ids))
    for chunk in final_chunks:
        chunk["_relevance_score"] = round(scores.get(chunk["id"], 0.0), 6)
    return final_chunks
