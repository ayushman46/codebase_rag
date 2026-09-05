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
    # Dedicated code-review model. Qwen2.5-Coder is served through the same
    # OpenAI-compatible NVIDIA endpoint and is trained specifically for code
    # generation, reasoning, and fixing. Keep a second free catalog model as
    # a provider-side fallback when the primary endpoint is unavailable.
    # Use models confirmed available to the configured NVIDIA account. The
    # Super model is trained for coding and long-context agentic work; the
    # Lightning model is a smaller fallback when the primary is busy.
    code_editing_model: str = "nvidia/nemotron-3-super-120b-a12b"
    code_editing_fallback_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
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
    code_editing_enable_thinking: bool = False
    code_editing_answer_max_tokens: int = 2_400
    code_editing_retry_attempts: int = 3
    # Interactive answers fail fast enough to keep the chat responsive. Long
    # embedding jobs retain their separate retry budget below.
    answer_retry_attempts: int = 2
    # Keep hosted embedding requests deliberately small. Code chunks can be
    # substantially larger than ordinary chat inputs, and large batches are
    # more likely to be rejected by a shared hosted endpoint.
    # Sixteen passages per request reduces provider round trips. The embedder
    # adaptively halves a rejected payload and never drops a chunk.
    embedding_batch_size: int = 16
    embedding_min_batch_size: int = 4
    # Aggregate chunks from small files before embedding. This avoids one
    # under-filled provider request per file while keeping peak memory bounded
    # on the 512 MB Render instance.
    embedding_chunk_buffer_size: int = 64
    # Shared hosted capacity can return a short-lived 503. Five attempts with
    # backoff provide a 30-second recovery window before a job is failed.
    embedding_retry_attempts: int = 5
    embedding_retry_base_seconds: float = 2.0
    # Progress is user-facing metadata; cancellation is still checked for
    # every batch, while these less frequent writes reduce Turso contention.
    embedding_progress_interval_batches: int = 4
    embedding_heartbeat_interval_batches: int = 2
    # Persisting a few hundred chunks per transaction materially reduces
    # Turso round trips for large repositories while staying below the
    # provider's request-size limits. The pipeline still checks cancellation
    # between batches.
    chunk_insert_batch_size: int = 250
    supabase_url: str = ""
    supabase_key: str = ""
    # Supabase remains the authentication provider. All application data is
    # stored through this server-only Turso connection.
    turso_database_url: str = ""
    turso_auth_token: str = ""
    # Billing is server-only. The public Razorpay key is exposed separately
    # through VITE_RAZORPAY_KEY_ID for the checkout widget.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    team_plan_amount_paise: int = 30_000
    team_plan_duration_days: int = 30
    # Explorer quota is cumulative indexed source across a user's repositories.
    free_codebase_bytes: int = 200_000_000
    # Team quota is configurable and deliberately finite; do not imply unlimited storage.
    team_codebase_bytes: int = 800_000_000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Protect the service from excessively large repository ingestion jobs.
    max_repository_files: int = 5_000
    max_repository_bytes: int = 100_000_000
    # Source files are chunked before embedding, so this is a per-file safety
    # limit rather than a provider input limit. Fifty MB covers large source
    # and schema files while the repository-wide limit remains in effect.
    max_file_size_bytes: int = 50_000_000
    max_repository_chunks: int = 3_500
    # GitHub OAuth & Git Data API integration
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = ""
    github_frontend_origin: str = ""
    # Render exposes the canonical public service URL automatically. It lets
    # GitHub OAuth work safely when the explicit callback variable has not yet
    # been added to a deployment, without guessing from an untrusted Host
    # header.
    render_external_url: str = ""
    github_oauth_state_ttl_seconds: int = 600
    github_token_encryption_key: str = ""
    # Signs short-lived, file-scoped tickets issued only by the editing query
    # flow. A ticket is required before the GitHub file and PR endpoints act.
    editing_ticket_secret: str = ""
    editing_ticket_ttl_seconds: int = 600
    max_github_change_bytes: int = 10_000_000
    github_editor_max_bytes: int = 2_000_000
    # Keep the shared worker and provider capacity fair across signed-in users.
    max_repositories_per_user: int = 30
    max_active_ingestion_jobs_per_user: int = 1
    ingest_requests_per_minute: int = 6
    query_requests_per_minute: int = 12
    max_concurrent_queries_per_user: int = 2
    clone_timeout_seconds: int = 180
    # Retain enough diverse evidence for accurate multi-file answers without
    # turning each question into an excessively large hosted-model request.
    max_context_characters: int = 40_000
    retrieval_top_k: int = 8
    editing_retrieval_top_k: int = 32
    # Dense reranking is restricted to lexical/path candidates so a question
    # never performs a repository-wide vector sort on Turso.
    dense_candidate_limit: int = 256
    # Broad architectural questions need a representative sample of the index
    # when no code-term match exists in the user's wording.
    overview_retrieval_candidates: int = 64
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
    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if "*" in origins:
        raise ValueError("CORS_ORIGINS must list explicit origins when credentials are enabled.")
    return origins


