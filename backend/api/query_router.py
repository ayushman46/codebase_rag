"""Repository question and conversation endpoints backed by Turso."""

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agent.agent import run_agent_loop
from agent.nemotron import LLMProviderError
from api.auth import get_current_user
from config import ModelConfigurationError, query_request_limiter, settings
from database import DatabaseConfigurationError, assert_turso_schema, explain_database_error, get_turso_store
from retrieval.retriever import build_evidence_plan, retrieve_context

logger = logging.getLogger(__name__)
router = APIRouter()

_GREETING_PATTERN = re.compile(
    r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening))(?:\s+(?:there|everyone|again))?[!. ]*$",
    re.IGNORECASE,
)


class QueryRequest(BaseModel):
    repo_name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4_000)
    model_profile: Literal["fast", "detailed"] = "fast"
    workflow: Literal["general", "onboarding", "security", "architecture", "contributor", "due_diligence"] = "general"


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


async def get_owned_repo(store, repo_name: str, user_id: str):
    repo = await store.fetch_one(
        "SELECT id, status FROM repos WHERE repo_name = ? AND user_id = ?", [repo_name, user_id]
    )
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
    return repo


async def get_conversation_history(store, repo_id: str, user_id: str, limit: int | None = None):
    rows = await store.fetch_all(
        "SELECT role, content FROM chat_messages WHERE repo_id = ? AND user_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        [repo_id, user_id, limit or settings.conversation_history_messages],
    )
    remaining, retained = settings.max_conversation_history_characters, []
    for message in rows:
        content = str(message.get("content") or "").strip()
        if not content or remaining <= 0:
            continue
        content = content[:min(settings.max_conversation_message_characters, remaining)]
        retained.append({"role": message["role"], "content": content})
        remaining -= len(content)
    return list(reversed(retained))


def build_context(chunks: list[dict]) -> str:
    remaining, sections = settings.max_context_characters, []
    for chunk in chunks:
        header = (
            f"File: {chunk['file_path']} (L{chunk['start_line']}-L{chunk['end_line']})"
            f"\nSymbols: {', '.join(chunk.get('symbols') or []) or 'not detected'}"
            f"\nRetrieval reason: {'; '.join(chunk.get('_retrieval_reasons') or []) or 'source match'}\n"
        )
        budget = remaining - len(header) - 2
        if budget <= 0:
            break
        sections.append(f"{header}{chunk['content'][:budget]}")
        remaining -= len(header) + len(chunk["content"][:budget]) + 2
    return "\n\n".join(sections)


def build_retrieval_fallback(chunks: list[dict]) -> str:
    lines = [
        "## Retrieved code context",
        "Live answer generation is temporarily unavailable. The relevant repository evidence is available below.",
        "",
        "## Relevant files",
    ]
    for chunk in chunks[:5]:
        summary = " ".join(str(chunk.get("content") or "").split())[:220]
        lines.append(f"- **{chunk['file_path']} (L{chunk['start_line']}-L{chunk['end_line']}):** {summary or 'Indexed source evidence.'}")
    lines.extend(["", "## Next step", "Try the question again in a moment. The citations below remain available for direct inspection."])
    return "\n".join(lines)


def build_no_evidence_response() -> str:
    return (
        "I can help you explore this repository. Ask about its architecture, features, implementation choices, "
        "files, or how it differs from a typical approach. I will keep the answer grounded in the indexed source."
    )


def is_greeting(question: str) -> bool:
    """Avoid calling retrieval and an answer model for a simple greeting."""
    return bool(_GREETING_PATTERN.fullmatch(question.strip()))


def build_greeting_response(repo_name: str) -> str:
    return f"Hello. What would you like to understand about **{repo_name}**?"


async def save_message(store, *, repo_id: str, user_id: str, role: str, content: str,
                       citations: list | None = None, tool_calls: list | None = None,
                       mode: str | None = None, latency_ms: int | None = None) -> None:
    await store.execute(
        "INSERT INTO chat_messages (id, repo_id, user_id, role, content, citations, tool_calls, mode, latency_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [str(uuid4()), repo_id, user_id, role, content, json.dumps(citations or []), json.dumps(tool_calls or []), mode, latency_ms, timestamp()],
    )


