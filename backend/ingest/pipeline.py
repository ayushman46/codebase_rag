import asyncio
from database import supabase, assert_supabase_schema, explain_supabase_api_error
from ingest.cloner import clone_repo_shallow, get_files_to_process, cleanup_repo
from ingest.chunker import chunk_file
from ingest.embedder import embed_chunks
from ingest.summarizer import build_kt_cache

async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def run_query(query):
    return await asyncio.to_thread(query.execute)


async def ensure_repo_record(supabase_client, github_url: str, user_id: str):
    repo_name = github_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    res = await run_query(
        supabase_client.table('repos').select('id').eq('github_url', github_url).eq('user_id', user_id)
    )
    if res.data:
        repo_id = res.data[0]['id']
        await run_query(
            supabase_client.table('repos').update({
                "repo_name": repo_name,
                "status": "queued",
                "error_message": None,
                "chunk_count": 0
            }).eq('id', repo_id)
        )
        await run_query(supabase_client.table('chunks').delete().eq('repo_id', repo_id))
        await run_query(supabase_client.table('kt_cache').delete().eq('repo_id', repo_id))
    else:
        res = await run_query(supabase_client.table('repos').insert({
            "repo_name": repo_name,
            "github_url": github_url,
            "status": "queued",
            "user_id": user_id
        }))
        repo_id = res.data[0]['id']

    return repo_id, repo_name


async def run_ingestion(github_url: str, user_id: str):
    assert_supabase_schema()
    await run_ingestion_for_repo(supabase, github_url, user_id)


async def run_ingestion_for_repo(supabase_client, github_url: str, user_id: str, repo_id: str | None = None):
    repo_name = github_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
        
    try:
        if repo_id is None:
            repo_id, _ = await ensure_repo_record(supabase_client, github_url, user_id)

        await run_query(
            supabase_client.table('repos').update({
                "status": "cloning",
                "error_message": None,
                "chunk_count": 0
            }).eq('id', repo_id)
        )

        repo_path = await run_blocking(clone_repo_shallow, github_url)
        
        await run_query(supabase_client.table('repos').update({"status": "chunking"}).eq('id', repo_id))
        files = await run_blocking(get_files_to_process, repo_path)
        
        def collect_chunks():
            chunks = []
            for file in files:
                file_chunks = chunk_file(file, repo_path)
                chunks.extend(file_chunks)
            return chunks

        all_chunks = await run_blocking(collect_chunks)
            
        await run_query(supabase_client.table('repos').update({"status": "embedding"}).eq('id', repo_id))
        embedded_chunks = await run_blocking(embed_chunks, all_chunks)
        
        # Batch insert chunks to Supabase in parallel
        batch_size = 300
        insert_tasks = []
        for i in range(0, len(embedded_chunks), batch_size):
            batch = embedded_chunks[i:i+batch_size]
            db_chunks = []
            for c in batch:
                db_chunks.append({
                    "repo_id": repo_id,
                    "file_path": c['file_path'],
                    "start_line": c['start_line'],
                    "end_line": c['end_line'],
                    "language": c['language'],
                    "content": c['content'],
                    "embedding": c['embedding']
                })
            insert_tasks.append(run_query(supabase_client.table('chunks').insert(db_chunks)))
        
        if insert_tasks:
            await asyncio.gather(*insert_tasks)
            
        await run_query(supabase_client.table('repos').update({"status": "summarizing"}).eq('id', repo_id))
        
        try:
            await build_kt_cache(supabase_client, repo_id, embedded_chunks)
        except Exception as e:
            print(f"Warning: KT Cache generation failed: {e}")
            
        await run_query(supabase_client.table('repos').update({
            "status": "ready",
            "chunk_count": len(embedded_chunks)
        }).eq('id', repo_id))
        
    except Exception as e:
        error_message = explain_supabase_api_error(e)
        print(f"Ingestion failed for {github_url}: {error_message}")
        if repo_id:
            await run_query(supabase_client.table('repos').update({
                "status": "failed",
                "error_message": error_message
            }).eq('id', repo_id))
    finally:
        # Cleanup
        try:
            await run_blocking(cleanup_repo, f"./repos_temp/{repo_name}")
        except:
            pass
