import os
from groq import AsyncGroq
from config import settings, groq_rate_limiter

client = AsyncGroq(api_key=settings.groq_api_key)

ROUTER_PROMPT = """
Classify this codebase question into exactly one category. Reply with ONLY the category name.

Categories:
- full_context: Use this for high-level requests like "explain this project", "how does it work", "onboarding", "architecture overview", "what is this repo about", "summarize the whole thing".
- cached_summary: Use this for file or module specific overviews like "what does main.py do", "what is in the auth module", "list all endpoints".
- rag: Use this for specific code behavior, debugging, tracing a symbol, or "how is X implemented".

Question: {question}
Category:
"""

async def classify_query(question: str) -> str:
    q_lower = question.lower().strip()
    full_context_keywords = {
        "explain this project", "what is this repo", "how does it work", 
        "architecture overview", "project summary", "explain the project",
        "what does this do", "summarize this repo", "what is this about"
    }
    if any(k in q_lower for k in full_context_keywords):
        return "full_context"

    await groq_rate_limiter.acquire()
    prompt = ROUTER_PROMPT.format(question=question)
    
    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.0
        )
        category = response.choices[0].message.content.strip().lower()
        if "full_context" in category: return "full_context"
        elif "cached_summary" in category: return "cached_summary"
        else: return "rag"
    except Exception as e:
        print(f"Router error: {e}")
        return "rag"
