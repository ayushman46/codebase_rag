"""Durable Turso-backed repository ingestion pipeline."""

import asyncio
import gc
import hashlib
import json
import os
import logging
import threading
import time
from array import array
from datetime import UTC, datetime, timedelta
from queue import Empty, Full, Queue
from uuid import uuid4

from config import settings
from database import Statement, assert_turso_schema, explain_database_error, get_turso_store
from ingest.chunker import STREAMING_FILE_THRESHOLD, chunk_file, iter_chunk_file
from ingest.cloner import (
    cleanup_repo,
    clone_repo_shallow,
    get_file_selection_report,
    normalize_github_url,
    repository_name,
    RepositoryValidationError,
)
from ingest.dependencies import build_manifest_and_dependency_manifest
from ingest.embedder import EmbeddingUnavailableError, embed_chunks
from ingest.memory import pressure_level, rss_mb, wait_for_memory_headroom
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


async def update_index_state(store, repo_id: str, *, phase: str, keyword_files: int | None = None,
                             keyword_chunks: int | None = None, semantic_progress: int | None = None,
                             embedding_status: str | None = None, searchable_at: str | None = None,
                             semantic_ready_at: str | None = None) -> None:
    """Publish durable, user-visible ingestion phase without changing repos.status."""
    assignments = ["phase = ?", "updated_at = ?"]
    update_args: list[object] = [phase, timestamp()]
    for field, value in (("keyword_files", keyword_files), ("keyword_chunks", keyword_chunks),
                         ("semantic_progress", semantic_progress), ("embedding_status", embedding_status),
                         ("searchable_at", searchable_at), ("semantic_ready_at", semantic_ready_at)):
        if value is not None:
            assignments.append(f"{field} = ?")
            update_args.append(value)
    update_args.append(repo_id)
    result = await store.execute(
        "UPDATE repo_index_state SET " + ", ".join(assignments) + " WHERE repo_id = ?", update_args
    )
    if result.rows_affected:
        return
    await store.execute(
        "INSERT OR IGNORE INTO repo_index_state (repo_id, phase, keyword_files, keyword_chunks, semantic_progress, "
        "embedding_status, searchable_at, semantic_ready_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [repo_id, phase, keyword_files or 0, keyword_chunks or 0, semantic_progress or 0,
         embedding_status or "pending", searchable_at, semantic_ready_at, timestamp()],
    )


async def publish_index_progress(store, repo_id: str, *, keyword_files: int | None = None,
                                 embedding_status: str | None = None, allow_ready: bool = False) -> tuple[int, int]:
    """Compute real semantic progress from persisted rows, never a fake timer."""
    totals = await store.fetch_one(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) AS embedded "
        "FROM chunks WHERE repo_id = ?", [repo_id]
    ) or {}
    total = int(totals.get("total") or 0)
    embedded = int(totals.get("embedded") or 0)
    progress = 100 if total == 0 else min(100, int((embedded / total) * 100))
    phase = "ready" if allow_ready and progress >= 100 and embedding_status != "degraded" else "searchable"
    await update_index_state(
        store, repo_id, phase=phase, keyword_files=keyword_files, keyword_chunks=total,
        semantic_progress=progress, embedding_status=embedding_status or ("complete" if progress >= 100 else "running"),
        searchable_at=timestamp() if phase in {"searchable", "ready"} else None,
        semantic_ready_at=timestamp() if phase == "ready" else None,
    )
    return total, progress


async def persist_ingestion_metrics(store, job_id: str | None, repo_id: str, metrics: dict) -> None:
    if not settings.ingestion_metrics_enabled:
        return
    if not job_id:
        return
    await store.execute(
        "INSERT INTO ingestion_metrics (job_id, repo_id, metrics_json, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(job_id) DO UPDATE SET metrics_json = excluded.metrics_json, updated_at = excluded.updated_at",
        [job_id, repo_id, json.dumps(metrics, separators=(",", ":")), timestamp()],
    )


