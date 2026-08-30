import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user
from config import ingest_request_limiter
from database import DatabaseConfigurationError, assert_turso_schema, get_turso_store
from ingest.cloner import RepositoryValidationError, normalize_github_url
from ingest.pipeline import IngestionConflictError, enqueue_ingestion_job, enforce_ingestion_capacity, ensure_repo_record

logger = logging.getLogger(__name__)
router = APIRouter()


class IngestRequest(BaseModel):
    github_url: str = Field(min_length=1, max_length=2_048)


@router.post("/ingest")
async def ingest_repo(req: IngestRequest, current_user=Depends(get_current_user)):
    limiter_acquired = False
    try:
        await ingest_request_limiter.acquire(current_user.id)
        limiter_acquired = True
        await assert_turso_schema()
        github_url = normalize_github_url(req.github_url)
        # Turso is server-only. The verified Supabase user id is persisted on
        # each record and is required again by all user-facing queries.
        store = get_turso_store()
        await enforce_ingestion_capacity(store, current_user.id, github_url)
        repo_id, repo_name = await ensure_repo_record(store, github_url, current_user.id)
        await enqueue_ingestion_job(store, github_url, current_user.id, repo_id)
    except RepositoryValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except IngestionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RuntimeError as error:
        if str(error) in {"rate_limit", "concurrency_limit"}:
            raise HTTPException(status_code=429, detail="Too many repository requests. Please wait a moment and try again.") from error
        raise
    except Exception as error:
        logger.exception("Could not start repository ingestion")
        raise HTTPException(status_code=500, detail="Could not start repository ingestion.") from error
    finally:
        if limiter_acquired:
            await ingest_request_limiter.release(current_user.id)

    return {"message": "Ingestion queued", "repo_name": repo_name}
