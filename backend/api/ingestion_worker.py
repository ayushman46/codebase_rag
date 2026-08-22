"""Private Vercel Cron endpoint for durable Supabase-backed ingestion jobs."""

from fastapi import APIRouter, Header, HTTPException, status

from config import settings
from database import DatabaseConfigurationError, assert_supabase_schema, get_supabase_client
from ingest.pipeline import process_one_queued_ingestion

router = APIRouter()


@router.get("/process-ingestions", include_in_schema=False)
async def process_ingestions(authorization: str | None = Header(default=None)):
    expected = settings.cron_secret.strip()
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    try:
        assert_supabase_schema()
        return await process_one_queued_ingestion(get_supabase_client())
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
