import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user
from database import DatabaseConfigurationError, assert_supabase_schema, get_user_scoped_supabase
from ingest.cloner import RepositoryValidationError, normalize_github_url
from ingest.pipeline import IngestionConflictError, ensure_repo_record, run_ingestion_for_repo

logger = logging.getLogger(__name__)
router = APIRouter()


class IngestRequest(BaseModel):
    github_url: str = Field(min_length=1, max_length=2_048)


@router.post("/ingest")
async def ingest_repo(req: IngestRequest, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    try:
        assert_supabase_schema()
        github_url = normalize_github_url(req.github_url)
        supabase_client = get_user_scoped_supabase(current_user.access_token)
        repo_id, repo_name = await ensure_repo_record(supabase_client, github_url, current_user.id)
    except RepositoryValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except IngestionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not start repository ingestion")
        raise HTTPException(status_code=500, detail="Could not start repository ingestion.") from error

    background_tasks.add_task(run_ingestion_for_repo, supabase_client, github_url, current_user.id, repo_id)
    return {"message": "Ingestion started", "repo_name": repo_name}
