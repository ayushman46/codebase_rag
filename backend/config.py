import asyncio
import time
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nemotron_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    nvidia_timeout_seconds: float = 90.0
    nvidia_calls_per_minute: int = 20
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_role_key: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_repository_files: int = 10_000
    max_repository_bytes: int = 50_000_000
    max_repository_chunks: int = 20_000
    max_context_characters: int = 60_000

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