async def _background_build_kt_cache(store, repo_id: str) -> None:
    """Build deterministic onboarding metadata after the source is searchable."""
    try:
        indexed_chunks = await store.fetch_all(
            "SELECT file_path, start_line, end_line, language, symbols FROM chunks "
            "WHERE repo_id = ? ORDER BY file_path, start_line LIMIT ?",
            [repo_id, settings.max_repository_chunks],
        )
        await build_kt_cache(store, repo_id, indexed_chunks)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Metadata is a convenience and must never turn a searchable index
        # into a failed job. The next re-index can rebuild it safely.
        logger.warning("Background repository metadata failed for %s", repo_id, exc_info=True)


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def iter_chunked_files(file_paths: list[str], repo_path: str):
    """Yield bounded concurrent chunking results without retaining a repo.

    Chunking is CPU and file-I/O work. The old pipeline awaited every file in
    sequence, leaving a worker idle while the next file was read. This helper
    overlaps a small number of ordinary files, but automatically falls back to
    one worker when any input is large enough to make concurrent full-file
    buffers unsafe on the 512 MB Render instance. Results may complete out of
    order; file paths and line ranges remain deterministic within each result.
    """
    if not file_paths:
        return
    configured_workers = max(1, int(settings.ingestion_chunk_workers))
    # Keep the scheduler's serial/streaming decision aligned with the chunker
    # threshold. A configured 8 MB serial threshold must not accidentally load
    # a 3 MB file into a complete chunk list when the chunker has already
    # switched to its bounded streaming implementation at 2 MB.
    large_threshold = max(1, min(int(settings.ingestion_large_file_serial_bytes), STREAMING_FILE_THRESHOLD))
    def is_large(path: str) -> bool:
        try:
            return os.path.getsize(path) >= large_threshold
        except OSError:
            return False

    has_large_file = any(is_large(path) for path in file_paths)
    worker_count = 1 if has_large_file else min(configured_workers, len(file_paths))

    if has_large_file:
        # A large source file is streamed through a tiny asynchronous queue.
        # ``run_blocking(list(...))`` would retain every chunk for a 50 MB
        # file while the database and embedding vectors are also resident.
        # The producer thread owns the generator and blocks when the queue is
        # full, keeping the worker's live source allocation bounded.
        async def stream_one(path: str):
            # A stdlib queue is safe to write from the producer thread. The
            # previous asyncio.Queue bridge could leave that thread blocked in
            # ``run_coroutine_threadsafe(...).result()`` when cancellation
            # happened during a memory guard or a client disconnect.
            queue: Queue[tuple[str, object]] = Queue(maxsize=2)
            sentinel = object()
            stopped = threading.Event()

            def put_item(item: tuple[str, object]) -> None:
                while not stopped.is_set():
                    try:
                        queue.put(item, timeout=0.1)
                        return
                    except Full:
                        continue

            def produce() -> None:
                error: BaseException | None = None
                try:
                    for chunk in iter_chunk_file(path, repo_path):
                        if stopped.is_set():
                            break
                        put_item(("chunk", chunk))
                except BaseException as caught:
                    error = caught
                finally:
                    put_item(("done", error or sentinel))

            producer = asyncio.create_task(run_blocking(produce))

            def get_item() -> tuple[str, object] | None:
                try:
                    return queue.get(timeout=0.25)
                except Empty:
                    return None

            try:
                while True:
                    item = await run_blocking(get_item)
                    if item is None:
                        continue
                    kind, value = item
                    if kind == "done":
                        if value is not sentinel:
                            raise value  # type: ignore[misc]
                        break
                    yield value
                await producer
            except BaseException:
                stopped.set()
                if not producer.done():
                    producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
                raise

        for path in file_paths:
            async for chunk in stream_one(path):
                yield path, [chunk]
        return

    async def chunk_one(path: str):
        return path, await run_blocking(chunk_file, path, repo_path)

    # Batch tasks rather than creating one asyncio task per repository file.
    # This bounds both task overhead and the number of full file buffers alive.
    for offset in range(0, len(file_paths), worker_count):
        tasks = [asyncio.create_task(chunk_one(path)) for path in file_paths[offset:offset + worker_count]]
        try:
            for task in asyncio.as_completed(tasks):
                yield await task
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise


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
    proposed_job_id = str(uuid4())
    await store.execute(
        "INSERT INTO ingestion_jobs (id, repo_id, user_id, github_url, status, attempts, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'queued', 0, ?, ?) "
        "ON CONFLICT(repo_id) DO UPDATE SET user_id = excluded.user_id, github_url = excluded.github_url, "
        "status = 'queued', attempts = 0, claimed_at = NULL, heartbeat_at = NULL, claim_token = NULL, "
        "finished_at = NULL, last_error = NULL, updated_at = excluded.updated_at",
        [proposed_job_id, repo_id, user_id, github_url, now, now],
    )
    # An upsert keeps the original row id. Re-read it after the write so two
    # concurrent submissions cannot create metadata pointing at a losing id.
    actual_job = await store.fetch_one("SELECT id FROM ingestion_jobs WHERE repo_id = ?", [repo_id])
    job_id = str((actual_job or {}).get("id") or proposed_job_id)
    # New submissions get the highest queue priority. The separate metadata
    # table keeps this additive for databases created before the performance
    # migration and lets the claim query remain atomic.
    await store.execute(
        "INSERT INTO ingestion_job_meta (job_id, priority, phase, progress, updated_at) VALUES (?, ?, 'queued', 0, ?) "
        "ON CONFLICT(job_id) DO UPDATE SET priority = excluded.priority, phase = 'queued', progress = 0, updated_at = excluded.updated_at",
        [job_id, 10, now],
    )
    await update_index_state(store, repo_id, phase="queued", semantic_progress=0, embedding_status="pending")


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
        now = timestamp()
        await store.execute(
            "UPDATE ingestion_jobs SET heartbeat_at = ?, updated_at = ? "
            "WHERE id = ? AND status = 'processing' AND claim_token = ?",
            [now, now, job_id, claim_token],
        )
        await store.execute(
            "UPDATE ingestion_job_meta SET phase = COALESCE((SELECT phase FROM repo_index_state s "
            "JOIN ingestion_jobs j ON j.repo_id = s.repo_id WHERE j.id = ?), phase), "
            "progress = COALESCE((SELECT semantic_progress FROM repo_index_state s "
            "JOIN ingestion_jobs j ON j.repo_id = s.repo_id WHERE j.id = ?), progress), updated_at = ? "
            "WHERE job_id = ?",
            [job_id, job_id, now, job_id],
        )


