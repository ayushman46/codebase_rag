from agent.nemotron import complete
from config import get_answer_model_options


async def run_agent_loop(
    _supabase_client,
    _repo_id: str,
    question: str,
    initial_context: str,
    conversation_history: list[dict] | None = None,
    model_profile: str = "fast",
):
    """Generate a grounded answer from bounded, retrieved repository evidence.

    Retrieval already supplies multi-file context. A single provider-neutral
    completion avoids the former provider-specific tool loop and never turns an
    unavailable LLM into an ungrounded, apparently successful response.
    """
    system_prompt = """You are a codebase-intelligence assistant. Answer only from the supplied repository evidence.

Write for a developer who wants to understand the codebase quickly. The client renders standard Markdown. Use clear headings, bold text for file names and key terms, and short lists. Do not use tables, block quotes, or code fences.

Use this structure when evidence supports it:

## Direct answer
One or two sentences answering the question immediately.

## Relevant files
- **path/to/file (Lstart-Lend):** concise explanation of why it matters.

## How it works
1. Explain the flow in simple, ordered steps. Include only evidence-supported steps.

## Where to start
- Give practical next files or symbols to inspect when the question asks for a change, fix, or contribution.

Use only the sections that help answer the question. Keep routine answers concise; do not repeat the citation content shown separately by the application. Cite every concrete claim using the supplied file path and line range. Do not invent files, symbols, relationships, endpoints, or line numbers. If the evidence is insufficient, say exactly what could not be established from the indexed repository. Do not expose private reasoning."""
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    for message in (conversation_history or [])[-10:]:
        role = message.get("role")
        content = str(message.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({
        "role": "user",
        "content": (
            "Use the conversation only to resolve references in the current question. "
            "The repository evidence below is the sole source for factual claims.\n\n"
            f"Repository evidence:\n{initial_context}\n\nQuestion: {question}"
        ),
    })
    model, enable_thinking, max_tokens = get_answer_model_options(model_profile)
    return await complete(
        messages,
        model=model,
        enable_thinking=enable_thinking,
        max_tokens=max_tokens,
    ), []
