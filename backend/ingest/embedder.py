from sentence_transformers import SentenceTransformer
from typing import List, Dict

# all-MiniLM-L6-v2 runs locally without API keys (384 dimensions)
model = SentenceTransformer('all-MiniLM-L6-v2')

def embed_chunks(chunks: List[Dict]) -> List[Dict]:
    if not chunks:
        return chunks
        
    texts_to_embed = [
        f"File: {c['file_path']}\nContent:\n{c['content']}"
        for c in chunks
    ]
    
    embeddings = model.encode(texts_to_embed, show_progress_bar=False)
    
    for chunk, emb in zip(chunks, embeddings):
        chunk['embedding'] = emb.tolist()
        
    return chunks
