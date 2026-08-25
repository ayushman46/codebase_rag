import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user
from database import (
    DatabaseConfigurationError,
    assert_supabase_schema,
    get_ingestion_supabase_client,
    get_user_scoped_supabase,
    explain_supabase_api_error,
)
from ingest.pipeline import IngestionConflictError, enqueue_ingestion_job, ensure_repo_record

logger = logging.getLogger(__name__)
router = APIRouter()


async def run_query(query):
    return await asyncio.to_thread(query.execute)


async def scoped_client(access_token: str):
    try:
        assert_supabase_schema()
        return get_user_scoped_supabase(access_token)
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/status/{repo_name}")
async def get_status(repo_name: str, current_user=Depends(get_current_user)):
    supabase_client = await scoped_client(current_user.access_token)
    try:
        res = await run_query(
            supabase_client.table("repos").select("status, chunk_count, error_message")
            .eq("repo_name", repo_name).eq("user_id", current_user.id)
        )
    except Exception as error:
        logger.exception("Could not fetch repository status")
        raise HTTPException(status_code=502, detail="Could not fetch repository status.") from error
    if not res.data:
        raise HTTPException(status_code=404, detail="Repository not found.")
    return res.data[0]


@router.get("/repos")
async def list_repos(current_user=Depends(get_current_user)):
    supabase_client = await scoped_client(current_user.access_token)
    try:
        res = await run_query(
            supabase_client.table("repos")
            .select("id, repo_name, github_url, status, chunk_count, created_at, error_message")
            .eq("user_id", current_user.id).order("created_at", desc=True)
        )
        return res.data
    except Exception as error:
        logger.exception("Could not list repositories")
        raise HTTPException(status_code=502, detail="Could not list repositories.") from error


@router.delete("/repos/{repo_name}")
async def delete_repo(repo_name: str, current_user=Depends(get_current_user)):
    supabase_client = await scoped_client(current_user.access_token)
    try:
        existing = await run_query(
            supabase_client.table("repos").select("id").eq("repo_name", repo_name).eq("user_id", current_user.id)
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Repository not found.")
        await run_query(
            supabase_client.table("repos").delete().eq("repo_name", repo_name).eq("user_id", current_user.id)
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Could not delete repository")
        raise HTTPException(status_code=502, detail="Could not delete repository.") from error
    return {"message": f"Repository {repo_name} deleted successfully"}


@router.post("/repos/{repo_name}/reindex")
async def reindex_repository(repo_name: str, current_user=Depends(get_current_user)):
    """Requeue an existing repository without relying on frontend URL state."""
    try:
        assert_supabase_schema()
        supabase_client = get_ingestion_supabase_client()
        existing = await run_query(
            supabase_client.table("repos").select("github_url")
            .eq("repo_name", repo_name).eq("user_id", current_user.id).limit(1)
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Repository not found.")
        repo_id, normalized_name = await ensure_repo_record(
            supabase_client, existing.data[0]["github_url"], current_user.id
        )
        await enqueue_ingestion_job(supabase_client, existing.data[0]["github_url"], current_user.id, repo_id)
    except HTTPException:
        raise
    except IngestionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not re-index repository")
        raise HTTPException(status_code=502, detail=explain_supabase_api_error(error)) from error
    return {"message": "Repository queued for re-indexing", "repo_name": normalized_name}


@router.post("/repos/{repo_name}/cancel-indexing")
async def cancel_indexing(repo_name: str, current_user=Depends(get_current_user)):
    try:
        assert_supabase_schema()
        supabase_client = get_ingestion_supabase_client()
        existing = await run_query(
            supabase_client.table("repos").select("id, status")
            .eq("repo_name", repo_name).eq("user_id", current_user.id).limit(1)
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Repository not found.")
        repo = existing.data[0]
        if repo["status"] not in {"queued", "cloning", "chunking", "embedding", "summarizing"}:
            raise HTTPException(status_code=409, detail="This repository is not currently being indexed.")

        await run_query(
            supabase_client.table("ingestion_jobs").update({
                "status": "cancelled", "finished_at": None, "claimed_at": None,
                "last_error": "Indexing stopped by the user.",
            }).eq("repo_id", repo["id"])
        )
        await run_query(supabase_client.table("chunks").delete().eq("repo_id", repo["id"]))
        await run_query(supabase_client.table("kt_cache").delete().eq("repo_id", repo["id"]))
        await run_query(
            supabase_client.table("repos").update({
                "status": "cancelled", "chunk_count": 0, "error_message": "Indexing stopped by you.",
            }).eq("id", repo["id"])
        )
    except HTTPException:
        raise
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not cancel repository ingestion")
        raise HTTPException(status_code=502, detail="Could not stop repository indexing. Please try again.") from error
    return {"message": "Indexing stopped", "repo_name": repo_name}
