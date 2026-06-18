import os
import json
import shutil
from fastapi import APIRouter

router = APIRouter(prefix="/api")

@router.get("/repos")
async def list_repos():
    registry_path = "./indexes/registry.json"
    if not os.path.exists(registry_path):
        return {}
    with open(registry_path, 'r', encoding='utf-8') as f:
        return json.load(f)

@router.delete("/repos/{repo_name}")
async def delete_repo(repo_name: str):
    registry_path = "./indexes/registry.json"
    
    # Update registry
    if os.path.exists(registry_path):
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        if repo_name in registry:
            del registry[repo_name]
        with open(registry_path, 'w', encoding='utf-8') as f:
            json.dump(registry, f, indent=2)
            
    # Remove files
    indexes_dir = f"./indexes/{repo_name}"
    repos_dir = f"./repos/{repo_name}"
    
    if os.path.exists(indexes_dir):
        shutil.rmtree(indexes_dir)
    if os.path.exists(repos_dir):
        shutil.rmtree(repos_dir)
        
    return {"message": f"Repo {repo_name} deleted successfully"}