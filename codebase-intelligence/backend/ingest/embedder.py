from sentence_transformers import SentenceTransformer
from typing import List
from .chunker import CodeChunk

# Load model globally to avoid reloading on every request
# all-MiniLM-L6-v2 runs locally without API keys
model = SentenceTransformer('all-MiniLM-L6-v2')

def embed_chunks(chunks: List[CodeChunk]) -> List[CodeChunk]:
    if not chunks:
        return chunks
        
    # We enrich the text sent to the embedder with context
    texts_to_embed = [
        f"File: {c.file_path}\nName: {c.name}\nType: {c.node_type}\nContent:\n{c.content}"
        for c in chunks
    ]
    
    embeddings = model.encode(texts_to_embed, show_progress_bar=False)
    
    for chunk, emb in zip(chunks, embeddings):
        chunk.embedding = emb.tolist()
        
    return chunks