async def update_repo(store, repo_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = timestamp()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    await store.execute(f"UPDATE repos SET {assignments} WHERE id = ?", [*fields.values(), repo_id])


async def embed_repository_chunks(
    store,
    repo_id: str,
    chunks: list[dict],
    job_id: str | None = None,
    claim_token: str | None = None,
    *,
    progress_offset: int = 0,
    progress_total: int | None = None,
    metrics: dict | None = None,
    cache_enabled: bool = True,
):
    """Embed in cancellable batches and publish meaningful UI progress."""
    embedded_chunks: list[dict] = []
    batch_size = max(1, settings.embedding_batch_size)
    minimum_batch_size = min(batch_size, max(1, settings.embedding_min_batch_size))
    progress_interval = max(1, settings.embedding_progress_interval_batches)
    heartbeat_interval = max(1, settings.embedding_heartbeat_interval_batches)
    total_chunks = len(chunks)

    async def report_progress(completed: int):
        overall_completed = progress_offset + completed
        percent = int((overall_completed / progress_total) * 100) if progress_total else None
        progress_label = f" ({min(100, percent)}%)." if percent is not None else "."
        await update_repo(
            store, repo_id,
            error_message=(
                f"Indexing {overall_completed} code sections{progress_label} "
                "Large repositories can take a few minutes while embeddings are created."
            ),
        )

    # Hash only the passage content, not its path, so identical code in two
    # files can reuse one vector. The hash and cache lookup are bounded to the
    # current buffer; no repository-wide embedding map is retained in RAM.
    for chunk in chunks:
        chunk.setdefault("content_hash", hashlib.sha256(str(chunk.get("content") or "").encode("utf-8")).hexdigest())
    cache_reader = getattr(store, "get_embedding_cache", None) if cache_enabled else None
    cached = await cache_reader([chunk["content_hash"] for chunk in chunks]) if cache_reader else {}
    cache_hits = 0
    pending_by_hash: dict[str, dict] = {}
    for chunk in chunks:
        vector = cached.get(chunk["content_hash"])
        if vector is not None:
            chunk["embedding"] = array("f", vector)
            chunk["_embedding_cache_hit"] = True
            cache_hits += 1
        else:
            # One provider request per distinct passage in this bounded
            # buffer; duplicate files receive the same validated vector.
            pending_by_hash.setdefault(chunk["content_hash"], chunk)

    pending = list(pending_by_hash.values())

    if cache_hits:
        await report_progress(cache_hits)

    if progress_offset == 0:
        await report_progress(0)

    def record_embedding_request() -> None:
        """Record provider calls without coupling this helper to one job."""
        if metrics is not None:
            metrics["embedding_requests"] = int(metrics.get("embedding_requests", 0)) + 1

    offset = 0
    batch_number = 0
    while offset < len(pending):
        batch_number += 1
        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        await wait_for_memory_headroom()
        current_size = min(batch_size, len(pending) - offset)
        batch = pending[offset:offset + current_size]
        observed_batch_size = [current_size]
        await run_blocking(
            embed_chunks,
            batch,
            initial_batch_size=current_size,
            on_batch_size_change=lambda value: observed_batch_size.__setitem__(0, value),
            on_request=record_embedding_request,
        )
        offset += current_size
        completed = sum(1 for item in chunks if item.get("embedding") is not None)
        # Persist a provider payload reduction for the remainder of this
        # repository. A payload-limited endpoint should not reject the first
        # batch of every subsequent request.
        batch_size = max(minimum_batch_size, min(current_size, observed_batch_size[0]))
        # Progress is useful to the UI but does not need one remote write per
        # provider request. Cancellation remains checked for every batch.
        if batch_number % progress_interval == 0 or completed == total_chunks:
            await report_progress(completed)
        if job_id and claim_token and (
            batch_number % heartbeat_interval == 0 or completed == total_chunks
        ):
            await heartbeat_job(store, job_id, claim_token)
        if pressure_level() in {"warning", "critical"}:
            # Drop transient references before the next provider request. The
            # next call also re-checks the critical threshold and pauses if
            # Render is under pressure.
            gc.collect()
    # Fan vectors back out to duplicate passages in this bounded buffer.
    vectors_by_hash = {
        chunk["content_hash"]: chunk.get("embedding")
        for chunk in pending
        if chunk.get("embedding") is not None
    }
    for chunk in chunks:
        if chunk.get("embedding") is None and chunk["content_hash"] in vectors_by_hash:
            chunk["embedding"] = vectors_by_hash[chunk["content_hash"]]
    embedded_chunks = list(chunks)
    cache_writer = getattr(store, "save_embedding_cache", None) if cache_enabled else None
    if cache_writer:
        cache_records = {}
        for chunk in embedded_chunks:
            content_hash = chunk.get("content_hash")
            if content_hash and content_hash not in cached and chunk.get("embedding") is not None:
                cache_records[content_hash] = {
                    "content_hash": content_hash, "embedding": chunk["embedding"], "updated_at": timestamp(),
                }
        await cache_writer(list(cache_records.values()))
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
        "WHERE id = (SELECT queued.id FROM ingestion_jobs queued "
        "LEFT JOIN ingestion_job_meta meta ON meta.job_id = queued.id "
        "WHERE queued.status = 'queued' ORDER BY COALESCE(meta.priority, 20) ASC, queued.created_at ASC LIMIT 1) "
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


async def replace_changed_file_chunks(
    store,
    repo_id: str,
    changed_paths: set[str],
    removed_paths: set[str],
    preserve_id_prefix: str | None = None,
) -> None:
    """Remove stale chunks while preserving the current ingestion version.

    Re-indexes keep the old rows until the new rows have been completely
    chunked and embedded. New rows carry a job-scoped id prefix, so the final
    cleanup can remove only the old version. This keeps a failed re-index from
    destroying a previously searchable repository.
    """
    if changed_paths:
        placeholders = ", ".join("?" for _ in changed_paths)
        predicate = f"repo_id = ? AND file_path IN ({placeholders})"
        args: list[object] = [repo_id, *sorted(changed_paths)]
        if preserve_id_prefix:
            predicate += " AND id NOT LIKE ?"
            args.append(f"{preserve_id_prefix}%")
        await store.execute(f"DELETE FROM chunks WHERE {predicate}", args)
    if removed_paths:
        placeholders = ", ".join("?" for _ in removed_paths)
        await store.execute(
            f"DELETE FROM chunks WHERE repo_id = ? AND file_path IN ({placeholders})",
            [repo_id, *sorted(removed_paths)],
        )
        await store.execute(
            f"DELETE FROM repo_files WHERE repo_id = ? AND file_path IN ({placeholders})",
            [repo_id, *sorted(removed_paths)],
        )


async def persist_file_manifest(store, repo_id: str, manifest: dict[str, dict[str, int | str]]) -> None:
    statements: list[Statement] = []
    for file_path, metadata in manifest.items():
        statements.append(Statement(
            "INSERT INTO repo_files (repo_id, file_path, content_hash, byte_size, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(repo_id, file_path) DO UPDATE SET content_hash = excluded.content_hash, "
            "byte_size = excluded.byte_size, updated_at = excluded.updated_at",
            [repo_id, file_path, metadata["content_hash"], metadata["byte_size"], timestamp()],
        ))
        if len(statements) >= max(1, settings.chunk_insert_batch_size):
            await store.batch(statements)
            statements.clear()
    if statements:
        await store.batch(statements)


async def persist_dependency_manifest(store, repo_id: str, dependencies: list[dict]) -> None:
    """Replace the small resolved dependency graph after a successful index."""
    await store.execute("DELETE FROM repo_dependencies WHERE repo_id = ?", [repo_id])
    statements: list[Statement] = []
    for edge in dependencies:
        statements.append(Statement(
            "INSERT OR IGNORE INTO repo_dependencies (repo_id, source_file, target_file, import_name, line_number) "
            "VALUES (?, ?, ?, ?, ?)",
            [repo_id, edge["source_file"], edge["target_file"], edge["import_name"], edge["line_number"]],
        ))
        if len(statements) >= max(1, settings.chunk_insert_batch_size):
            await store.batch(statements)
            statements.clear()
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
    # Track the version that existed before this run. Cancellation of a
    # refresh must not erase a healthy searchable index; only the fresh,
    # job-scoped rows are disposable until the swap completes.
    preexisting_chunk_count = 0
    chunk_id_prefix: str | None = None
    replacement_swapped = False
    started_at = time.perf_counter()
    metrics = {
        "clone_ms": 0, "scan_ms": 0, "manifest_ms": 0, "chunk_ms": 0,
        "keyword_index_ms": 0, "embedding_ms": 0, "database_ms": 0,
        "dependency_ms": 0, "summarization_ms": 0, "total_ms": 0,
        "files_selected": 0, "files_excluded": 0, "bytes_selected": 0,
        "chunks_created": 0, "chunks_embedded": 0, "embedding_requests": 0,
        "embedding_cache_hits": 0, "embedding_failures": 0, "db_batches": 0,
        "peak_rss_mb": 0,
    }
    try:
        canonical_url = normalize_github_url(github_url)
        if repo_id is None:
            repo_id, _ = await ensure_repo_record(store, canonical_url, user_id)
        preexisting_chunk_count = await get_repo_chunk_count(store, repo_id)
        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        await heartbeat_job(store, job_id, claim_token)
        # Keep the previous ready index available while a fresh clone is being
        # prepared. Only stale file paths are replaced after the clone passes
        # validation, so a failed re-index does not erase working evidence.
        await update_repo(store, repo_id, status="cloning", error_message=None)
        await update_index_state(store, repo_id, phase="cloning", embedding_status="pending")
        clone_started = time.perf_counter()
        repo_path = await run_blocking(clone_repo_shallow, canonical_url)
        metrics["clone_ms"] = int((time.perf_counter() - clone_started) * 1000)

        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        await heartbeat_job(store, job_id, claim_token)
        await update_repo(store, repo_id, status="chunking")
        await update_index_state(store, repo_id, phase="scanning")
        scan_started = time.perf_counter()
        selection_report = await run_blocking(get_file_selection_report, repo_path)
        metrics["scan_ms"] = int((time.perf_counter() - scan_started) * 1000)
        metrics["files_selected"] = int(selection_report.get("eligible_files", 0))
        metrics["files_excluded"] = int(selection_report.get("excluded_files", 0))
        metrics["bytes_selected"] = int(selection_report.get("eligible_bytes", 0))
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
        await update_index_state(store, repo_id, phase="manifesting")
        manifest_started = time.perf_counter()
        previous_rows_task = store.fetch_all(
            "SELECT file_path, content_hash FROM repo_files WHERE repo_id = ?", [repo_id]
        )
        manifest_task = run_blocking(build_manifest_and_dependency_manifest, files, repo_path)
        (manifest, dependencies), previous_rows = await asyncio.gather(manifest_task, previous_rows_task)
        metrics["manifest_ms"] = int((time.perf_counter() - manifest_started) * 1000)
        metrics["dependency_ms"] = metrics["manifest_ms"]
        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        previous_manifest = {row["file_path"]: row["content_hash"] for row in previous_rows}
        changed_paths = {
            path for path, metadata in manifest.items()
            if previous_manifest.get(path) != metadata["content_hash"]
        }
        removed_paths = set(previous_manifest) - set(manifest)
        # Keep an existing searchable index intact until this run has produced
        # a complete replacement. New chunks are hidden from retrieval during
        # the re-index and the final cleanup preserves their job-scoped ids.
        existing_count = await get_repo_chunk_count(store, repo_id)
        defer_replacement = existing_count > 0
        # ``existing_count`` still contains stale rows for changed or removed
        # paths. Subtract them when enforcing the final chunk cap; otherwise a
        # refresh near the limit can be rejected even when the committed
        # post-refresh index would still fit.
        stale_paths = sorted(changed_paths | removed_paths)
        stale_chunk_count = 0
        if stale_paths:
            placeholders = ", ".join("?" for _ in stale_paths)
            stale_rows = await store.fetch_one(
                f"SELECT COUNT(*) AS count FROM chunks WHERE repo_id = ? AND file_path IN ({placeholders})",
                [repo_id, *stale_paths],
            )
            stale_chunk_count = int((stale_rows or {}).get("count", 0))
        retained_chunk_count = max(0, existing_count - stale_chunk_count)
        if not defer_replacement:
            await replace_changed_file_chunks(store, repo_id, changed_paths, removed_paths)

        changed_files = [
            file_path for file_path in files
            if os.path.relpath(file_path, repo_path).replace(os.sep, "/") in changed_paths
        ]
        # Chunk files incrementally, but aggregate a bounded number of chunks
        # before calling the embedding provider. Small files otherwise create
        # one under-filled request per file. The buffer is deliberately small
        # enough to keep peak memory proportional to tens of chunks rather than
        # the whole repository on the 512 MB Render instance.
        chunked_paths: set[str] = set()
        new_chunk_count = 0
        semantic_index_warning = None
        await update_repo(store, repo_id, status="chunking")
        chunk_started = time.perf_counter()
        keyword_published = False
        # Include a fresh run id even when a durable ingestion job is retried;
        # reusing only ``job_id`` would make cleanup match rows from the
        # previous attempt as well.
        chunk_id_prefix = f"{job_id or 'ingest'}-{uuid4()}-"

        async def persist_keyword_chunks(records: list[dict]) -> None:
            for offset in range(0, len(records), max(1, settings.chunk_insert_batch_size)):
                await raise_if_ingestion_cancelled(store, repo_id, claim_token)
                await heartbeat_job(store, job_id, claim_token)
                db_started = time.perf_counter()
                await store.insert_chunks(records[offset:offset + max(1, settings.chunk_insert_batch_size)])
                metrics["database_ms"] += int((time.perf_counter() - db_started) * 1000)
                metrics["db_batches"] += 1

        async def persist_embedding_updates(records: list[dict]) -> None:
            updater = getattr(store, "update_chunk_embeddings", None)
            if not updater:
                return
            for offset in range(0, len(records), max(1, settings.chunk_insert_batch_size)):
                await raise_if_ingestion_cancelled(store, repo_id, claim_token)
                db_started = time.perf_counter()
                await updater(records[offset:offset + max(1, settings.chunk_insert_batch_size)])
                metrics["database_ms"] += int((time.perf_counter() - db_started) * 1000)
                metrics["db_batches"] += 1

        chunk_buffer: list[dict] = []
        embedded_count = 0
        embeddings_disabled = False

        async def flush_chunk_buffer() -> None:
            nonlocal chunk_buffer, embedded_count, semantic_index_warning, embeddings_disabled, keyword_published
            if not chunk_buffer:
                return
            batch = chunk_buffer
            chunk_buffer = []
            records = [
                {
                    "id": f"{chunk_id_prefix}{uuid4()}", "repo_id": repo_id, "file_path": chunk["file_path"],
                    "start_line": chunk["start_line"], "end_line": chunk["end_line"],
                    "language": chunk["language"], "symbols": chunk.get("symbols", []),
                    "content": chunk["content"], "embedding": None,
                    "content_hash": hashlib.sha256(str(chunk.get("content") or "").encode("utf-8")).hexdigest(),
                }
                for chunk in batch
            ]
            keyword_started = time.perf_counter()
            await persist_keyword_chunks(records)
            await raise_if_ingestion_cancelled(store, repo_id, claim_token)
            metrics["keyword_index_ms"] += int((time.perf_counter() - keyword_started) * 1000)
            if not keyword_published:
                keyword_published = True
                if defer_replacement:
                    # Do not expose duplicate old/new rows while a replacement
                    # is being built. The old index remains stored and will be
                    # restored automatically if this run fails.
                    await update_repo(store, repo_id, status="chunking", chunk_count=existing_count, error_message="Refreshing the codebase. The previous index remains available after validation.")
                    await update_index_state(store, repo_id, phase="chunking", keyword_files=len(chunked_paths), keyword_chunks=existing_count, semantic_progress=0, embedding_status="running")
                else:
                    await update_repo(store, repo_id, status="ready", chunk_count=await get_repo_chunk_count(store, repo_id), error_message="Codebase ready to explore. Semantic indexing is continuing in the background.")
                    await update_index_state(store, repo_id, phase="searchable", keyword_files=len(chunked_paths), keyword_chunks=await get_repo_chunk_count(store, repo_id), semantic_progress=0, embedding_status="running", searchable_at=timestamp())
            if embeddings_disabled:
                embedded_chunks = records
            else:
                try:
                    embedding_started = time.perf_counter()
                    embedded_chunks = await embed_repository_chunks(
                        store,
                        repo_id,
                        records,
                        job_id,
                        claim_token,
                        progress_offset=embedded_count,
                        progress_total=max(retained_chunk_count + new_chunk_count, 1),
                        metrics=metrics,
                        cache_enabled=(
                            int(selection_report.get("eligible_bytes", 0))
                            <= settings.embedding_cache_max_repository_bytes
                        ),
                    )
                    metrics["embedding_ms"] += int((time.perf_counter() - embedding_started) * 1000)
                    metrics["chunks_embedded"] += sum(1 for chunk in embedded_chunks if chunk.get("embedding") is not None)
                    metrics["embedding_cache_hits"] += sum(1 for chunk in embedded_chunks if chunk.get("_embedding_cache_hit"))
                    await persist_embedding_updates(embedded_chunks)
                except EmbeddingUnavailableError as error:
                    # A provider outage is job-wide, not batch-local. Do not
                    # spend another five retries for every subsequent buffer.
                    embeddings_disabled = True
                    logger.warning("NVIDIA embeddings unavailable for %s; using keyword retrieval: %s", repo_id, error)
                    semantic_index_warning = (
                        "NVIDIA semantic embeddings are temporarily unavailable. "
                        "This repository is ready with keyword retrieval; re-index later to restore semantic search."
                    )
                    metrics["embedding_failures"] += 1
                    embedded_chunks = records
            _, semantic_progress = await publish_index_progress(
                store, repo_id, keyword_files=len(chunked_paths),
                embedding_status="degraded" if embeddings_disabled else None,
                allow_ready=False,
            )
            embedded_count += len(embedded_chunks)
            metrics["chunks_created"] += len(records)
            metrics["peak_rss_mb"] = max(metrics["peak_rss_mb"], round(rss_mb(), 1))
            del embedded_chunks
            del records
            del batch

        file_index = 0
        processed_paths: set[str] = set()
        pressure = "normal"
        async for file_path, file_chunks in iter_chunked_files(changed_files, repo_path):
            await raise_if_ingestion_cancelled(store, repo_id, claim_token)
            relative_path = os.path.relpath(file_path, repo_path).replace(os.sep, "/")
            if relative_path not in processed_paths:
                processed_paths.add(relative_path)
                file_index += 1
            if not file_chunks:
                continue
            chunked_paths.add(relative_path)
            new_chunk_count += len(file_chunks)
            if retained_chunk_count + new_chunk_count > settings.max_repository_chunks:
                raise ValueError("Repository exceeds the configured chunk limit. Use a smaller repository.")
            chunk_buffer.extend(file_chunks)
            configured_buffer = max(1, settings.embedding_chunk_buffer_size)
            # RSS probing is cheap on Linux (/proc) but spawning ``ps`` for
            # every streamed chunk is surprisingly expensive on macOS. A
            # bounded 64-chunk sampling interval still reacts well before the
            # next provider batch can add material memory pressure.
            if new_chunk_count == len(file_chunks) or new_chunk_count % 64 == 0:
                pressure = pressure_level()
            if pressure in {"elevated", "warning", "critical"}:
                configured_buffer = max(16, configured_buffer // 2)
            if len(chunk_buffer) >= configured_buffer:
                await flush_chunk_buffer()
            # Keep progress alive while a buffer is below the provider
            # threshold and no embedding request has completed yet.
            if file_index == len(changed_files) or file_index % max(1, settings.embedding_progress_interval_batches) == 0:
                await update_repo(
                    store,
                    repo_id,
                    error_message=f"Reading source files ({file_index} of {len(changed_files)} changed files).",
                )
            del file_chunks

        await flush_chunk_buffer()
        metrics["chunk_ms"] = int((time.perf_counter() - chunk_started) * 1000)

        chunking_failed_paths = sorted(changed_paths - chunked_paths)
        if chunking_failed_paths:
            reasons = dict(selection_report.get("excluded_reasons") or {})
            reasons["chunking_failed"] = int(reasons.get("chunking_failed", 0)) + len(chunking_failed_paths)
            selection_report["excluded_reasons"] = reasons
            selection_report["excluded_files"] = int(selection_report.get("excluded_files", 0)) + len(chunking_failed_paths)
            selection_report["excluded_paths"] = sorted({
                *selection_report.get("excluded_paths", []), *chunking_failed_paths,
            })
        if not chunked_paths and existing_count == 0:
            raise ValueError("No readable source code chunks were created from this repository.")

        if defer_replacement:
            # Replace only the previous version. The current run's rows are
            # identified by the job prefix and remain untouched.
            await replace_changed_file_chunks(
                store, repo_id, changed_paths, removed_paths, preserve_id_prefix=chunk_id_prefix,
            )
            replacement_swapped = True
        await persist_file_manifest(store, repo_id, manifest)
        await persist_dependency_manifest(store, repo_id, dependencies)
        indexed_count = await store.fetch_one(
            "SELECT COUNT(DISTINCT file_path) AS count FROM chunks WHERE repo_id = ?", [repo_id]
        )
        indexed_file_count = int((indexed_count or {}).get("count", 0))
        await persist_coverage(store, repo_id, selection_report, indexed_file_count)

        await raise_if_ingestion_cancelled(store, repo_id, claim_token)
        await heartbeat_job(store, job_id, claim_token)
        # Metadata is deliberately out of the critical path. Source search is
        # already durable; a restart can safely regenerate this cache later.
        asyncio.create_task(_background_build_kt_cache(store, repo_id))
        _, semantic_progress = await publish_index_progress(
            store, repo_id, keyword_files=len(chunked_paths),
            embedding_status="degraded" if embeddings_disabled else None,
            allow_ready=True,
        )
        if semantic_progress >= 100 and not embeddings_disabled:
            await update_repo(store, repo_id, status="ready", chunk_count=await get_repo_chunk_count(store, repo_id), error_message=None)
            await update_index_state(store, repo_id, phase="ready", semantic_progress=100, embedding_status="complete", semantic_ready_at=timestamp())
        else:
            await update_repo(store, repo_id, status="ready", chunk_count=await get_repo_chunk_count(store, repo_id), error_message=semantic_index_warning)
            await update_index_state(store, repo_id, phase="searchable", semantic_progress=semantic_progress, embedding_status="degraded" if embeddings_disabled else "running")
        metrics["total_ms"] = int((time.perf_counter() - started_at) * 1000)
        metrics["peak_rss_mb"] = max(metrics["peak_rss_mb"], round(rss_mb(), 1))
        await persist_ingestion_metrics(store, job_id, repo_id, metrics)
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
            if replacement_swapped:
                # A cancellation can race the final swap. At that point the
                # old changed rows are already gone, so deleting the fresh
                # rows would leave a partially indexed repository. Preserve
                # the committed rows and finish the durable state instead.
                chunk_count = await get_repo_chunk_count(store, repo_id)
                await update_repo(
                    store, repo_id, status="ready", chunk_count=chunk_count,
                    error_message="The refresh completed before cancellation was received.",
                )
                try:
                    await publish_index_progress(store, repo_id, allow_ready=True)
                except Exception:
                    logger.debug("Could not publish completed cancellation state", exc_info=True)
                return True
            if chunk_id_prefix:
                # Remove only this attempt's rows. A previous searchable
                # version, if present, remains available for questions.
                await store.execute(
                    "DELETE FROM chunks WHERE repo_id = ? AND id LIKE ?",
                    [repo_id, f"{chunk_id_prefix}%"],
                )
            if preexisting_chunk_count > 0:
                chunk_count = await get_repo_chunk_count(store, repo_id)
                await update_repo(
                    store, repo_id, status="ready", chunk_count=chunk_count,
                    error_message="Index refresh stopped. The previous index remains available.",
                )
                try:
                    await publish_index_progress(store, repo_id, allow_ready=True)
                except Exception:
                    logger.debug("Could not restore previous searchable state", exc_info=True)
            else:
                await store.execute("DELETE FROM kt_cache WHERE repo_id = ?", [repo_id])
                await store.execute("DELETE FROM repo_files WHERE repo_id = ?", [repo_id])
                await store.execute("DELETE FROM repo_dependencies WHERE repo_id = ?", [repo_id])
                await store.execute("DELETE FROM repo_coverage WHERE repo_id = ?", [repo_id])
                await update_repo(store, repo_id, status="cancelled", chunk_count=0, error_message="Indexing stopped by you.")
                try:
                    await update_index_state(store, repo_id, phase="cancelled", keyword_chunks=0, semantic_progress=0, embedding_status="degraded")
                except Exception:
                    logger.debug("Could not publish cancelled ingestion state", exc_info=True)
        return False
    except Exception as error:
        error_message = str(error).strip() if isinstance(error, (ValueError, RepositoryValidationError)) else explain_database_error(error)
        error_message = error_message or "Repository ingestion could not be completed."
        if error_message != "The database could not complete that request. Please try again shortly.":
            logger.warning("Repository ingestion stopped: %s", error_message)
        else:
            logger.exception("Repository ingestion failed")
        if repo_id:
            # A failed run must not leave half of a new index behind. The
            # job-scoped prefix also lets an existing index survive a failed
            # re-index because its rows never share this prefix.
            chunk_id_prefix = locals().get("chunk_id_prefix")
            if chunk_id_prefix:
                try:
                    await store.execute(
                        "DELETE FROM chunks WHERE repo_id = ? AND id LIKE ?",
                        [repo_id, f"{chunk_id_prefix}%"],
                    )
                except Exception:
                    logger.debug("Could not remove partial ingestion chunks", exc_info=True)
            await update_repo(store, repo_id, status="failed", error_message=error_message[:500])
            try:
                await update_index_state(store, repo_id, phase="failed", embedding_status="degraded")
                metrics["total_ms"] = int((time.perf_counter() - started_at) * 1000)
                metrics["peak_rss_mb"] = max(metrics["peak_rss_mb"], round(rss_mb(), 1))
                await persist_ingestion_metrics(store, job_id, repo_id, metrics)
            except Exception:
                logger.debug("Could not persist failed ingestion metrics", exc_info=True)
        return False
    finally:
        if repo_path:
            try:
                await run_blocking(cleanup_repo, repo_path)
            except Exception:
                logger.warning("Could not clean up temporary repository directory")
