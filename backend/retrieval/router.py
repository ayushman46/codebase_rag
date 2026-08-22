async def classify_query(_question: str) -> str:
    """All questions use bounded retrieval; no mode may send the whole repo to an LLM."""
    return "rag"
