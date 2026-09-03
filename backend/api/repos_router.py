"""Owned repository management backed by Turso."""

import logging
import posixpath
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth import get_current_user
from database import DatabaseConfigurationError, assert_turso_schema, explain_database_error, get_turso_store
from ingest.pipeline import ACTIVE_REPOSITORY_STATUSES, IngestionConflictError, enforce_ingestion_capacity, ensure_repo_record, queue_existing_repo
from retrieval.retriever import dependent_file_chunks

logger = logging.getLogger(__name__)
router = APIRouter()


class RenameRepositoryRequest(BaseModel):
    repo_name: str = Field(min_length=1, max_length=200)


def now() -> str:
    return datetime.now(UTC).isoformat()


def _normalise_impact_path(file_path: str) -> str:
    """Validate one relative source path before it reaches a SQL LIKE clause."""
    candidate = file_path.strip().replace("\\", "/")
    if not candidate or len(candidate) > 500 or "\x00" in candidate:
        raise HTTPException(status_code=422, detail="Enter a relative source file path.")
    if candidate.startswith("/"):
        raise HTTPException(status_code=422, detail="The impact path must be relative to the repository.")
    normalised = posixpath.normpath(candidate)
    parts = normalised.split("/")
    if normalised in {"", "."} or normalised.startswith("../") or ".." in parts:
        raise HTTPException(status_code=422, detail="The impact path must stay inside the repository.")
    return normalised


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


@router.get("/repos/statuses")
async def list_repo_statuses(current_user=Depends(get_current_user)):
    """Return all repository statuses in one tenant-scoped query."""
    try:
        await assert_turso_schema()
        return await get_turso_store().fetch_all(
            "SELECT r.repo_name, r.status, r.chunk_count, r.error_message, "
            "COALESCE(c.total_seen_files, 0) AS total_seen_files, COALESCE(c.eligible_files, 0) AS eligible_files, "
            "COALESCE(c.indexed_files, 0) AS indexed_files, COALESCE(c.excluded_files, 0) AS excluded_files, "
            "COALESCE(c.excluded_bytes, 0) AS excluded_bytes, COALESCE(c.excluded_reasons, '{}') AS excluded_reasons, "
            "COALESCE(c.excluded_paths, '[]') AS excluded_paths "
            "FROM repos r LEFT JOIN repo_coverage c ON c.repo_id = r.id "
            "WHERE r.user_id = ? "
            "ORDER BY r.created_at DESC",
            [current_user.id],
        )
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not list repository statuses")
        raise HTTPException(status_code=502, detail=explain_database_error(error)) from error


@router.get("/repos/{repo_name}/impact")
async def repository_impact(
    repo_name: str,
    file_path: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
):
    """Show the local files that would be affected by changing one source file.

    The graph is deliberately conservative: only imports resolved to another
    indexed file are returned. External packages and unresolved aliases are
    omitted instead of being presented as speculative breakage.
    """
    target = _normalise_impact_path(file_path)
    try:
        await assert_turso_schema()
        store = get_turso_store()
        repo = await owned_repo(store, current_user.id, repo_name)
        escaped = _escape_like(target.lower())
        target_rows = await store.fetch_all(
            "SELECT DISTINCT file_path FROM chunks WHERE repo_id = ? AND (lower(file_path) = ? "
            "OR (lower(file_path) LIKE ? ESCAPE '\\' AND instr(lower(file_path), '/') > 0)) "
            "ORDER BY file_path LIMIT ?",
            [repo["id"], target.lower(), f"%/{escaped}", limit],
        )
        target_paths = [str(row["file_path"]) for row in target_rows]
        if not target_paths:
            raise HTTPException(status_code=404, detail="That source file is not present in the indexed repository.")

        dependency_conditions = []
        dependency_args = [repo["id"]]
        for path in target_paths:
            escaped_path = _escape_like(path)
            dependency_conditions.append("(d.target_file = ? OR d.target_file LIKE ? ESCAPE '\\')")
            dependency_args.extend([path, f"%/{escaped_path}"])
        edges = await store.fetch_all(
            "SELECT d.source_file, d.target_file, d.import_name, d.line_number "
            "FROM repo_dependencies d "
            f"WHERE d.repo_id = ? AND ({' OR '.join(dependency_conditions)}) "
            "ORDER BY d.source_file, d.line_number, d.target_file LIMIT ?",
            [*dependency_args, limit * 4],
        )
        dependents = await dependent_file_chunks(store, repo["id"], target_paths, limit=limit)
        dependent_paths = sorted({str(chunk["file_path"]) for chunk in dependents})
        return {
            "repository": repo_name,
            "target_files": target_paths,
            "dependent_files": dependent_paths,
            "edges": edges,
            "summary": (
                f"{len(dependent_paths)} indexed file(s) import the selected file."
                if dependent_paths else
                "No resolved indexed dependents were found. External or dynamic imports are not included."
            ),
        }
    except HTTPException:
        raise
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not analyze repository impact")
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
        _repo_id, normalized_name = await queue_existing_repo(store, existing, current_user.id)
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
