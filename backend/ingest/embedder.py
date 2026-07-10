import hashlib
import math
import re
from typing import List, Dict
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
_model = None


class HashingEmbedder:
    def encode(self, texts, show_progress_bar=False, batch_size=None):
        return [hash_embed(text) for text in texts]


def get_embedding_model():
    global _model
    if _model is not None:
        return _model

    try:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
    except Exception:
        try:
            _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        except Exception as e:
            print(f"Warning: falling back to hashing embeddings: {e}")
            _model = HashingEmbedder()

    return _model

def embed_chunks(chunks: List[Dict]) -> List[Dict]:
    if not chunks:
        return chunks

    model = get_embedding_model()
    batch_size = 32

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts_to_embed = [
            f"File: {c['file_path']}\nContent:\n{c['content']}"
            for c in batch
        ]
        embeddings = model.encode(
            texts_to_embed,
            show_progress_bar=False,
            batch_size=batch_size
        )

        for chunk, emb in zip(batch, embeddings):
            chunk['embedding'] = emb.tolist() if hasattr(emb, "tolist") else list(emb)
        
    return chunks


def hash_embed(text: str) -> List[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_./:-]*", text.lower())

    for token in tokens[:4000]:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % EMBEDDING_DIMENSION
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector

    return [v / norm for v in vector]
