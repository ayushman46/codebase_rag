import threading
import time
from collections import deque
from typing import Dict, List

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from config import require_nvidia_api_key, settings

EMBEDDING_DIMENSION = settings.embedding_dimension
_client = None
_request_times: deque[float] = deque()
_rate_limit_lock = threading.Lock()


class EmbeddingUnavailableError(RuntimeError):
    pass


def wait_for_embedding_slot():
    """Throttle hosted embedding requests across ingestion and query threads."""
    calls_per_minute = max(1, settings.nvidia_calls_per_minute)
    while True:
        with _rate_limit_lock:
            now = time.monotonic()
            while _request_times and now - _request_times[0] >= 60:
                _request_times.popleft()
            if len(_request_times) < calls_per_minute:
                _request_times.append(now)
                return
            wait_seconds = max(0.1, 60 - (now - _request_times[0]))
        time.sleep(wait_seconds)


def should_retry_embedding_error(error: Exception) -> bool:
    if isinstance(error, (APITimeoutError, APIConnectionError)):
        return True
    return isinstance(error, APIStatusError) and error.status_code in {429, 500, 502, 503, 504}


def embedding_retry_delay(error: Exception, attempt: int) -> float:
    """Prefer the provider's cooldown hint, otherwise use bounded backoff."""
    response = getattr(error, "response", None)
    retry_after = response.headers.get("retry-after") if response is not None else None
    try:
        if retry_after is not None:
            return min(60.0, max(0.1, float(retry_after)))
    except (TypeError, ValueError):
        pass
    return min(30.0, settings.embedding_retry_base_seconds * (2 ** attempt))


def get_embedding_client():
    """Return the hosted NVIDIA embedding client."""
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
    last_error: Exception | None = None
    attempts = max(1, settings.embedding_retry_attempts)
    for attempt in range(attempts):
        try:
            wait_for_embedding_slot()
            response = get_embedding_client().embeddings.create(
                model=settings.embedding_model,
                input=texts,
                extra_body={"input_type": input_type, "truncate": "END"},
            )
            vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
            last_error = None
            break
        except Exception as error:
            last_error = error
            if not should_retry_embedding_error(error) or attempt == attempts - 1:
                break
            time.sleep(embedding_retry_delay(error, attempt))
    else:  # pragma: no cover - the loop always breaks or returns a response.
        last_error = RuntimeError("Embedding retry loop ended unexpectedly.")

    if last_error is not None:
        if isinstance(last_error, APITimeoutError):
            raise EmbeddingUnavailableError("NVIDIA timed out while creating repository embeddings after retries.") from last_error
        if isinstance(last_error, APIConnectionError):
            raise EmbeddingUnavailableError("Could not connect to NVIDIA for repository embeddings after retries.") from last_error
        if isinstance(last_error, APIStatusError):
            raise EmbeddingUnavailableError(
                f"NVIDIA could not create repository embeddings after retries (HTTP {last_error.status_code})."
            ) from last_error
        raise EmbeddingUnavailableError("NVIDIA returned an invalid embedding response.") from last_error

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

    # NVIDIA's hosted endpoint is most reliable when code-heavy requests stay
    # small. This is configurable for paid/dedicated deployments, but four is
    # a conservative default for the shared endpoint.
    batch_size = max(1, settings.embedding_batch_size)

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
