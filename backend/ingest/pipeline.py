"""Durable Turso-backed repository ingestion pipeline."""

import asyncio
import hashlib
import json
import os
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from config import settings
from database import Statement, assert_turso_schema, explain_database_error, get_turso_store
from ingest.chunker import chunk_file
from ingest.cloner import (
    cleanup_repo,
    clone_repo_shallow,
    get_file_selection_report,
    normalize_github_url,
    repository_name,
    RepositoryValidationError,
)
from ingest.dependencies import build_dependency_manifest
from ingest.embedder import EmbeddingUnavailableError, embed_chunks
from ingest.summarizer import build_kt_cache
from quota import ensure_repository_usage_capacity

logger = logging.getLogger(__name__)
ACTIVE_REPOSITORY_STATUSES = {"queued", "cloning", "chunking", "embedding", "summarizing"}


class IngestionConflictError(RuntimeError):
    pass


class IngestionCancelledError(RuntimeError):
    pass


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def ensure_repo_record(store, github_url: str, user_id: str):
    """Create or queue a repository only for its authenticated owner.

    Existing chunks are intentionally retained until the worker has a fresh
    clone. The worker compares file hashes and replaces only changed paths,
    keeping a ready index available while a re-index waits in the queue.
    """
    canonical_url = normalize_github_url(github_url)
    repo_name = repository_name(canonical_url)
    existing = await store.fetch_one(
        "SELECT id, status FROM repos WHERE user_id = ? AND repo_name = ?", [user_id, repo_name]
    )
    now = timestamp()
    if existing:
        if existing["status"] in ACTIVE_REPOSITORY_STATUSES:
            raise IngestionConflictError("Repository ingestion is already in progress.")
        repo_id = existing["id"]
        await store.execute(
            "UPDATE repos SET repo_name = ?, github_url = ?, status = 'queued', "
            "error_message = NULL, updated_at = ? WHERE id = ? AND user_id = ?",
            [repo_name, canonical_url, now, repo_id, user_id],
        )
    else:
        repo_id = str(uuid4())
        await store.execute(
            "INSERT INTO repos (id, user_id, repo_name, github_url, status, chunk_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)",
            [repo_id, user_id, repo_name, canonical_url, now, now],
        )
    return repo_id, repo_name


async def queue_existing_repo(store, repo: dict, user_id: str) -> tuple[str, str]:
    """Queue a known repository without rebuilding its user-facing name.

    Repository names are editable labels. Re-indexing must therefore use the
    existing row id and label rather than calling ``ensure_repo_record`` with
    the GitHub URL (which derives the original upstream name and can create a
    duplicate row after a rename).
    """
    repo_id = str(repo["id"])
    repo_name = str(repo["repo_name"])
    canonical_url = normalize_github_url(str(repo["github_url"]))
    now = timestamp()
    await store.execute(
        "UPDATE repos SET status = 'queued', error_message = NULL, updated_at = ? "
        "WHERE id = ? AND user_id = ?",
        [now, repo_id, user_id],
    )
    await enqueue_ingestion_job(store, canonical_url, user_id, repo_id)
    return repo_id, repo_name


async def enforce_ingestion_capacity(store, user_id: str, github_url: str) -> None:
    repo_name = repository_name(github_url)
    existing = await store.fetch_one(
        "SELECT id FROM repos WHERE user_id = ? AND repo_name = ?", [user_id, repo_name]
    )
    if not existing:
        repository_count = await store.fetch_one("SELECT COUNT(*) AS count FROM repos WHERE user_id = ?", [user_id])
        if int(repository_count["count"]) >= settings.max_repositories_per_user:
            raise IngestionConflictError(
                "Repository limit reached for this workspace. Delete an unused repository before adding another."
            )

    active_count = await store.fetch_one(
        "SELECT COUNT(*) AS count FROM ingestion_jobs WHERE user_id = ? AND status IN ('queued', 'processing')",
        [user_id],
    )
    if int(active_count["count"]) >= settings.max_active_ingestion_jobs_per_user:
        raise IngestionConflictError(
            "An indexing job is already running for this workspace. Wait for it to finish or stop it first."
        )


