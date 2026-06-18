import os
import json
import pickle
import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from flashrank import Ranker, RerankRequest
from ingest.embedder import model as embedding_model

INDEXES_DIR = "./indexes"
# Load the ranker globally
ranker = Ranker()

def load_metadata(repo_name: str) -> list[dict]:
    path = os.path.join(INDEXES_DIR, repo_name, "chunks_metadata.json")
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def retrieve_context(repo_name: str, query: str, top_k: int = 6) -> list[dict]:
    repo_dir = os.path.join(INDEXES_DIR, repo_name)
    metadata = load_metadata(repo_name)
    if not metadata:
        return []

    # Always try to fetch README if it exists to provide high-level context
    readme_content = ""
    repo_path = f"./repos/{repo_name}"
    for readme_name in ["README.md", "readme.md", "README.MD"]:
        r_path = os.path.join(repo_path, readme_name)
        if os.path.exists(r_path):
            try:
                with open(r_path, 'r', encoding='utf-8', errors='ignore') as f:
                    readme_content = f.read()[:3000] # Cap at 3k chars
                break
            except: pass

    # 1. FAISS Search
    faiss_path = os.path.join(repo_dir, "faiss_index", "index.faiss")
    if not os.path.exists(faiss_path):
        return []
        
    faiss_index = faiss.read_index(faiss_path)
    
    query_emb = embedding_model.encode([query], show_progress_bar=False).astype(np.float32)
    faiss_k = min(20, len(metadata))
    faiss_distances, faiss_indices = faiss_index.search(query_emb, faiss_k)
    
    # 2. BM25 Search
    bm25_path = os.path.join(repo_dir, "bm25.pkl")
    with open(bm25_path, 'rb') as f:
        bm25 = pickle.load(f)
        
    tokenized_query = query.split()
    bm25_scores = bm25.get_scores(tokenized_query)
    bm25_indices = np.argsort(bm25_scores)[::-1][:faiss_k]
    
    # 3. RRF Fusion (Reciprocal Rank Fusion)
    k_rrf = 60
    rrf_scores = {}
    
    for rank, idx in enumerate(faiss_indices[0]):
        if idx != -1:
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (k_rrf + rank + 1)
            
    for rank, idx in enumerate(bm25_indices):
        rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (k_rrf + rank + 1)
        
    # Get top combined candidates for reranking
    sorted_fused_indices = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:30]
    
    # 4. Flashrank Reranking
    passages = []
    for idx in sorted_fused_indices:
        passages.append({
            "id": metadata[idx]["id"],
            "text": metadata[idx]["content"],
            "meta": metadata[idx]
        })
        
    rerank_request = RerankRequest(query=query, passages=passages)
    reranked_results = ranker.rerank(rerank_request)
    
    # Extract final top_k
    final_chunks = []
    
    # Inject README as first chunk if found
    if readme_content:
        final_chunks.append({
            "id": "readme",
            "content": f"--- REPO README START ---\n{readme_content}\n--- REPO README END ---",
            "file_path": "README.md",
            "start_line": 1,
            "end_line": 0,
            "name": "README"
        })

    for res in reranked_results[:top_k]:
        final_chunks.append(res["meta"])
        
    return final_chunks