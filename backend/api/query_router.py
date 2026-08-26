import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query
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


async def get_owned_repo(supabase_client, repo_name: str, user_id: str):
    res = await run_query(
        supabase_client.table("repos").select("id, status").eq("repo_name", repo_name).eq("user_id", user_id)
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Repository not found.")
    return res.data[0]


async def get_conversation_history(supabase_client, repo_id: str, user_id: str, limit: int | None = None):
    res = await run_query(
        supabase_client.table("chat_messages").select("role, content")
        .eq("repo_id", repo_id).eq("user_id", user_id).order("created_at", desc=True)
        .limit(limit or settings.conversation_history_messages)
    )
    remaining = settings.max_conversation_history_characters
    retained = []
    for message in res.data or []:
        content = str(message.get("content") or "").strip()
        if not content or remaining <= 0:
            continue
        content = content[:min(settings.max_conversation_message_characters, remaining)]
        retained.append({"role": message.get("role"), "content": content})
        remaining -= len(content)
    return list(reversed(retained))


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


def build_retrieval_fallback(chunks: list[dict]) -> str:
    """Return a useful, cited response when live answer generation is unavailable."""
    lines = [
        "## Retrieved code context",
        "Live answer generation is temporarily unavailable. The relevant repository evidence is available below.",
        "",
        "## Relevant files",
    ]
    for chunk in chunks[:5]:
        summary = " ".join(str(chunk.get("content") or "").split())[:220]
        lines.append(
            f"- **{chunk['file_path']} (L{chunk['start_line']}-L{chunk['end_line']}):** {summary or 'Indexed source evidence.'}"
        )
    lines.extend([
        "",
        "## Next step",
        "Try the question again in a moment. The citations below remain available for direct inspection.",
    ])
    return "\n".join(lines)


@router.post("/query")
async def query_repo(req: QueryRequest, current_user=Depends(get_current_user)):
    start_time = time.time()
    try:
        assert_supabase_schema()
        supabase_client = get_user_scoped_supabase(current_user.access_token)
        repo = await get_owned_repo(supabase_client, req.repo_name, current_user.id)
        if repo["status"] != "ready":
            raise HTTPException(status_code=409, detail=f"Repository is not ready (status: {repo['status']}).")

        question = req.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="Question must contain non-whitespace text.")
        chunks, conversation_history = await asyncio.gather(
            retrieve_context(supabase_client, repo["id"], question, top_k=settings.retrieval_top_k),
            get_conversation_history(supabase_client, repo["id"], current_user.id),
        )
        if not chunks:
            raise HTTPException(status_code=422, detail="No repository evidence was available for this question.")
        context = build_context(chunks)
        if not context:
            raise HTTPException(status_code=422, detail="Repository evidence exceeded the configured context limit.")
        try:
            answer, tool_calls = await run_agent_loop(
                supabase_client, repo["id"], question, context, conversation_history
            )
            mode = "rag"
        except (LLMProviderError, ModelConfigurationError):
            logger.warning("Live answer generation unavailable for repository %s; returning retrieved evidence", repo["id"])
            answer, tool_calls, mode = build_retrieval_fallback(chunks), [], "retrieval_fallback"
        citations = [{
            "file_path": chunk["file_path"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "content": chunk["content"],
            "language": chunk["language"],
            "symbols": chunk.get("symbols", []),
        } for chunk in chunks]
        latency_ms = int((time.time() - start_time) * 1000)
        await run_query(
            supabase_client.table("chat_messages").insert([
                {
                    "repo_id": repo["id"], "user_id": current_user.id, "role": "user",
                    "content": question, "citations": [], "tool_calls": [],
                    "mode": None, "latency_ms": None,
                },
                {
                    "repo_id": repo["id"], "user_id": current_user.id, "role": "assistant",
                    "content": answer, "citations": citations, "tool_calls": tool_calls,
                    "mode": mode, "latency_ms": latency_ms,
                },
            ])
        )
        return {
            "answer": answer, "mode": mode, "citations": citations, "tool_calls": tool_calls,
            "latency_ms": latency_ms, "tokens_used": 0,
        }
    except HTTPException:
        raise
    except (ModelConfigurationError, DatabaseConfigurationError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Repository query failed")
        detail = explain_supabase_api_error(error)
        if "row-level security" in detail.lower():
            raise HTTPException(status_code=403, detail=detail) from error
        raise HTTPException(status_code=500, detail="Could not process the repository query.") from error


@router.get("/conversations/{repo_name}")
async def get_conversation(
    repo_name: str,
    limit: int = Query(default=100, ge=1, le=200),
    current_user=Depends(get_current_user),
):
    try:
        assert_supabase_schema()
        supabase_client = get_user_scoped_supabase(current_user.access_token)
        repo = await get_owned_repo(supabase_client, repo_name, current_user.id)
        res = await run_query(
            supabase_client.table("chat_messages")
            .select("id, role, content, citations, tool_calls, mode, latency_ms, created_at")
            .eq("repo_id", repo["id"]).eq("user_id", current_user.id)
            .order("created_at", desc=True).limit(limit)
        )
        return {"messages": list(reversed(res.data or []))}
    except HTTPException:
        raise
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not load conversation history")
        raise HTTPException(status_code=500, detail="Could not load conversation history.") from error