async def enqueue_ingestion_job(store, github_url: str, user_id: str, repo_id: str):
    """Persist durable queue work before returning an API response."""
    now = timestamp()
    await store.execute(
        "INSERT INTO ingestion_jobs (id, repo_id, user_id, github_url, status, attempts, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'queued', 0, ?, ?) "
        "ON CONFLICT(repo_id) DO UPDATE SET user_id = excluded.user_id, github_url = excluded.github_url, "
        "status = 'queued', attempts = 0, claimed_at = NULL, heartbeat_at = NULL, claim_token = NULL, "
        "finished_at = NULL, last_error = NULL, updated_at = excluded.updated_at",
        [str(uuid4()), repo_id, user_id, github_url, now, now],
    )


async def job_is_active(store, repo_id: str, claim_token: str | None = None) -> bool:
    job = await store.fetch_one("SELECT status, claim_token FROM ingestion_jobs WHERE repo_id = ?", [repo_id])
    return bool(job and job["status"] == "processing" and (claim_token is None or job["claim_token"] == claim_token))


async def raise_if_ingestion_cancelled(store, repo_id: str, claim_token: str | None = None):
    if claim_token is None:
        job = await store.fetch_one("SELECT status FROM ingestion_jobs WHERE repo_id = ?", [repo_id])
        if job and job["status"] == "cancelled":
            raise IngestionCancelledError("Indexing was stopped by the user.")
        return
    if not await job_is_active(store, repo_id, claim_token):
        raise IngestionCancelledError("Indexing was stopped by the user.")


async def heartbeat_job(store, job_id: str | None, claim_token: str | None) -> None:
    if job_id and claim_token:
        await store.execute(
            "UPDATE ingestion_jobs SET heartbeat_at = ?, updated_at = ? "
            "WHERE id = ? AND status = 'processing' AND claim_token = ?",
            [timestamp(), timestamp(), job_id, claim_token],
        )