def should_run_local_ingestion_worker() -> bool:
    """Return whether this service instance should process queued ingestion jobs."""
    return settings.local_ingestion_worker


def get_editing_ticket_secret() -> str:
    """Return the dedicated ticket key, with GitHub's server key as fallback.

    Existing deployments already set GITHUB_TOKEN_ENCRYPTION_KEY for the PR
    integration. Reusing it only for HMAC signing keeps the new editing mode
    functional during a rolling deploy; EDITING_TICKET_SECRET can be set to a
    separate value when operators want independent key rotation.
    """
    return settings.editing_ticket_secret.strip() or settings.github_token_encryption_key.strip()


def get_answer_model_options(profile: str, workflow: str = "general") -> tuple[str, bool, int]:
    """Resolve an allow-listed chat profile without accepting model IDs from clients."""
    if workflow == "editing" or profile == "code":
        # Older Render environments may still carry the previously configured
        # Qwen/Codestral IDs. They are not served for every NVIDIA account;
        # transparently use the confirmed Nemotron IDs until those variables
        # are updated in the dashboard and the service is redeployed.
        unavailable_ids = {
            "qwen/qwen2.5-coder-32b-instruct",
            "qwen/qwen3-next-80b-a3b-instruct",
            "mistralai/codestral-22b-instruct-v0.1",
            "deepseek-ai/deepseek-coder-6.7b-instruct",
        }
        code_model = settings.code_editing_model if settings.code_editing_model not in unavailable_ids else "nvidia/nemotron-3-super-120b-a12b"
        return (
            code_model,
            settings.code_editing_enable_thinking,
            settings.code_editing_answer_max_tokens,
        )
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


class UserRequestLimiter:
    """Small process-local fairness guard for authenticated API work.

    Durable per-account quotas still live in Supabase. This limiter protects a
    single web process from bursts before expensive provider work begins.
    """

    def __init__(self, requests_per_minute: int, max_concurrent: int = 1):
        self.requests_per_minute = requests_per_minute
        self.max_concurrent = max_concurrent
        self._requests: dict[str, list[float]] = {}
        self._active: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: str) -> None:
        async with self._lock:
            now = time.monotonic()
            requests = [value for value in self._requests.get(user_id, []) if now - value < 60]
            if len(requests) >= self.requests_per_minute:
                raise RuntimeError("rate_limit")
            if self._active.get(user_id, 0) >= self.max_concurrent:
                raise RuntimeError("concurrency_limit")
            requests.append(now)
            self._requests[user_id] = requests
            self._active[user_id] = self._active.get(user_id, 0) + 1

    async def release(self, user_id: str) -> None:
        async with self._lock:
            active = max(0, self._active.get(user_id, 0) - 1)
            if active:
                self._active[user_id] = active
            else:
                self._active.pop(user_id, None)


ingest_request_limiter = UserRequestLimiter(settings.ingest_requests_per_minute)
query_request_limiter = UserRequestLimiter(
    settings.query_requests_per_minute,
    settings.max_concurrent_queries_per_user,
)
