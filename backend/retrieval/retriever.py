import asyncio
import logging
from typing import Dict, List

from ingest.embedder import EmbeddingUnavailableError, embed_query

logger = logging.getLogger(__name__)

async def retrieve_context(supabase_client, repo_id: str, query: str, top_k: int = 8) -> List[Dict]:
    # 1. Embed the query when NVIDIA is available. A repository may have been
    # indexed during a temporary embedding outage, in which case sparse search
    # still provides source-grounded evidence instead of failing the chat.
    try:
        query_emb = await asyncio.to_thread(embed_query, query)
    except EmbeddingUnavailableError:
        logger.warning("NVIDIA query embedding unavailable; falling back to keyword retrieval")
        query_emb = None
    
    # 2. Run queries concurrently via asyncio wrapping Supabase sync calls
    # supabase-py is sync, so we run them in executors to not block the event loop
    loop = asyncio.get_running_loop()
    
    def fetch_dense():
        return supabase_client.rpc('match_chunks_dense', {
            'p_repo_id': repo_id,
            'p_query_embedding': query_emb,
            'p_limit': 20
        }).execute()

    def fetch_sparse():
        return supabase_client.rpc('match_chunks_sparse', {
            'p_repo_id': repo_id,
            'p_query': query,
            'p_limit': 20
        }).execute()
        
    def fetch_readme():
        return supabase_client.table('chunks').select('id, file_path, start_line, end_line, language, content')\
            .eq('repo_id', repo_id)\
            .ilike('file_path', '%readme.md%')\
            .limit(1).execute()

    retrieval_tasks = [
        loop.run_in_executor(None, fetch_sparse),
        loop.run_in_executor(None, fetch_readme),
    ]
    if query_emb is not None:
        retrieval_tasks.insert(0, loop.run_in_executor(None, fetch_dense))
    results = await asyncio.gather(*retrieval_tasks)
    if query_emb is not None:
        dense_res, sparse_res, readme_res = results
    else:
        sparse_res, readme_res = results
        dense_res = None
    
    dense_chunks = dense_res.data if dense_res is not None else []
    sparse_chunks = sparse_res.data or []
    readme_chunks = readme_res.data or []

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
        
    # Sort by RRF score
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    
    # 4. Use the README as a tie-breaking architectural anchor, without exceeding K.
    final_chunks = [chunk_map[c_id] for c_id in sorted_ids[:top_k]]
    if readme_chunks:
        readme = readme_chunks[0]
        if not any(chunk['id'] == readme['id'] for chunk in final_chunks):
            final_chunks = [readme] + final_chunks[:max(0, top_k - 1)]
    return final_chunks
