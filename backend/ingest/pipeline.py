import asyncio
from database import supabase
from ingest.cloner import clone_repo_shallow, get_files_to_process, cleanup_repo
from ingest.chunker import chunk_file
from ingest.embedder import embed_chunks
from ingest.summarizer import build_kt_cache

async def run_ingestion(github_url: str, user_id: str):
    repo_name = github_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
        
    repo_id = None
    try:
        # Create or fetch repo row scoped by user_id
        res = supabase.table('repos').select('id').eq('github_url', github_url).eq('user_id', user_id).execute()
        if res.data:
            repo_id = res.data[0]['id']
            # Reset chunks
            supabase.table('repos').update({"status": "cloning", "error_message": None, "chunk_count": 0}).eq('id', repo_id).execute()
            supabase.table('chunks').delete().eq('repo_id', repo_id).execute()
            supabase.table('kt_cache').delete().eq('repo_id', repo_id).execute()
        else:
            res = supabase.table('repos').insert({
                "repo_name": repo_name,
                "github_url": github_url,
                "status": "cloning",
                "user_id": user_id
            }).execute()
            repo_id = res.data[0]['id']

        repo_path = clone_repo_shallow(github_url)
        
        supabase.table('repos').update({"status": "chunking"}).eq('id', repo_id).execute()
        files = get_files_to_process(repo_path)
        
        all_chunks = []
        for file in files:
            file_chunks = chunk_file(file, repo_path)
            all_chunks.extend(file_chunks)
            
        supabase.table('repos').update({"status": "embedding"}).eq('id', repo_id).execute()
        embedded_chunks = embed_chunks(all_chunks)
        
        # Batch insert chunks to Supabase
        batch_size = 50
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
            supabase.table('chunks').insert(db_chunks).execute()
            
        supabase.table('repos').update({"status": "summarizing"}).eq('id', repo_id).execute()
        
        try:
            await build_kt_cache(repo_id, embedded_chunks)
        except Exception as e:
            print(f"Warning: KT Cache generation failed: {e}")
            
        supabase.table('repos').update({
            "status": "ready",
            "chunk_count": len(embedded_chunks)
        }).eq('id', repo_id).execute()
        
    except Exception as e:
        print(f"Ingestion failed for {github_url}: {e}")
        if repo_id:
            supabase.table('repos').update({
                "status": "failed",
                "error_message": str(e)
            }).eq('id', repo_id).execute()
    finally:
        # Cleanup
        try:
            cleanup_repo(f"./repos_temp/{repo_name}")
        except:
            pass
