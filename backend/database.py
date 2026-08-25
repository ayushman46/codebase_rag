import base64
import json
import logging
from functools import lru_cache
from typing import Optional

from postgrest.exceptions import APIError
from supabase import create_client
from config import settings

logger = logging.getLogger(__name__)

class DatabaseConfigurationError(RuntimeError):
    pass


class DeferredSupabaseClient:
    def __init__(self, message: str):
        self.message = message

    def __getattr__(self, _name):
        raise DatabaseConfigurationError(self.message)


def looks_like_service_role_key(key: str) -> bool:
    try:
        payload = decode_jwt_payload(key)
        return payload.get("role") == "service_role"
    except Exception:
        return False


def decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2:
        return {}

    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload + padding)
    return json.loads(decoded.decode("utf-8"))


def get_supabase_client():
    return build_supabase_client()


def build_supabase_client(access_token: Optional[str] = None):
    url = settings.supabase_url
    key = settings.supabase_service_role_key or settings.supabase_key
    message = (
        "Supabase is not configured correctly. Set SUPABASE_URL and a backend key "
        "(preferably SUPABASE_SERVICE_ROLE_KEY) in the project root .env file before starting the backend."
    )
    
    # Check for empty or placeholder values
    if not url or not key or "your_supabase_url_here" in url or "your_supabase_anon_key_here" in key:
        logger.warning("Supabase configuration is incomplete")
        return DeferredSupabaseClient(message)
        
    try:
        if not settings.supabase_service_role_key and not looks_like_service_role_key(key):
            logger.warning("Backend is not using a Supabase service role key; writes may be blocked by RLS")
        client = create_client(url, key)
        if access_token and not settings.supabase_service_role_key:
            client.postgrest.auth(access_token)
        return client
    except Exception:
        logger.exception("Failed to initialize Supabase client")
        return DeferredSupabaseClient(message)

supabase = get_supabase_client()


@lru_cache(maxsize=1)
def assert_supabase_schema():
    try:
        supabase.table("repos").select("id").limit(1).execute()
        supabase.table("chunks").select("symbols").limit(1).execute()
        supabase.table("ingestion_jobs").select("id").limit(1).execute()
        supabase.table("chat_messages").select("id").limit(1).execute()
    except DatabaseConfigurationError:
        raise
    except APIError as e:
        if (
            getattr(e, "code", "") in {"PGRST204", "PGRST205", "42703"}
            or "schema cache" in str(e).lower()
            or "does not exist" in str(e).lower()
        ):
            raise DatabaseConfigurationError(
                "Supabase schema is not initialized. Run supabase/00_init.sql in the Supabase SQL editor, "
                "then restart the backend."
            ) from e
        raise DatabaseConfigurationError(
            "Supabase schema could not be verified. Check the Supabase configuration and retry."
        ) from e
    except Exception as e:
        raise DatabaseConfigurationError(
            "Supabase is currently unavailable. Check the connection configuration and retry."
        ) from e


def explain_supabase_api_error(error: Exception) -> str:
    if isinstance(error, APIError):
        message = str(error)
        normalized_message = message.lower()
        if "dimensions" in normalized_message and "expected" in normalized_message:
            return (
                "Your Supabase database embedding dimension is incompatible with this application's NVIDIA "
                "2048-dimensional embeddings. Run the current supabase/00_init.sql in the Supabase SQL Editor once, "
                "then submit this repository again. Existing code chunks will be rebuilt during re-indexing."
            )
        if "row-level security" in normalized_message:
            return (
                "Supabase denied the write because the backend is not using a service role key. "
                "Set SUPABASE_SERVICE_ROLE_KEY in /Users/ayush/Downloads/codebase_rag/.env "
                "to your Supabase service_role key, then restart the backend."
            )
    return str(error)


def get_user_scoped_supabase(access_token: Optional[str]):
    if settings.supabase_service_role_key:
        return build_supabase_client()
    if not access_token:
        raise DatabaseConfigurationError(
            "No Supabase access token was available for this request. Sign in again and retry."
        )
    return build_supabase_client(access_token=access_token)
