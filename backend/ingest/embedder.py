from typing import List, Dict
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
_model = None


class EmbeddingUnavailableError(RuntimeError):
    pass


def get_embedding_model():
    global _model
    if _model is not None:
        return _model

    try:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
    except Exception as error:
        raise EmbeddingUnavailableError(
            "The local embedding model is unavailable. Pre-download "
            f"{EMBEDDING_MODEL_NAME} before ingesting repositories."
        ) from error

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
