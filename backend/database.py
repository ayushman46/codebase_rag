from supabase import create_client, Client
from config import settings

def get_supabase_client() -> Client:
    if not settings.supabase_url or not settings.supabase_key:
        raise ValueError("Supabase credentials not configured.")
    return create_client(settings.supabase_url, settings.supabase_key)

supabase = get_supabase_client()
