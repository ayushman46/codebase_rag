import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.agent import run_agent_loop
from agent.nemotron import LLMProviderError
from api.auth import get_current_user
from config import ModelConfigurationError, require_nvidia_api_key, settings
from database import DatabaseConfigurationError, get_user_scoped_supabase
from database import assert_supabase_schema, explain_supabase_api_error
from retrieval.retriever import retrieve_context

logger = logging.getLogger(__name__)
router = APIRouter()


async def run_query(query):
    return await asyncio.to_thread(query.execute)


class QueryRequest(BaseModel):
    repo_name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4_000)


def build_context(chunks: list[dict]) -> str:
    remaining = settings.max_context_characters
    sections: list[str] = []
    for chunk in chunks:
        header = (
            f"File: {chunk['file_path']} (L{chunk['start_line']}-L{chunk['end_line']})"
            f"\nSymbols: {', '.join(chunk.get('symbols') or []) or 'not detected'}\n"
        )
        budget = remaining - len(header) - 2
        if budget <= 0:
            break
        content = chunk["content"][:budget]
        sections.append(f"{header}{content}")
        remaining -= len(header) + len(content) + 2
    return "\n\n".join(sections)


@router.post("/query")
async def query_repo(req: QueryRequest, current_user=Depends(get_current_user)):
    start_time = time.time()
    try:
        assert_supabase_schema()
        require_nvidia_api_key()
        supabase_client = get_user_scoped_supabase(current_user.access_token)
        res = await run_query(
            supabase_client.table("repos").select("id, status").eq("repo_name", req.repo_name).eq("user_id", current_user.id)
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="Repository not found.")
        repo = res.data[0]
        if repo["status"] != "ready":
            raise HTTPException(status_code=409, detail=f"Repository is not ready (status: {repo['status']}).")

        question = req.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="Question must contain non-whitespace text.")
        chunks = await retrieve_context(supabase_client, repo["id"], question)
        if not chunks:
            raise HTTPException(status_code=422, detail="No repository evidence was available for this question.")
        context = build_context(chunks)
        if not context:
            raise HTTPException(status_code=422, detail="Repository evidence exceeded the configured context limit.")
        answer, tool_calls = await run_agent_loop(supabase_client, repo["id"], question, context)
        citations = [{
            "file_path": chunk["file_path"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "content": chunk["content"],
            "language": chunk["language"],
            "symbols": chunk.get("symbols", []),
        } for chunk in chunks]
        return {
            "answer": answer, "mode": "rag", "citations": citations, "tool_calls": tool_calls,
            "latency_ms": int((time.time() - start_time) * 1000), "tokens_used": 0,
        }
    except HTTPException:
        raise
    except (ModelConfigurationError, DatabaseConfigurationError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except LLMProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        logger.exception("Repository query failed")
        detail = explain_supabase_api_error(error)
        if "row-level security" in detail.lower():
            raise HTTPException(status_code=403, detail=detail) from error
        raise HTTPException(status_code=500, detail="Could not process the repository query.") from error
