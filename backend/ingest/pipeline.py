import asyncio
import logging

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


async def run_ingestion(github_url: str, user_id: str):
    assert_supabase_schema()
    await run_ingestion_for_repo(supabase, github_url, user_id)


async def run_ingestion_for_repo(supabase_client, github_url: str, user_id: str, repo_id: str | None = None):
    repo_path: str | None = None
    try:
        canonical_url = normalize_github_url(github_url)
        if repo_id is None:
            repo_id, _ = await ensure_repo_record(supabase_client, canonical_url, user_id)
        await run_query(supabase_client.table("repos").update({
            "status": "cloning", "error_message": None, "chunk_count": 0,
        }).eq("id", repo_id))
        repo_path = await run_blocking(clone_repo_shallow, canonical_url)

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

        await run_query(supabase_client.table("repos").update({"status": "embedding"}).eq("id", repo_id))
        embedded_chunks = await run_blocking(embed_chunks, all_chunks)

        for offset in range(0, len(embedded_chunks), 100):
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

        await run_query(supabase_client.table("repos").update({"status": "summarizing"}).eq("id", repo_id))
        await build_kt_cache(supabase_client, repo_id, embedded_chunks)
        await run_query(supabase_client.table("repos").update({
            "status": "ready", "chunk_count": len(embedded_chunks), "error_message": None,
        }).eq("id", repo_id))
    except Exception as error:
        error_message = explain_supabase_api_error(error)
        logger.exception("Repository ingestion failed")
        if repo_id:
            await run_query(supabase_client.table("repos").update({
                "status": "failed", "error_message": error_message[:500],
            }).eq("id", repo_id))
    finally:
        if repo_path:
            try:
                await run_blocking(cleanup_repo, repo_path)
            except Exception:
                logger.warning("Could not clean up temporary repository directory")
