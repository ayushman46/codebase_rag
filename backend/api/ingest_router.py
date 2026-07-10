from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel
from ingest.pipeline import ensure_repo_record, run_ingestion_for_repo
from database import assert_supabase_schema, DatabaseConfigurationError, get_user_scoped_supabase
from api.auth import get_current_user

router = APIRouter()

class IngestRequest(BaseModel):
    github_url: str

@router.post("/ingest")
async def ingest_repo(
    req: IngestRequest, 
    background_tasks: BackgroundTasks, 
    current_user = Depends(get_current_user)
):
    try:
        assert_supabase_schema()
    except DatabaseConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))

    github_url = req.github_url
    if not github_url.startswith("https://github.com/"):
        raise HTTPException(status_code=400, detail="Must be a valid public GitHub URL")

    supabase = get_user_scoped_supabase(current_user.access_token)
    repo_id, repo_name = await ensure_repo_record(supabase, github_url, current_user.id)
    background_tasks.add_task(
        run_ingestion_for_repo,
        supabase,
        github_url,
        current_user.id,
        repo_id
    )
    return {"message": "Ingestion started", "repo_name": repo_name}
