import os
import time
import asyncio
import sys
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    groq_api_key: str
    gemini_api_key: str
    
    model_config = SettingsConfigDict(
        env_file='../.env', 
        env_file_encoding='utf-8', 
        extra='ignore',
        case_sensitive=False
    )

try:
    settings = Settings()
    if settings.groq_api_key == "your_groq_api_key_here" or settings.gemini_api_key == "your_gemini_api_key_here":
        print("CRITICAL: You are still using placeholder API keys in your .env file.")
        print("Please replace 'your_groq_api_key_here' and 'your_gemini_api_key_here' with real keys.")
        sys.exit(1)
except Exception as e:
    print(f"Failed to load configuration. Please ensure .env file is present and contains GROQ_API_KEY and GEMINI_API_KEY.")
    print(f"Error details: {e}")
    sys.exit(1)

class RateLimiter:
    def __init__(self, calls_per_minute: int):
        self.calls_per_minute = calls_per_minute
        self.calls = []
    
    async def acquire(self):
        now = time.time()
        self.calls = [c for c in self.calls if now - c < 60]
        if len(self.calls) >= self.calls_per_minute:
            sleep_time = 60 - (now - self.calls[0]) + 0.1
            await asyncio.sleep(sleep_time)
        self.calls.append(time.time())

# Shared rate limiters across all concurrent requests
groq_rate_limiter = RateLimiter(calls_per_minute=28)
gemini_rate_limiter = RateLimiter(calls_per_minute=14)
