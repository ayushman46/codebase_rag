import os
import json
import time
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
from config import settings, gemini_rate_limiter
from retrieval.router import classify_query
from retrieval.retriever import retrieve_context
from agent.agent import run_agent_loop

router = APIRouter(prefix="/api")
genai.configure(api_key=settings.gemini_api_key)
gemini_model = genai.GenerativeModel('gemini-2.0-flash')

class QueryRequest(BaseModel):
    repo_name: str
    question: str

from groq import AsyncGroq
from config import settings, groq_rate_limiter, gemini_rate_limiter

client = AsyncGroq(api_key=settings.groq_api_key)

async def full_context_query(repo_name: str, question: str) -> tuple[str, list]:
    # Use absolute path or ensure it's relative to the backend root where uvicorn runs
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_path = os.path.join(backend_root, "repos", repo_name)
    
    if not os.path.exists(repo_path):
        print(f"Repo path not found: {repo_path}")
        return None, []

    total_chars = 0
    full_code = ""
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'node_modules', 'venv', '__pycache__'}]
        for file in files:
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    total_chars += len(content)
                    rel_path = os.path.relpath(filepath, repo_path)
                    full_code += f"\n--- {rel_path} ---\n{content}\n"
            except:
                pass
                
    # Groq Llama 3.3 handles 128k tokens. 1 token ~ 4 chars.
    # We'll cap at 100k tokens (400k chars) for safety and speed.
    if total_chars < 400_000:
        try:
            await groq_rate_limiter.acquire()
            prompt = (
                f"You are an expert technical architect. Provide a high-level, detailed prose explanation of the project based on the codebase below. "
                "Focus on the project's purpose, core logic, data flow, and key features. "
                "DO NOT provide large code blocks or simple import lists. Focus on EXPLAINING the system in English.\n\n"
                f"Codebase:\n{full_code}\n\nQuestion: {question}"
            )
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3000,
                temperature=0.3
            )
            return response.choices[0].message.content, []
        except Exception as e:
            print(f"Groq full context error: {e}")
            # Fallback to Gemini if Groq fails
                
    # Gemini Fallback for larger repos (up to 1M tokens)
    if total_chars < 3_000_000:
        for attempt in range(2):
            try:
                await gemini_rate_limiter.acquire()
                prompt = f"You are an expert developer. Analyze this codebase:\n{full_code}\n\nQuestion: {question}"
                response = await gemini_model.generate_content_async(prompt)
                return response.text, []
            except Exception as e:
                if "429" in str(e):
                    await asyncio.sleep(2)
                else: break
                
    return None, []

def get_cached_summary(repo_name: str, question: str) -> tuple[str, list]:
    cache_path = f"./indexes/{repo_name}/kt_cache.json"
    if not os.path.exists(cache_path):
        return "Cache not found for this repo.", []
        
    with open(cache_path, 'r', encoding='utf-8') as f:
        cache = json.load(f)
        
    # provide the high-level onboarding manual if it exists
    manual = cache.get("onboarding_manual", "")
    if manual:
        response_text = f"## PROJECT TRANSITION MANUAL (Original Creator's Notes)\n\n"
        response_text += f"{manual}\n\n"
        response_text += f"### DETECTED TECH STACK:\n{cache.get('tech_stack', 'N/A')}\n"
        return response_text, []

    # Fallback to legacy behavior
    response_text = f"**Architecture Overview:**\n{cache.get('architecture_doc', 'N/A')}\n\n"
    response_text += f"**Key Modules:**\n"
    for mod, summary in cache.get('module_overviews', {}).items():
        response_text += f"- **{mod}**: {summary}\n"
        
    return response_text, []

@router.post("/query")
async def query_repo(request: QueryRequest):
    try:
        start_time = time.time()
        
        # 1. Classify
        mode = await classify_query(request.question)
        
        answer = ""
        citations = []
        tool_calls = []
        
        if mode == "full_context":
            ans, cits = await full_context_query(request.repo_name, request.question)
            if ans is None:
                mode = "rag" # Fallback to RAG
            else:
                answer = ans
                citations = cits
                
        if mode == "cached_summary":
            ans, cits = get_cached_summary(request.repo_name, request.question)
            if not ans or len(ans) < 100 or "Cache not found" in ans:
                mode = "rag"
            else:
                answer = ans
                citations = cits
                
        if mode == "rag":
            chunks = retrieve_context(request.repo_name, request.question, top_k=8)
            context_str = "\n\n".join([f"File: {c['file_path']} (Lines {c['start_line']}-{c['end_line']})\n```\n{c['content']}\n```" for c in chunks])
            
            ans, t_calls = await run_agent_loop(request.repo_name, request.question, context_str)
            answer = ans
            tool_calls = t_calls
            
            for c in chunks:
                if c.get("id") == "readme": continue
                citations.append({
                    "file": c["file_path"],
                    "start_line": c["start_line"],
                    "end_line": c["end_line"],
                    "function_name": c.get("name", "unknown"),
                    "snippet": "\n".join(c["content"].split("\n")[:3])
                })
                
        latency_ms = int((time.time() - start_time) * 1000)
        
        return {
            "answer": answer,
            "mode": mode,
            "citations": citations,
            "tool_calls": tool_calls,
            "latency_ms": latency_ms,
            "tokens_used": 0
        }
    except Exception as e:
        print(f"Global Query Error: {e}")
        return {
            "answer": f"I encountered an error while processing your request: {str(e)}. Please try again in a moment.",
            "mode": "error",
            "citations": [],
            "tool_calls": [],
            "latency_ms": 0,
            "tokens_used": 0
        }