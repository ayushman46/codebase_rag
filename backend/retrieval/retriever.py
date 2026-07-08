import asyncio
from database import supabase
from ingest.embedder import model as embedding_model
from typing import List, Dict

async def retrieve_context(repo_id: str, query: str, top_k: int = 8) -> List[Dict]:
    # 1. Embed query
    query_emb = embedding_model.encode([query], show_progress_bar=False)[0].tolist()
    
    # 2. Run queries concurrently via asyncio wrapping Supabase sync calls
    # supabase-py is sync, so we run them in executors to not block the event loop
    loop = asyncio.get_running_loop()
    
    def fetch_dense():
        return supabase.rpc('match_chunks_dense', {
            'p_repo_id': repo_id,
            'p_query_embedding': query_emb,
            'p_limit': 20
        }).execute()

    def fetch_sparse():
        return supabase.rpc('match_chunks_sparse', {
            'p_repo_id': repo_id,
            'p_query': query,
            'p_limit': 20
        }).execute()
        
    def fetch_readme():
        return supabase.table('chunks').select('id, file_path, start_line, end_line, language, content')\
            .eq('repo_id', repo_id)\
            .ilike('file_path', '%readme.md%')\
            .limit(1).execute()

    dense_res, sparse_res, readme_res = await asyncio.gather(
        loop.run_in_executor(None, fetch_dense),
        loop.run_in_executor(None, fetch_sparse),
        loop.run_in_executor(None, fetch_readme)
    )
    
    dense_chunks = dense_res.data
    sparse_chunks = sparse_res.data
    readme_chunks = readme_res.data

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
    
    # 4. Take Top K
    final_chunks = [chunk_map[c_id] for c_id in sorted_ids[:top_k]]
    
    # 5. Always add README
    if readme_chunks:
        readme = readme_chunks[0]
        if not any(c['id'] == readme['id'] for c in final_chunks):
            final_chunks.insert(0, readme)
            
    return final_chunks
