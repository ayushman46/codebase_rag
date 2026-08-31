"""Owned repository management backed by Turso."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user
from database import DatabaseConfigurationError, assert_turso_schema, explain_database_error, get_turso_store
from ingest.pipeline import ACTIVE_REPOSITORY_STATUSES, IngestionConflictError, enqueue_ingestion_job, enforce_ingestion_capacity, ensure_repo_record

logger = logging.getLogger(__name__)
router = APIRouter()


class RenameRepositoryRequest(BaseModel):
    repo_name: str = Field(min_length=1, max_length=200)


def now() -> str:
    return datetime.now(UTC).isoformat()


async def owned_repo(store, user_id: str, repo_name: str):
    repo = await store.fetch_one(
        "SELECT r.id, r.repo_name, r.github_url, r.status, r.chunk_count, r.error_message, r.created_at, "
        "COALESCE(c.total_seen_files, 0) AS total_seen_files, COALESCE(c.eligible_files, 0) AS eligible_files, "
        "COALESCE(c.indexed_files, 0) AS indexed_files, COALESCE(c.excluded_files, 0) AS excluded_files, "
        "COALESCE(c.excluded_bytes, 0) AS excluded_bytes, COALESCE(c.excluded_reasons, '{}') AS excluded_reasons, "
        "COALESCE(c.excluded_paths, '[]') AS excluded_paths "
        "FROM repos r LEFT JOIN repo_coverage c ON c.repo_id = r.id "
        "WHERE r.user_id = ? AND r.repo_name = ?",
        [user_id, repo_name],
    )
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
    return repo


@router.get("/status/{repo_name}")
async def get_status(repo_name: str, current_user=Depends(get_current_user)):
    try:
        await assert_turso_schema()
        repo = await owned_repo(get_turso_store(), current_user.id, repo_name)
        return {key: repo[key] for key in (
            "status", "chunk_count", "error_message", "total_seen_files", "eligible_files",
            "indexed_files", "excluded_files", "excluded_bytes", "excluded_reasons",
            "excluded_paths",
        )}
    except HTTPException:
        raise
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not fetch repository status")
        raise HTTPException(status_code=502, detail=explain_database_error(error)) from error


@router.get("/repos")
async def list_repos(current_user=Depends(get_current_user)):
    try:
        await assert_turso_schema()
        return await get_turso_store().fetch_all(
            "SELECT r.id, r.repo_name, r.github_url, r.status, r.chunk_count, r.created_at, r.error_message, "
            "COALESCE(c.total_seen_files, 0) AS total_seen_files, COALESCE(c.eligible_files, 0) AS eligible_files, "
            "COALESCE(c.indexed_files, 0) AS indexed_files, COALESCE(c.excluded_files, 0) AS excluded_files, "
            "COALESCE(c.excluded_bytes, 0) AS excluded_bytes, COALESCE(c.excluded_reasons, '{}') AS excluded_reasons, "
            "COALESCE(c.excluded_paths, '[]') AS excluded_paths "
            "FROM repos r LEFT JOIN repo_coverage c ON c.repo_id = r.id "
            "WHERE r.user_id = ? ORDER BY r.created_at DESC",
            [current_user.id],
        )
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not list repositories")
        raise HTTPException(status_code=502, detail=explain_database_error(error)) from error


@router.delete("/repos/{repo_name}")
async def delete_repo(repo_name: str, current_user=Depends(get_current_user)):
    try:
        await assert_turso_schema()
        store = get_turso_store()
        repo = await owned_repo(store, current_user.id, repo_name)
        if repo["status"] in ACTIVE_REPOSITORY_STATUSES:
            raise HTTPException(status_code=409, detail="Stop indexing before deleting this repository.")
        # Explicit deletes make cleanup reliable even if a Turso connection was
        # created without SQLite's per-connection foreign-key pragma.
        for table in ("chat_messages", "ingestion_jobs", "kt_cache", "repo_dependencies", "repo_files", "repo_coverage", "chunks"):
            await store.execute(f"DELETE FROM {table} WHERE repo_id = ?", [repo["id"]])
        await store.execute("DELETE FROM repos WHERE id = ? AND user_id = ?", [repo["id"], current_user.id])
    except HTTPException:
        raise
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not delete repository")
        raise HTTPException(status_code=502, detail=explain_database_error(error)) from error
    return {"message": f"Repository {repo_name} deleted successfully"}


@router.patch("/repos/{repo_name}")
async def rename_repo(repo_name: str, payload: RenameRepositoryRequest, current_user=Depends(get_current_user)):
    new_name = " ".join(payload.repo_name.split())
    if not new_name:
        raise HTTPException(status_code=422, detail="Repository name must contain visible text.")
    if any(character in new_name for character in ("/", "\\", "\x00")):
        raise HTTPException(status_code=422, detail="Repository names cannot contain path separators.")
    if new_name == repo_name:
        return {"repo_name": new_name}
    try:
        await assert_turso_schema()
        store = get_turso_store()
        repo = await owned_repo(store, current_user.id, repo_name)
        duplicate = await store.fetch_one(
            "SELECT id FROM repos WHERE user_id = ? AND repo_name = ?", [current_user.id, new_name]
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="You already have a repository with that name.")
        await store.execute(
            "UPDATE repos SET repo_name = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            [new_name, now(), repo["id"], current_user.id],
        )
    except HTTPException:
        raise
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not rename repository")
        raise HTTPException(status_code=502, detail=explain_database_error(error)) from error
    return {"repo_name": new_name}


@router.post("/repos/{repo_name}/reindex")
async def reindex_repository(repo_name: str, current_user=Depends(get_current_user)):
    try:
        await assert_turso_schema()
        store = get_turso_store()
        existing = await owned_repo(store, current_user.id, repo_name)
        await enforce_ingestion_capacity(store, current_user.id, existing["github_url"])
        repo_id, normalized_name = await ensure_repo_record(store, existing["github_url"], current_user.id)
        await enqueue_ingestion_job(store, existing["github_url"], current_user.id, repo_id)
    except HTTPException:
        raise
    except IngestionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not re-index repository")
        raise HTTPException(status_code=502, detail=explain_database_error(error)) from error
    return {"message": "Repository queued for re-indexing", "repo_name": normalized_name}


@router.post("/repos/{repo_name}/cancel-indexing")
async def cancel_indexing(repo_name: str, current_user=Depends(get_current_user)):
    try:
        await assert_turso_schema()
        store = get_turso_store()
        repo = await owned_repo(store, current_user.id, repo_name)
        if repo["status"] not in ACTIVE_REPOSITORY_STATUSES:
            raise HTTPException(status_code=409, detail="This repository is not currently being indexed.")
        cancelled = await store.execute(
            "UPDATE ingestion_jobs SET status = 'cancelled', claimed_at = NULL, heartbeat_at = NULL, claim_token = NULL, "
            "last_error = 'Indexing stopped by the user.', updated_at = ? "
            "WHERE repo_id = ? AND status IN ('queued', 'processing') RETURNING id",
            [now(), repo["id"]],
        )
        if not cancelled.rows:
            raise HTTPException(status_code=409, detail="This repository finished indexing before it could be stopped.")
        await store.execute("DELETE FROM chunks WHERE repo_id = ?", [repo["id"]])
        await store.execute("DELETE FROM kt_cache WHERE repo_id = ?", [repo["id"]])
        await store.execute("DELETE FROM repo_files WHERE repo_id = ?", [repo["id"]])
        await store.execute("DELETE FROM repo_dependencies WHERE repo_id = ?", [repo["id"]])
        await store.execute("DELETE FROM repo_coverage WHERE repo_id = ?", [repo["id"]])
        await store.execute(
            "UPDATE repos SET status = 'cancelled', chunk_count = 0, error_message = 'Indexing stopped by you.', "
            "updated_at = ? WHERE id = ? AND user_id = ?",
            [now(), repo["id"], current_user.id],
        )
    except HTTPException:
        raise
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not cancel repository ingestion")
        raise HTTPException(status_code=502, detail=explain_database_error(error)) from error
    return {"message": "Indexing stopped", "repo_name": repo_name}
