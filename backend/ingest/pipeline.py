import asyncio
import logging
from datetime import UTC, datetime, timedelta

from database import assert_supabase_schema, explain_supabase_api_error, supabase
from ingest.chunker import chunk_file
from ingest.cloner import cleanup_repo, clone_repo_shallow, normalize_github_url, repository_name
from ingest.cloner import get_files_to_process
from ingest.embedder import embed_chunks
from ingest.summarizer import build_kt_cache
from config import settings

logger = logging.getLogger(__name__)


class IngestionConflictError(RuntimeError):
    pass


class IngestionCancelledError(RuntimeError):
    pass


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def run_query(query):
    return await asyncio.to_thread(query.execute)


async def ensure_repo_record(supabase_client, github_url: str, user_id: str):
    canonical_url = normalize_github_url(github_url)
    repo_name = repository_name(canonical_url)
    # repo_name is unique per user and also matches records created before URL
    # normalization was introduced.
    res = await run_query(
        supabase_client.table("repos").select("id, status").eq("repo_name", repo_name).eq("user_id", user_id)
    )
    if res.data:
        repo = res.data[0]
        if repo["status"] in {"queued", "cloning", "chunking", "embedding", "summarizing"}:
            raise IngestionConflictError("Repository ingestion is already in progress.")
        repo_id = repo["id"]
        await run_query(
            supabase_client.table("repos").update({
                "repo_name": repo_name, "github_url": canonical_url, "status": "queued", "error_message": None, "chunk_count": 0,
            }).eq("id", repo_id)
        )
        await run_query(supabase_client.table("chunks").delete().eq("repo_id", repo_id))
        await run_query(supabase_client.table("kt_cache").delete().eq("repo_id", repo_id))
    else:
        res = await run_query(supabase_client.table("repos").insert({
            "repo_name": repo_name, "github_url": canonical_url, "status": "queued", "user_id": user_id,
        }))
        repo_id = res.data[0]["id"]
    return repo_id, repo_name


async def enqueue_ingestion_job(supabase_client, github_url: str, user_id: str, repo_id: str):
    """Persist work before returning to a serverless request handler."""
    await run_query(
        supabase_client.table("ingestion_jobs").upsert(
            {
                "repo_id": repo_id,
                "user_id": user_id,
                "github_url": github_url,
                "status": "queued",
                "attempts": 0,
                "claimed_at": None,
                "finished_at": None,
                "last_error": None,
            },
            on_conflict="repo_id",
        )
    )


async def raise_if_ingestion_cancelled(supabase_client, repo_id: str):
    job = await run_query(
        supabase_client.table("ingestion_jobs").select("status").eq("repo_id", repo_id).limit(1)
    )
    if job.data and job.data[0].get("status") == "cancelled":
        raise IngestionCancelledError("Indexing was stopped by the user.")


async def embed_repository_chunks(supabase_client, repo_id: str, chunks: list[dict]):
    """Embed in cancellable batches rather than one long blocking operation."""
    embedded_chunks = []
    for offset in range(0, len(chunks), 32):
        await raise_if_ingestion_cancelled(supabase_client, repo_id)
        embedded_chunks.extend(await run_blocking(embed_chunks, chunks[offset:offset + 32]))
    return embedded_chunks


async def requeue_stale_jobs(supabase_client):
    stale_before = (datetime.now(UTC) - timedelta(seconds=settings.ingestion_job_timeout_seconds)).isoformat()
    stale = await run_query(
        supabase_client.table("ingestion_jobs").select("id, repo_id, attempts")
        .eq("status", "processing").lt("claimed_at", stale_before)
    )
    for job in stale.data or []:
        attempts = int(job.get("attempts") or 0)
        if attempts >= settings.max_ingestion_attempts:
            error = "Ingestion timed out repeatedly. Use a smaller repository and submit it again."
            await run_query(
                supabase_client.table("ingestion_jobs").update(
                    {"status": "failed", "claimed_at": None, "finished_at": datetime.now(UTC).isoformat(), "last_error": error}
                ).eq("id", job["id"])
            )
            await run_query(
                supabase_client.table("repos").update({"status": "failed", "error_message": error}).eq("id", job["repo_id"])
            )
        else:
            await run_query(
                supabase_client.table("ingestion_jobs").update(
                    {"status": "queued", "claimed_at": None, "last_error": "Previous worker invocation timed out; retrying."}
                ).eq("id", job["id"])
            )


async def claim_next_ingestion_job(supabase_client):
    """Atomically claim at most one queued job, safe when two cron runs overlap."""
    await requeue_stale_jobs(supabase_client)
    queued = await run_query(
        supabase_client.table("ingestion_jobs").select("id, repo_id, user_id, github_url, attempts")
        .eq("status", "queued").order("created_at").limit(1)
    )
    if not queued.data:
        return None

    job = queued.data[0]
    claimed = await run_query(
        supabase_client.table("ingestion_jobs").update(
            {
                "status": "processing",
                "claimed_at": datetime.now(UTC).isoformat(),
                "attempts": int(job.get("attempts") or 0) + 1,
                "last_error": None,
            }
        ).eq("id", job["id"]).eq("status", "queued")
    )
    return job if claimed.data else None


