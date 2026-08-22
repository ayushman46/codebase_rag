"""Deterministic repository metadata cache; it never blocks ingestion on an LLM."""

import asyncio
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Dict, List

LANGUAGE_NAMES = {
    "py": "Python", "js": "JavaScript", "jsx": "JavaScript/React", "ts": "TypeScript",
    "tsx": "TypeScript/React", "java": "Java", "go": "Go", "rs": "Rust", "rb": "Ruby",
    "php": "PHP", "cs": "C#", "sql": "SQL", "html": "HTML", "css": "CSS",
}


async def build_kt_cache(supabase_client, repo_id: str, chunks: List[Dict]):
    """Persist factual file/language metadata without model calls or invented summaries."""
    files: dict[str, list[Dict]] = defaultdict(list)
    for chunk in chunks:
        files[chunk["file_path"]].append(chunk)
    languages = Counter(chunk["language"] for chunk in chunks)
    tech_stack = [LANGUAGE_NAMES.get(language, language) for language, _ in languages.most_common()]
    # The cache is a convenience only; bound it so metadata never becomes a
    # second copy of a very large repository.
    file_summaries = {
        path: {
            "language": file_chunks[0]["language"],
            "line_count": max(chunk["end_line"] for chunk in file_chunks),
            "symbols": [symbol for chunk in file_chunks for symbol in chunk.get("symbols", [])][:50],
        }
        for path, file_chunks in sorted(files.items())[:500]
    }
    top_directories = Counter(
        str(PurePosixPath(path).parent) for path in files if str(PurePosixPath(path).parent) != "."
    )
    onboarding_manual = (
        "Repository index summary generated from file metadata. "
        f"Indexed {len(files)} files in {len(chunks)} chunks. "
        f"Primary languages: {', '.join(tech_stack) or 'not detected'}. "
        f"Most represented directories: {', '.join(directory for directory, _ in top_directories.most_common(8)) or 'root'} . "
        "Ask a repository question to retrieve source-backed, line-level evidence."
    )
    payload = {
        "repo_id": repo_id,
        "tech_stack": tech_stack,
        "onboarding_manual": onboarding_manual,
        "file_summaries": file_summaries,
    }
    await asyncio.to_thread(lambda: supabase_client.table("kt_cache").upsert(payload, on_conflict="repo_id").execute())
