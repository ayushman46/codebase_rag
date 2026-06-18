import os
import json
import pickle
import faiss
import numpy as np
import networkx as nx
from rank_bm25 import BM25Okapi
from typing import List
from .chunker import CodeChunk

INDEXES_DIR = "./indexes"

def build_and_save_indexes(repo_name: str, chunks: List[CodeChunk]):
    repo_index_dir = os.path.join(INDEXES_DIR, repo_name)
    os.makedirs(repo_index_dir, exist_ok=True)
    
    # 1. Save chunks metadata
    metadata_path = os.path.join(repo_index_dir, "chunks_metadata.json")
    metadata_list = []
    for c in chunks:
        c_dict = {
            "id": c.id,
            "content": c.content,
            "file_path": c.file_path,
            "language": c.language,
            "node_type": c.node_type,
            "name": c.name,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "parent_class": c.parent_class,
            "imports": c.imports,
            "calls": c.calls,
            "variables": c.variables,
            "routes": c.routes,
            "docstring": c.docstring
        }
        metadata_list.append(c_dict)
        
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata_list, f, indent=2)
        
    if not chunks:
        update_registry(repo_name, "ready", 0)
        return

    # 2. Build and save FAISS index
    embeddings = np.array([c.embedding for c in chunks], dtype=np.float32)
    dim = embeddings.shape[1]
    faiss_index = faiss.IndexFlatL2(dim)
    faiss_index.add(embeddings)
    
    faiss_dir = os.path.join(repo_index_dir, "faiss_index")
    os.makedirs(faiss_dir, exist_ok=True)
    faiss.write_index(faiss_index, os.path.join(faiss_dir, "index.faiss"))
    
    # 3. Build and save BM25
    tokenized_corpus = [c.content.split() for c in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    
    bm25_path = os.path.join(repo_index_dir, "bm25.pkl")
    with open(bm25_path, 'wb') as f:
        pickle.dump(bm25, f)
        
    # 4. Build and save Knowledge Graph (NetworkX)
    G = nx.MultiDiGraph()
    
    # Add nodes for chunks and files
    for c in chunks:
        # Node for the chunk itself (Function/Class)
        G.add_node(c.id, label=c.name, type=c.node_type, file=c.file_path)
        
        # Edge: File contains Chunk
        G.add_edge(c.file_path, c.id, relation="contains")
        
        # Edge: Class contains Method
        if c.parent_class:
            # Find the parent class chunk ID
            parent_ids = [p.id for p in chunks if p.name == c.parent_class and p.file_path == c.file_path]
            for pid in parent_ids:
                G.add_edge(pid, c.id, relation="defines")

        # Edges: Function calls
        for call in c.calls:
            # Try to find what function/class this call refers to
            # This is heuristic and improved by LLM later
            target_ids = [t.id for t in chunks if t.name == call]
            for tid in target_ids:
                G.add_edge(c.id, tid, relation="calls")

    graph_path = os.path.join(repo_index_dir, "graph.pkl")
    with open(graph_path, 'wb') as f:
        pickle.dump(G, f)

    # 5. Update Registry
    update_registry(repo_name, "ready", len(chunks))

def update_registry(repo_name: str, status: str, chunk_count: int = 0):
    os.makedirs(INDEXES_DIR, exist_ok=True)
    registry_path = os.path.join(INDEXES_DIR, "registry.json")
    registry = {}
    if os.path.exists(registry_path):
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)
            
    registry[repo_name] = {
        "status": status,
        "chunk_count": chunk_count
    }
    
    with open(registry_path, 'w', encoding='utf-8') as f:
        json.dump(registry, f, indent=2)