@router.post("/query")
async def query_repo(req: QueryRequest, current_user=Depends(get_current_user)):
    started, limiter_acquired = time.time(), False
    try:
        await query_request_limiter.acquire(current_user.id)
        limiter_acquired = True
        await assert_turso_schema()
        store = get_turso_store()
        repo = await get_owned_repo(store, req.repo_name, current_user.id)
        if repo["status"] != "ready":
            raise HTTPException(status_code=409, detail="Repository is not ready for questions. Check the repository status and try again.")
        question = req.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="Question must contain non-whitespace text.")
        workflow = getattr(req, "workflow", "general")
        evidence_plan = build_evidence_plan(question, workflow)
        if is_greeting(question):
            answer, tool_calls, mode, citations = build_greeting_response(req.repo_name), [], "greeting", []
        else:
            chunks, conversation_history = await asyncio.gather(
                retrieve_context(store, repo["id"], question, top_k=settings.retrieval_top_k, workflow=workflow),
                get_conversation_history(store, repo["id"], current_user.id),
            )
            if not chunks:
                answer, tool_calls, mode, citations = build_no_evidence_response(), [], "repository_guidance", []
            else:
                context = build_context(chunks)
                if not context:
                    raise HTTPException(status_code=422, detail="Repository evidence exceeded the configured context limit.")
                try:
                    answer, tool_calls = await run_agent_loop(
                        store, repo["id"], question, context, conversation_history, req.model_profile,
                        workflow=workflow, evidence_plan=evidence_plan,
                    )
                    mode = "rag"
                except (LLMProviderError, ModelConfigurationError):
                    logger.warning("Live answer generation unavailable for repository %s; returning retrieved evidence", repo["id"])
                    answer, tool_calls, mode = build_retrieval_fallback(chunks), [], "retrieval_fallback"
                citations = [
                    {
                        "file_path": chunk["file_path"], "start_line": chunk["start_line"], "end_line": chunk["end_line"],
                        "content": chunk["content"], "language": chunk["language"], "symbols": chunk.get("symbols", []),
                        "retrieval_methods": chunk.get("_retrieval_methods") or ["retrieval"],
                        "retrieval_reasons": chunk.get("_retrieval_reasons") or ["Relevant source match"],
                        "relevance_score": chunk.get("_relevance_score", 0),
                        "support_status": "source-backed",
                    }
                    for chunk in chunks
                ]
        latency_ms = int((time.time() - started) * 1000)
        await save_message(store, repo_id=repo["id"], user_id=current_user.id, role="user", content=question)
        await save_message(
            store, repo_id=repo["id"], user_id=current_user.id, role="assistant", content=answer,
            citations=citations, tool_calls=tool_calls, mode=mode, latency_ms=latency_ms,
        )
        return {
            "answer": answer, "mode": mode, "citations": citations, "tool_calls": tool_calls,
            "latency_ms": latency_ms, "tokens_used": 0, "model_profile": req.model_profile,
            "workflow": workflow, "evidence_plan": evidence_plan,
        }
    except HTTPException:
        raise
    except (ModelConfigurationError, DatabaseConfigurationError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except RuntimeError as error:
        if str(error) in {"rate_limit", "concurrency_limit"}:
            raise HTTPException(status_code=429, detail="Too many questions are already being processed. Please wait a moment and try again.") from error
        raise
    except Exception as error:
        logger.exception("Repository query failed")
        raise HTTPException(status_code=500, detail=explain_database_error(error)) from error
    finally:
        if limiter_acquired:
            await query_request_limiter.release(current_user.id)


@router.get("/conversations/{repo_name}")
async def get_conversation(repo_name: str, limit: int = Query(default=100, ge=1, le=200), current_user=Depends(get_current_user)):
    try:
        await assert_turso_schema()
        store = get_turso_store()
        repo = await get_owned_repo(store, repo_name, current_user.id)
        messages = await store.fetch_all(
            "SELECT id, role, content, citations, tool_calls, mode, latency_ms, created_at "
            "FROM chat_messages WHERE repo_id = ? AND user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            [repo["id"], current_user.id, limit],
        )
        return {"messages": list(reversed(messages))}
    except HTTPException:
        raise
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not load conversation history")
        raise HTTPException(status_code=500, detail=explain_database_error(error)) from error
