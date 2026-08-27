import asyncio
import time
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    # A strong, low-latency MoE model for source-grounded RAG. It has far fewer
    # active parameters than Ultra while retaining long-context coding support.
    nemotron_model: str = "nvidia/nemotron-3-super-120b-a12b"
    detailed_nemotron_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    embedding_model: str = "nvidia/nemotron-3-embed-1b"
    embedding_dimension: int = 2048
    nvidia_timeout_seconds: float = 90.0
    nvidia_calls_per_minute: int = 20
    # Preserve a few embedding slots for interactive questions while a large
    # repository is being indexed in the background.
    query_embedding_reserve_per_minute: int = 4
    # Answers are source-grounded and intentionally concise. Avoiding extended
    # reasoning and oversized generations keeps the interactive chat responsive.
    nvidia_enable_thinking: bool = False
    answer_max_tokens: int = 900
    detailed_nvidia_enable_thinking: bool = True
    detailed_answer_max_tokens: int = 1_800
    # Keep hosted embedding requests deliberately small. Code chunks can be
    # substantially larger than ordinary chat inputs, and large batches are
    # more likely to be rejected by a shared hosted endpoint.
    embedding_batch_size: int = 4
    # Shared hosted capacity can return a short-lived 503. Five attempts with
    # backoff provide a 30-second recovery window before a job is failed.
    embedding_retry_attempts: int = 5
    embedding_retry_base_seconds: float = 2.0
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_role_key: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Protect the service from excessively large repository ingestion jobs.
    max_repository_files: int = 5_000
    max_repository_bytes: int = 25_000_000
    # Source files are chunked before embedding, so this is a per-file safety
    # limit rather than a provider input limit. Five MB covers large source and
    # schema files while the repository-wide limits below remain in effect.
    max_file_size_bytes: int = 5_000_000
    max_repository_chunks: int = 1_500
    # Retain enough diverse evidence for accurate multi-file answers without
    # turning each question into an excessively large hosted-model request.
    max_context_characters: int = 40_000
    retrieval_top_k: int = 8
    conversation_history_messages: int = 6
    max_conversation_history_characters: int = 7_200
    max_conversation_message_characters: int = 1_800
    ingestion_job_timeout_seconds: int = 900
    max_ingestion_attempts: int = 3
    # Run the durable worker in-process so jobs do not remain queued indefinitely.
    local_ingestion_worker: bool = True
    local_ingestion_poll_seconds: float = 3.0

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()


class ModelConfigurationError(RuntimeError):
    """Raised only when a request needs an unavailable LLM configuration."""


def require_nvidia_api_key() -> str:
    key = settings.nvidia_api_key.strip()
    if not key:
        raise ModelConfigurationError(
            "NVIDIA is not configured. Set NVIDIA_API_KEY in the project root .env file and retry."
        )
    return key


def get_cors_origins() -> list[str]:
    return [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]


def should_run_local_ingestion_worker() -> bool:
    """Return whether this service instance should process queued ingestion jobs."""
    return settings.local_ingestion_worker


def get_answer_model_options(profile: str) -> tuple[str, bool, int]:
    """Resolve an allow-listed chat profile without accepting model IDs from clients."""
    if profile == "detailed":
        return (
            settings.detailed_nemotron_model,
            settings.detailed_nvidia_enable_thinking,
            settings.detailed_answer_max_tokens,
        )
    return settings.nemotron_model, settings.nvidia_enable_thinking, settings.answer_max_tokens


class RateLimiter:
    def __init__(self, calls_per_minute: int):
        self.calls_per_minute = calls_per_minute
        self.calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Acquire without holding the lock while waiting for a slot."""
        while True:
            async with self._lock:
                now = time.time()
                self.calls = [call for call in self.calls if now - call < 60]
                if len(self.calls) < self.calls_per_minute:
                    self.calls.append(now)
                    return
                sleep_time = max(0.1, 60 - (now - self.calls[0]))
            await asyncio.sleep(sleep_time)


nvidia_rate_limiter = RateLimiter(calls_per_minute=settings.nvidia_calls_per_minute)
