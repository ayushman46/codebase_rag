from typing import Dict, List

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from config import require_nvidia_api_key, settings

EMBEDDING_DIMENSION = 1024
_client = None


class EmbeddingUnavailableError(RuntimeError):
    pass


def get_embedding_client():
    """Return the lightweight hosted-embedding client used on Vercel."""
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=settings.nvidia_base_url,
            api_key=require_nvidia_api_key(),
            timeout=settings.nvidia_timeout_seconds,
            max_retries=0,
        )
    return _client


def embed_texts(texts: List[str], *, input_type: str) -> List[List[float]]:
    """Generate NVIDIA embeddings, keeping indexing and search modes explicit."""
    if not texts:
        return []
    try:
        response = get_embedding_client().embeddings.create(
            model=settings.embedding_model,
            input=texts,
            extra_body={"input_type": input_type, "truncate": "END"},
        )
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    except APITimeoutError as error:
        raise EmbeddingUnavailableError("NVIDIA timed out while creating repository embeddings.") from error
    except APIConnectionError as error:
        raise EmbeddingUnavailableError("Could not connect to NVIDIA for repository embeddings.") from error
    except APIStatusError as error:
        raise EmbeddingUnavailableError(
            f"NVIDIA could not create repository embeddings (HTTP {error.status_code})."
        ) from error
    except Exception as error:
        raise EmbeddingUnavailableError("NVIDIA returned an invalid embedding response.") from error

    if len(vectors) != len(texts) or any(len(vector) != EMBEDDING_DIMENSION for vector in vectors):
        raise EmbeddingUnavailableError(
            f"NVIDIA returned embeddings incompatible with the expected {EMBEDDING_DIMENSION}-dimension schema."
        )
    return vectors


def embed_query(query: str) -> List[float]:
    return embed_texts([query], input_type="query")[0]

def embed_chunks(chunks: List[Dict]) -> List[Dict]:
    if not chunks:
        return chunks

    batch_size = 32

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts_to_embed = [
            f"File: {c['file_path']}\nContent:\n{c['content']}"
            for c in batch
        ]
        embeddings = embed_texts(texts_to_embed, input_type="passage")

        for chunk, emb in zip(batch, embeddings):
            chunk['embedding'] = list(emb)
        
    return chunks
