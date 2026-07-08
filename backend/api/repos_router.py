from fastapi import APIRouter, HTTPException, Depends
from database import supabase
from api.auth import get_current_user

router = APIRouter()

@router.get("/status/{repo_name}")
def get_status(repo_name: str, current_user = Depends(get_current_user)):
    res = supabase.table('repos').select('*').eq('repo_name', repo_name).eq('user_id', current_user.id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Repo not found")
    repo = res.data[0]
    return {
        "status": repo['status'],
        "chunk_count": repo['chunk_count'],
        "error_message": repo['error_message']
    }

@router.get("/repos")
def list_repos(current_user = Depends(get_current_user)):
    res = supabase.table('repos')\
        .select('id, repo_name, github_url, status, chunk_count, created_at, error_message')\
        .eq('user_id', current_user.id)\
        .order('created_at', desc=True).execute()
    return res.data

@router.delete("/repos/{repo_name}")
def delete_repo(repo_name: str, current_user = Depends(get_current_user)):
    supabase.table('repos').delete().eq('repo_name', repo_name).eq('user_id', current_user.id).execute()
    return {"message": f"Repo {repo_name} deleted successfully"}
