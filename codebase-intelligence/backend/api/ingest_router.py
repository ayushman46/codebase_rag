import os
import json
import asyncio
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from ingest.cloner import clone_repo, get_files_to_index
from ingest.parser import parse_file
from ingest.embedder import embed_chunks
from ingest.indexer import build_and_save_indexes, update_registry
from ingest.summarizer import build_kt_cache

router = APIRouter(prefix="/api")

class IngestRequest(BaseModel):
    github_url: str

def run_ingestion(github_url: str):
    repo_name = github_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
        
    try:
        update_registry(repo_name, "cloning")
        repo_path = clone_repo(github_url)
        
        update_registry(repo_name, "parsing")
        files_info = get_files_to_index(repo_path)
        
        all_chunks = []
        for file_info in files_info:
            try:
                chunks = parse_file(file_info["path"], repo_path, file_info["language"], file_info["type"])
                all_chunks.extend(chunks)
            except Exception as parse_e:
                print(f"Warning: Failed to parse {file_info['path']}: {parse_e}")
                continue
            
        update_registry(repo_name, "embedding")
        embedded_chunks = embed_chunks(all_chunks)
        
        update_registry(repo_name, "indexing")
        build_and_save_indexes(repo_name, embedded_chunks)
        
        update_registry(repo_name, "summarizing")
        # Run async function in a new loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(build_kt_cache(repo_name, embedded_chunks))
        loop.close()
        
        update_registry(repo_name, "ready", len(embedded_chunks))
    except Exception as e:
        print(f"Ingestion failed for {repo_name}: {e}")
        update_registry(repo_name, "error")

@router.post("/ingest")
async def ingest_repo(request: IngestRequest, background_tasks: BackgroundTasks):
    repo_name = request.github_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
        
    background_tasks.add_task(run_ingestion, request.github_url)
    return {"message": "Ingestion started", "repo_name": repo_name}

@router.get("/status/{repo_name}")
async def get_status(repo_name: str):
    registry_path = "./indexes/registry.json"
    if not os.path.exists(registry_path):
        raise HTTPException(status_code=404, detail="Registry not found")
        
    with open(registry_path, 'r', encoding='utf-8') as f:
        registry = json.load(f)
        
    if repo_name not in registry:
        raise HTTPException(status_code=404, detail="Repo not found in registry")
        
    return registry[repo_name]