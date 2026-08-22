from agent.nemotron import complete


async def run_agent_loop(_supabase_client, _repo_id: str, question: str, initial_context: str):
    """Generate a grounded answer from bounded, retrieved repository evidence.

    Retrieval already supplies multi-file context. A single provider-neutral
    completion avoids the former provider-specific tool loop and never turns an
    unavailable LLM into an ungrounded, apparently successful response.
    """
    system_prompt = """You are a codebase-intelligence assistant. Answer only from the supplied repository evidence.

Write for a developer who wants to understand the codebase quickly. The client displays your response as plain text, so do not use Markdown syntax: no # headings, **bold**, backticks, tables, block quotes, or code fences.

Use this structure when evidence supports it:

Direct answer
One or two sentences answering the question immediately.

Relevant files
- path/to/file (Lstart-Lend): concise explanation of why it matters.

How it works
1. Explain the flow in simple, ordered steps. Include only evidence-supported steps.

Where to start
- Give practical next files or symbols to inspect when the question asks for a change, fix, or contribution.

Use only the sections that help answer the question. Keep routine answers concise; do not repeat the citation content shown separately by the application. Cite every concrete claim using the supplied file path and line range. Do not invent files, symbols, relationships, endpoints, or line numbers. If the evidence is insufficient, say exactly what could not be established from the indexed repository. Do not expose private reasoning."""
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Repository evidence:\n{initial_context}\n\nQuestion: {question}",
        },
    ]
    return await complete(messages), []
