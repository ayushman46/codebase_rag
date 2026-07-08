import os
import time
import asyncio
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    groq_api_key: str = ""
    gemini_api_key: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    
    model_config = SettingsConfigDict(
        env_file='../.env', 
        env_file_encoding='utf-8', 
        extra='ignore',
        case_sensitive=False
    )

settings = Settings()

if not all([settings.groq_api_key, settings.gemini_api_key, settings.supabase_url, settings.supabase_key]):
    print("Warning: Missing one or more API keys in .env file.")

class RateLimiter:
    def __init__(self, calls_per_minute: int):
        self.calls_per_minute = calls_per_minute
        self.calls = []
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        async with self._lock:
            now = time.time()
            # Remove calls older than 60 seconds
            self.calls = [c for c in self.calls if now - c < 60]
            if len(self.calls) >= self.calls_per_minute:
                sleep_time = 60 - (now - self.calls[0]) + 0.1
                await asyncio.sleep(sleep_time)
                now = time.time()
            self.calls.append(now)

# Groq free tier limit ~30 RPM. Let's use 28 to be safe.
groq_rate_limiter = RateLimiter(calls_per_minute=28)
# Gemini free tier limit 15 RPM. Let's use 14.
gemini_rate_limiter = RateLimiter(calls_per_minute=14)