async def update_repo(store, repo_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = timestamp()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    await store.execute(f"UPDATE repos SET {assignments} WHERE id = ?", [*fields.values(), repo_id])


async def embed_repository_chunks(store, repo_id: str, chunks: list[dict], job_id: str | None = None, claim_token: str | None = None):
    """Embed in cancellable batches and publish meaningful UI progress."""
    embedded_chunks: list[dict] = []
    batch_size = max(1, settings.embedding_batch_size)
    minimum_batch_size = min(batch_size, max(1, settings.embedding_min_batch_size))
    progress_interval = max(1, settings.embedding_progress_interval_batches)
    heartbeat_interval = max(1, settings.embedding_heartbeat_interval_batches)
    total_chunks = len(chunks)

    async def report_progress(completed: int):
        percent = int((completed / total_chunks) * 100) if total_chunks else 100
        await update_repo(
            store, repo_id,
            error_message=(
                f"Indexing {completed} of {total_chunks} code sections ({percent}%). "
                "Large repositories can take a few minutes while embeddings are created."
            ),
        )

    await report_progress(0)
    offset = 0
    batch_number = 0
    while offset < len(chunks):
        batch_number += 1
        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        current_size = min(batch_size, len(chunks) - offset)
        batch = chunks[offset:offset + current_size]
        observed_batch_size = [current_size]
        embedded_chunks.extend(await run_blocking(
            embed_chunks,
            batch,
            initial_batch_size=current_size,
            on_batch_size_change=lambda value: observed_batch_size.__setitem__(0, value),
        ))
        completed = len(embedded_chunks)
        # Persist a provider payload reduction for the remainder of this
        # repository. A payload-limited endpoint should not reject the first
        # batch of every subsequent request.
        batch_size = max(minimum_batch_size, min(current_size, observed_batch_size[0]))
        offset += current_size
        # Progress is useful to the UI but does not need one remote write per
        # provider request. Cancellation remains checked for every batch.
        if batch_number % progress_interval == 0 or completed == total_chunks:
            await report_progress(completed)
        if job_id and claim_token and (
            batch_number % heartbeat_interval == 0 or completed == total_chunks
        ):
            await heartbeat_job(store, job_id, claim_token)
    return embedded_chunks


def _lease_is_stale(lease_time: str | None, threshold: datetime) -> bool:
    if not lease_time:
        return True
    try:
        return datetime.fromisoformat(lease_time.replace("Z", "+00:00")) < threshold
    except ValueError:
        return True


async def requeue_stale_jobs(store):
    threshold = datetime.now(UTC) - timedelta(seconds=settings.ingestion_job_timeout_seconds)
    jobs = await store.fetch_all(
        "SELECT id, repo_id, attempts, claim_token, claimed_at, heartbeat_at FROM ingestion_jobs WHERE status = 'processing'"
    )
    for job in jobs:
        if not _lease_is_stale(job.get("heartbeat_at") or job.get("claimed_at"), threshold):
            continue
        attempts = int(job.get("attempts") or 0)
        failed = attempts >= settings.max_ingestion_attempts
        error = (
            "Ingestion timed out repeatedly. Use a smaller repository and submit it again."
            if failed else "Previous worker lease expired; retrying."
        )
        now = timestamp()
        result = await store.execute(
            "UPDATE ingestion_jobs SET status = ?, claimed_at = NULL, heartbeat_at = NULL, claim_token = NULL, "
            "finished_at = ?, last_error = ?, updated_at = ? "
            "WHERE id = ? AND status = 'processing' AND COALESCE(claim_token, '') = COALESCE(?, '') "
            "AND COALESCE(heartbeat_at, claimed_at) = ? RETURNING id",
            ["failed" if failed else "queued", now if failed else None, error, now, job["id"], job.get("claim_token"), job.get("heartbeat_at") or job.get("claimed_at")],
        )
        if result.rows_affected and failed:
            await update_repo(store, job["repo_id"], status="failed", error_message=error)


async def claim_next_ingestion_job(store):
    """Claim one queue row atomically; overlapping workers cannot claim it twice."""
    await requeue_stale_jobs(store)
    claim_token = str(uuid4())
    now = timestamp()
    result = await store.execute(
        "UPDATE ingestion_jobs SET status = 'processing', claimed_at = ?, heartbeat_at = ?, claim_token = ?, "
        "attempts = attempts + 1, last_error = NULL, updated_at = ? "
        "WHERE id = (SELECT id FROM ingestion_jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1) "
        "AND status = 'queued' "
        "RETURNING id, repo_id, user_id, github_url, attempts",
        [now, now, claim_token, now],
    )
    if not result.rows:
        return None
    # TursoStore normalizes every row into a plain dictionary. Keeping that
    # representation avoids a worker crash immediately after an atomic claim.
    job = dict(result.rows[0])
    job["claim_token"] = claim_token
    return job


async def get_repo_chunk_count(store, repo_id: str) -> int:
    result = await store.fetch_one("SELECT COUNT(*) AS count FROM chunks WHERE repo_id = ?", [repo_id])
    return int(result["count"]) if result else 0


async def get_repo_error_message(store, repo_id: str) -> str | None:
    result = await store.fetch_one("SELECT error_message FROM repos WHERE id = ?", [repo_id])
    return result.get("error_message") if result else None


async def persist_coverage(store, repo_id: str, report: dict, indexed_files: int = 0) -> None:
    """Persist bounded, explainable ingestion coverage for the repository UI."""
    await store.execute(
        "INSERT INTO repo_coverage (repo_id, total_seen_files, eligible_files, indexed_files, "
        "excluded_files, excluded_bytes, excluded_reasons, excluded_paths, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repo_id) DO UPDATE SET total_seen_files = excluded.total_seen_files, "
        "eligible_files = excluded.eligible_files, indexed_files = excluded.indexed_files, "
        "excluded_files = excluded.excluded_files, excluded_bytes = excluded.excluded_bytes, "
        "excluded_reasons = excluded.excluded_reasons, excluded_paths = excluded.excluded_paths, updated_at = excluded.updated_at",
        [
            repo_id,
            int(report.get("total_seen_files", 0)),
            int(report.get("eligible_files", 0)),
            int(indexed_files),
            int(report.get("excluded_files", 0)),
            int(report.get("excluded_bytes", 0)),
            json.dumps(report.get("excluded_reasons") or {}),
            json.dumps(report.get("excluded_paths") or []),
            timestamp(),
        ],
    )


def build_file_manifest(files: list[str], repo_path: str) -> dict[str, dict[str, int | str]]:
    """Hash selected source files for deterministic incremental re-indexing."""
    manifest: dict[str, dict[str, int | str]] = {}
    for file_path in files:
        digest = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        relative = os.path.relpath(file_path, repo_path).replace(os.sep, "/")
        manifest[relative] = {"content_hash": digest.hexdigest(), "byte_size": os.path.getsize(file_path)}
    return manifest


async def replace_changed_file_chunks(store, repo_id: str, changed_paths: set[str], removed_paths: set[str]) -> None:
    """Remove only stale chunks before new versions are inserted."""
    stale_paths = sorted(changed_paths | removed_paths)
    if not stale_paths:
        return
    placeholders = ", ".join("?" for _ in stale_paths)
    await store.execute(
        f"DELETE FROM chunks WHERE repo_id = ? AND file_path IN ({placeholders})",
        [repo_id, *stale_paths],
    )
    if removed_paths:
        placeholders = ", ".join("?" for _ in removed_paths)
        await store.execute(
            f"DELETE FROM repo_files WHERE repo_id = ? AND file_path IN ({placeholders})",
            [repo_id, *sorted(removed_paths)],
        )


async def persist_file_manifest(store, repo_id: str, manifest: dict[str, dict[str, int | str]]) -> None:
    statements = []
    for file_path, metadata in manifest.items():
        statements.append(Statement(
            "INSERT INTO repo_files (repo_id, file_path, content_hash, byte_size, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(repo_id, file_path) DO UPDATE SET content_hash = excluded.content_hash, "
            "byte_size = excluded.byte_size, updated_at = excluded.updated_at",
            [repo_id, file_path, metadata["content_hash"], metadata["byte_size"], timestamp()],
        ))
    if statements:
        await store.batch(statements)


async def persist_dependency_manifest(store, repo_id: str, dependencies: list[dict]) -> None:
    """Replace the small resolved dependency graph after a successful index."""
    await store.execute("DELETE FROM repo_dependencies WHERE repo_id = ?", [repo_id])
    statements = [
        Statement(
            "INSERT OR IGNORE INTO repo_dependencies (repo_id, source_file, target_file, import_name, line_number) "
            "VALUES (?, ?, ?, ?, ?)",
            [repo_id, edge["source_file"], edge["target_file"], edge["import_name"], edge["line_number"]],
        )
        for edge in dependencies
    ]
    if statements:
        await store.batch(statements)


async def finalize_successful_job(store, job: dict) -> bool:
    """Publish ready only if the same worker still owns the queue lease.

    Pre-fetch the repo metadata before the atomic job UPDATE so the repo
    status can be written immediately afterward, closing the timing window
    where a crash between the two writes would leave the repo stuck.
    """
    now = timestamp()
    repo_id = job["repo_id"]
    # Fetch final repo values before marking the job completed. If either
    # query fails, the job stays in 'processing' and the stale-job reaper
    # will eventually retry it — the safer outcome.
    chunk_count = await get_repo_chunk_count(store, repo_id)
    error_message = await get_repo_error_message(store, repo_id)
    completed = await store.execute(
        "UPDATE ingestion_jobs SET status = 'completed', finished_at = ?, claimed_at = NULL, heartbeat_at = NULL, "
        "claim_token = NULL, updated_at = ? WHERE id = ? AND status = 'processing' AND claim_token = ? RETURNING id",
        [now, now, job["id"], job["claim_token"]],
    )
    if not completed.rows:
        return False
    await update_repo(store, repo_id, status="ready", chunk_count=chunk_count, error_message=error_message)
    return True


async def mark_job_failed(store, job: dict) -> None:
    now = timestamp()
    await store.execute(
        "UPDATE ingestion_jobs SET status = 'failed', finished_at = ?, claimed_at = NULL, heartbeat_at = NULL, "
        "claim_token = NULL, updated_at = ? WHERE id = ? AND status = 'processing' AND claim_token = ?",
        [now, now, job["id"], job["claim_token"]],
    )


async def recover_stuck_repos(store) -> int:
    """Fix repositories stuck in active statuses whose ingestion jobs already completed.

    This is a safety net for the rare case where a crash leaves the repo
    status in an intermediate state (e.g. 'embedding') while the job row
    was already marked 'completed'. Returns the number of recovered repos.
    """
    stuck = await store.fetch_all(
        "SELECT r.id, r.status, j.status AS job_status "
        "FROM repos r JOIN ingestion_jobs j ON j.repo_id = r.id "
        "WHERE r.status IN (?, ?, ?, ?, ?) AND j.status = 'completed'",
        list(ACTIVE_REPOSITORY_STATUSES),
    )
    recovered = 0
    for repo in stuck:
        repo_id = repo["id"]
        chunk_count = await get_repo_chunk_count(store, repo_id)
        error_message = await get_repo_error_message(store, repo_id)
        await update_repo(store, repo_id, status="ready", chunk_count=chunk_count, error_message=error_message)
        recovered += 1
        logger.info("Recovered stuck repository %s from status '%s' to 'ready'", repo_id, repo["status"])
    return recovered


async def process_one_queued_ingestion(store):
    job = await claim_next_ingestion_job(store)
    if not job:
        return {"processed": False}
    succeeded = await run_ingestion_for_repo(
        store, job["github_url"], job["user_id"], job["repo_id"], job_id=job["id"], claim_token=job["claim_token"]
    )
    if succeeded:
        succeeded = await finalize_successful_job(store, job)
    else:
        await mark_job_failed(store, job)
    return {"processed": True, "repo_id": job["repo_id"], "succeeded": succeeded}


async def run_ingestion(github_url: str, user_id: str):
    await assert_turso_schema()
    await run_ingestion_for_repo(get_turso_store(), github_url, user_id)


async def run_ingestion_for_repo(
    store, github_url: str, user_id: str, repo_id: str | None = None,
    job_id: str | None = None, claim_token: str | None = None,
):
    repo_path: str | None = None
    try:
        canonical_url = normalize_github_url(github_url)
        if repo_id is None:
            repo_id, _ = await ensure_repo_record(store, canonical_url, user_id)
        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        await heartbeat_job(store, job_id, claim_token)
        # Keep the previous ready index available while a fresh clone is being
        # prepared. Only stale file paths are replaced after the clone passes
        # validation, so a failed re-index does not erase working evidence.
        await update_repo(store, repo_id, status="cloning", error_message=None)
        repo_path = await run_blocking(clone_repo_shallow, canonical_url)

        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        await heartbeat_job(store, job_id, claim_token)
        await update_repo(store, repo_id, status="chunking")
        selection_report = await run_blocking(get_file_selection_report, repo_path)
        await persist_coverage(store, repo_id, selection_report)
        files = selection_report["files"]
        if not files:
            raise ValueError("No supported text source files were found in this repository.")

        # Enforce the account quota after the clone has been inspected but
        # before replacing any existing chunks. A re-index excludes the old
        # version of this repository from the projection calculation.
        await ensure_repository_usage_capacity(
            store,
            user_id,
            selection_report.get("eligible_bytes", 0),
            replacing_repo_id=repo_id,
        )

        # These are independent reads of the immutable shallow clone. Run the
        # CPU/file work together and overlap it with the metadata lookup so a
        # large repository does not pay three full serial passes before
        # chunking starts.
        manifest_task = run_blocking(build_file_manifest, files, repo_path)
        dependency_task = run_blocking(build_dependency_manifest, files, repo_path)
        previous_rows_task = store.fetch_all(
            "SELECT file_path, content_hash FROM repo_files WHERE repo_id = ?", [repo_id]
        )
        manifest, dependencies, previous_rows = await asyncio.gather(
            manifest_task, dependency_task, previous_rows_task,
        )
        previous_manifest = {row["file_path"]: row["content_hash"] for row in previous_rows}
        changed_paths = {
            path for path, metadata in manifest.items()
            if previous_manifest.get(path) != metadata["content_hash"]
        }
        removed_paths = set(previous_manifest) - set(manifest)
        await replace_changed_file_chunks(store, repo_id, changed_paths, removed_paths)

        def collect_chunks():
            chunks = []
            for file_path in files:
                relative = os.path.relpath(file_path, repo_path).replace(os.sep, "/")
                if relative not in changed_paths:
                    continue
                chunks.extend(chunk_file(file_path, repo_path))
                if len(chunks) > settings.max_repository_chunks:
                    raise ValueError("Repository exceeds the configured chunk limit. Use a smaller repository.")
            return chunks

        all_chunks = await run_blocking(collect_chunks)
        chunked_paths = {chunk["file_path"] for chunk in all_chunks}
        chunking_failed_paths = sorted(changed_paths - chunked_paths)
        if chunking_failed_paths:
            reasons = dict(selection_report.get("excluded_reasons") or {})
            reasons["chunking_failed"] = int(reasons.get("chunking_failed", 0)) + len(chunking_failed_paths)
            selection_report["excluded_reasons"] = reasons
            selection_report["excluded_files"] = int(selection_report.get("excluded_files", 0)) + len(chunking_failed_paths)
            selection_report["excluded_paths"] = sorted({
                *selection_report.get("excluded_paths", []), *chunking_failed_paths,
            })
        existing_count = await get_repo_chunk_count(store, repo_id)
        if existing_count + len(all_chunks) > settings.max_repository_chunks:
            raise ValueError("Repository exceeds the configured chunk limit. Use a smaller repository.")
        if not all_chunks and existing_count == 0:
            raise ValueError("No readable source code chunks were created from this repository.")

        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        await heartbeat_job(store, job_id, claim_token)
        await update_repo(store, repo_id, status="embedding")
        semantic_index_warning = None
        embedded_chunks = []
        if all_chunks:
            try:
                embedded_chunks = await embed_repository_chunks(store, repo_id, all_chunks, job_id, claim_token)
            except EmbeddingUnavailableError as error:
                logger.warning("NVIDIA embeddings unavailable for %s; using keyword retrieval: %s", repo_id, error)
                semantic_index_warning = (
                    "NVIDIA semantic embeddings are temporarily unavailable. "
                    "This repository is ready with keyword retrieval; re-index later to restore semantic search."
                )
                embedded_chunks = [{**chunk, "embedding": None} for chunk in all_chunks]

        for offset in range(0, len(embedded_chunks), 100):
            await raise_if_ingestion_cancelled(store, repo_id, claim_token)
            await heartbeat_job(store, job_id, claim_token)
            records = [
                {
                    "id": str(uuid4()), "repo_id": repo_id, "file_path": chunk["file_path"],
                    "start_line": chunk["start_line"], "end_line": chunk["end_line"],
                    "language": chunk["language"], "symbols": chunk.get("symbols", []),
                    "content": chunk["content"], "embedding": chunk.get("embedding"),
                }
                for chunk in embedded_chunks[offset:offset + 100]
            ]
            await store.insert_chunks(records)

        await persist_file_manifest(store, repo_id, manifest)
        await persist_dependency_manifest(store, repo_id, dependencies)
        indexed_count = await store.fetch_one(
            "SELECT COUNT(DISTINCT file_path) AS count FROM chunks WHERE repo_id = ?", [repo_id]
        )
        indexed_file_count = int((indexed_count or {}).get("count", 0))
        await persist_coverage(store, repo_id, selection_report, indexed_file_count)

        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        await heartbeat_job(store, job_id, claim_token)
        await update_repo(store, repo_id, status="summarizing")
        indexed_chunks = await store.fetch_all(
            "SELECT file_path, start_line, end_line, language, symbols, content FROM chunks "
            "WHERE repo_id = ? ORDER BY file_path, start_line", [repo_id]
        )
        await build_kt_cache(store, repo_id, indexed_chunks)
        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        if job_id and claim_token:
            # Progress is temporarily stored in the existing message column
            # for clients that already poll it. Clear the completed-progress
            # text before the worker publishes ``ready`` so it is never shown
            # as a stale error after a successful index.
            await update_repo(store, repo_id, error_message=semantic_index_warning)
            return True
        await update_repo(store, repo_id, status="ready", chunk_count=await get_repo_chunk_count(store, repo_id), error_message=semantic_index_warning)
        return True
    except IngestionCancelledError:
        logger.info("Repository ingestion cancelled for %s", repo_id)
        if repo_id:
            await store.execute("DELETE FROM chunks WHERE repo_id = ?", [repo_id])
            await store.execute("DELETE FROM kt_cache WHERE repo_id = ?", [repo_id])
            await store.execute("DELETE FROM repo_files WHERE repo_id = ?", [repo_id])
            await store.execute("DELETE FROM repo_dependencies WHERE repo_id = ?", [repo_id])
            await store.execute("DELETE FROM repo_coverage WHERE repo_id = ?", [repo_id])
            await update_repo(store, repo_id, status="cancelled", chunk_count=0, error_message="Indexing stopped by you.")
        return False
    except Exception as error:
        error_message = str(error).strip() if isinstance(error, (ValueError, RepositoryValidationError)) else explain_database_error(error)
        error_message = error_message or "Repository ingestion could not be completed."
        if error_message != "The database could not complete that request. Please try again shortly.":
            logger.warning("Repository ingestion stopped: %s", error_message)
        else:
            logger.exception("Repository ingestion failed")
        if repo_id:
            await update_repo(store, repo_id, status="failed", error_message=error_message[:500])
        return False
    finally:
        if repo_path:
            try:
                await run_blocking(cleanup_repo, repo_path)
            except Exception:
                logger.warning("Could not clean up temporary repository directory")
