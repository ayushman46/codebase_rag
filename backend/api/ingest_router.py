import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user
from database import DatabaseConfigurationError, assert_supabase_schema, get_user_scoped_supabase
from ingest.cloner import RepositoryValidationError, normalize_github_url
from ingest.pipeline import IngestionConflictError, enqueue_ingestion_job, ensure_repo_record

logger = logging.getLogger(__name__)
router = APIRouter()


class IngestRequest(BaseModel):
    github_url: str = Field(min_length=1, max_length=2_048)


@router.post("/ingest")
async def ingest_repo(req: IngestRequest, current_user=Depends(get_current_user)):
    try:
        assert_supabase_schema()
        github_url = normalize_github_url(req.github_url)
        supabase_client = get_user_scoped_supabase(current_user.access_token)
        repo_id, repo_name = await ensure_repo_record(supabase_client, github_url, current_user.id)
        await enqueue_ingestion_job(supabase_client, github_url, current_user.id, repo_id)
    except RepositoryValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except IngestionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not start repository ingestion")
        raise HTTPException(status_code=500, detail="Could not start repository ingestion.") from error

    return {"message": "Ingestion queued", "repo_name": repo_name}