async def process_one_queued_ingestion(supabase_client):
    """Run a durable ingestion job. The cron endpoint intentionally processes one job per invocation."""
    job = await claim_next_ingestion_job(supabase_client)
    if not job:
        return {"processed": False}

    succeeded = await run_ingestion_for_repo(
        supabase_client,
        job["github_url"],
        job["user_id"],
        job["repo_id"],
    )
    current_job = await run_query(
        supabase_client.table("ingestion_jobs").select("status").eq("id", job["id"]).limit(1)
    )
    if not current_job.data or current_job.data[0].get("status") != "cancelled":
        await run_query(
            supabase_client.table("ingestion_jobs").update(
                {
                    "status": "completed" if succeeded else "failed",
                    "finished_at": datetime.now(UTC).isoformat(),
                    "claimed_at": None,
                }
            ).eq("id", job["id"])
        )
    return {"processed": True, "repo_id": job["repo_id"], "succeeded": succeeded}


async def run_ingestion(github_url: str, user_id: str):
    assert_supabase_schema()
    await run_ingestion_for_repo(supabase, github_url, user_id)


async def run_ingestion_for_repo(supabase_client, github_url: str, user_id: str, repo_id: str | None = None):
    repo_path: str | None = None
    try:
        canonical_url = normalize_github_url(github_url)
        if repo_id is None:
            repo_id, _ = await ensure_repo_record(supabase_client, canonical_url, user_id)
        await raise_if_ingestion_cancelled(supabase_client, repo_id)
        await run_query(supabase_client.table("repos").update({
            "status": "cloning", "error_message": None, "chunk_count": 0,
        }).eq("id", repo_id))
        repo_path = await run_blocking(clone_repo_shallow, canonical_url)

        await raise_if_ingestion_cancelled(supabase_client, repo_id)
        await run_query(supabase_client.table("repos").update({"status": "chunking"}).eq("id", repo_id))
        files = await run_blocking(get_files_to_process, repo_path)
        if not files:
            raise ValueError("No supported text source files were found in this repository.")

        def collect_chunks():
            chunks = []
            for file_path in files:
                chunks.extend(chunk_file(file_path, repo_path))
                if len(chunks) > settings.max_repository_chunks:
                    raise ValueError("Repository exceeds the configured chunk limit. Use a smaller repository.")
            return chunks

        all_chunks = await run_blocking(collect_chunks)
        if not all_chunks:
            raise ValueError("No readable source code chunks were created from this repository.")

        await raise_if_ingestion_cancelled(supabase_client, repo_id)
        await run_query(supabase_client.table("repos").update({"status": "embedding"}).eq("id", repo_id))
        embedded_chunks = await embed_repository_chunks(supabase_client, repo_id, all_chunks)

        for offset in range(0, len(embedded_chunks), 100):
            await raise_if_ingestion_cancelled(supabase_client, repo_id)
            db_chunks = [{
                "repo_id": repo_id,
                "file_path": chunk["file_path"],
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
                "language": chunk["language"],
                "symbols": chunk.get("symbols", []),
                "content": chunk["content"],
                "embedding": chunk["embedding"],
            } for chunk in embedded_chunks[offset:offset + 100]]
            await run_query(supabase_client.table("chunks").insert(db_chunks))

        await raise_if_ingestion_cancelled(supabase_client, repo_id)
        await run_query(supabase_client.table("repos").update({"status": "summarizing"}).eq("id", repo_id))
        await build_kt_cache(supabase_client, repo_id, embedded_chunks)
        await raise_if_ingestion_cancelled(supabase_client, repo_id)
        await run_query(supabase_client.table("repos").update({
            "status": "ready", "chunk_count": len(embedded_chunks), "error_message": None,
        }).eq("id", repo_id))
        return True
    except IngestionCancelledError:
        logger.info("Repository ingestion cancelled for %s", repo_id)
        if repo_id:
            await run_query(supabase_client.table("chunks").delete().eq("repo_id", repo_id))
            await run_query(supabase_client.table("kt_cache").delete().eq("repo_id", repo_id))
            await run_query(supabase_client.table("repos").update({
                "status": "cancelled", "chunk_count": 0, "error_message": "Indexing stopped by you.",
            }).eq("id", repo_id))
        return False
    except Exception as error:
        error_message = explain_supabase_api_error(error)
        # Expected configuration mismatches are already turned into a clear,
        # user-facing diagnosis. Keep unexpected failures traceable without
        # flooding normal local-development logs with known migration errors.
        if error_message != str(error):
            logger.warning("Repository ingestion stopped: %s", error_message)
        else:
            logger.exception("Repository ingestion failed")
        if repo_id:
            await run_query(supabase_client.table("repos").update({
                "status": "failed", "error_message": error_message[:500],
            }).eq("id", repo_id))
        return False
    finally:
        if repo_path:
            try:
                await run_blocking(cleanup_repo, repo_path)
            except Exception:
                logger.warning("Could not clean up temporary repository directory")
