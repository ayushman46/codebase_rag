import time
import asyncio
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from database import assert_supabase_schema, DatabaseConfigurationError, explain_supabase_api_error, get_user_scoped_supabase
from retrieval.router import classify_query
from retrieval.retriever import retrieve_context
from agent.agent import run_agent_loop
from ingest.summarizer import generate_with_gemini
from api.auth import get_current_user

router = APIRouter()


async def run_query(query):
    return await asyncio.to_thread(query.execute)

class QueryRequest(BaseModel):
    repo_name: str
    question: str

@router.post("/query")
async def query_repo(req: QueryRequest, current_user = Depends(get_current_user)):
    start_time = time.time()
    try:
        assert_supabase_schema()
    except DatabaseConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))

    supabase = get_user_scoped_supabase(current_user.access_token)
    
    # Get repo_id scoped by user_id
    res = await run_query(
        supabase.table('repos').select('id, status').eq('repo_name', req.repo_name).eq('user_id', current_user.id)
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    repo = res.data[0]
    if repo['status'] != 'ready':
        raise HTTPException(status_code=400, detail=f"Repository is not ready. Status: {repo['status']}")
        
    repo_id = repo['id']
    question = req.question
    
    try:
        mode = await classify_query(question)
        
        answer = ""
        citations = []
        tool_calls = []
        
        if mode == "cached_summary":
            kt_res = await run_query(supabase.table('kt_cache').select('*').eq('repo_id', repo_id))
            if kt_res.data:
                cache = kt_res.data[0]
                answer = f"**Tech Stack:** {', '.join(cache.get('tech_stack', []))}\\n\\n"
                answer += f"**Onboarding Manual:**\\n{cache.get('onboarding_manual', '')}\\n"
            else:
                mode = "rag"
                
        if mode == "full_context":
            # Pull chunks up to Gemini's free limits
            chunks_res = await run_query(
                supabase.table('chunks').select('file_path, content').eq('repo_id', repo_id).limit(500)
            )
            full_text = "\\n\\n".join([f"--- {c['file_path']} ---\\n{c['content']}" for c in chunks_res.data])
            prompt = f"Codebase Context:\\n{full_text}\\n\\nQuestion: {question}\\nAnswer comprehensively."
            answer = await generate_with_gemini(prompt)
            if not answer.strip():
                mode = "rag"
            
        if mode == "rag":
            chunks = await retrieve_context(supabase, repo_id, question)
            context = "\\n\\n".join([f"File: {c['file_path']} (L{c['start_line']}-L{c['end_line']})\\n{c['content']}" for c in chunks])
            
            for c in chunks:
                citations.append({
                    "file_path": c['file_path'],
                    "start_line": c['start_line'],
                    "content": c['content'],
                    "language": c['language']
                })
                
            answer, tool_calls = await run_agent_loop(supabase, repo_id, question, context)
            
        latency = int((time.time() - start_time) * 1000)
        
        return {
            "answer": answer,
            "mode": mode,
            "citations": citations,
            "tool_calls": tool_calls,
            "latency_ms": latency,
            "tokens_used": 0
        }
    except Exception as e:
        print(f"Query error: {e}")
        return {
            "answer": explain_supabase_api_error(e) if "row-level security" in str(e).lower() else "I encountered an error processing your request.",
            "mode": "error",
            "citations": [],
            "tool_calls": [],
            "latency_ms": int((time.time() - start_time) * 1000)
        }
