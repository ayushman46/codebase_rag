from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel
from ingest.pipeline import run_ingestion
from database import supabase
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
    github_url = req.github_url
    if not github_url.startswith("https://github.com/"):
        raise HTTPException(status_code=400, detail="Must be a valid public GitHub URL")
        
    repo_name = github_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
        
    background_tasks.add_task(run_ingestion, github_url, current_user.id)
    return {"message": "Ingestion started", "repo_name": repo_name}
