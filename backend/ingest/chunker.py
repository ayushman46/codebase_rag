import os
import re
from collections.abc import Iterator
from bisect import bisect_left
from typing import Dict, List

MAX_LINES_PER_CHUNK = 150
CHUNK_OVERLAP = 40
MAX_CHARS_PER_CHUNK = 12000
# ``chunk_file_content`` intentionally remains the compatibility path for
# callers that already have a string.  The ingestion worker uses the streaming
# path for larger files so a 50 MB source file never becomes a second 50 MB
# string plus a list of all of its chunks in the worker.
STREAMING_FILE_THRESHOLD = 2_000_000

# Basic boundary patterns for common languages
BOUNDARY_REGEX = re.compile(
    r"^(?:def|class|function|func|interface|struct)\s+"
    r"|^(?:public|private|protected)\s+(?:class|interface|enum|.*?\s+\w+\()"
    r"|^(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>",
    re.MULTILINE
)

SYMBOL_REGEX = re.compile(
    r"^\s*(?:async\s+)?(?:def|class|function|func|interface|struct|enum)\s+([A-Za-z_$][\w$]*)"
    r"|^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
    re.MULTILINE,
)


def extract_symbols(content: str) -> List[str]:
    """Return declaration names in source order, without pretending to parse an AST."""
    symbols: List[str] = []
    for match in SYMBOL_REGEX.finditer(content):
        symbol = next((group for group in match.groups() if group), None)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols[:50]

def chunk_file_content(content: str, rel_path: str) -> List[Dict]:
    """Split already-loaded source text into deterministic retrieval chunks.

    Keeping the pure content operation separate lets the ingestion worker run
    several *bounded* files concurrently without changing chunk boundaries or
    reading a file more than once inside a worker.
    """
    if not content.strip():
        return []

    _, ext = os.path.splitext(rel_path)
    ext = ext.lower()
    language = ext[1:] if ext else "text"

    # splitlines avoids manufacturing a non-existent extra line for a final newline.
    lines = content.splitlines()

    # 1. If file is small and not obviously minified/generated, treat as single chunk
    if len(lines) <= 200 and len(content) <= MAX_CHARS_PER_CHUNK:
        return [{
            "file_path": rel_path,
            "start_line": 1,
            "end_line": len(lines),
            "content": content,
            "language": language,
            "symbols": extract_symbols(content),
        }]

    if is_probably_minified(content, lines):
        return split_by_characters(content, rel_path, language)

    chunks = []

    # 2. Try regex boundary detection
    boundaries = [0]
    for i, line in enumerate(lines):
        if BOUNDARY_REGEX.search(line):
            boundaries.append(i)

    boundaries.append(len(lines))

    # Process boundaries
    for i in range(len(boundaries) - 1):
        start_line = boundaries[i]
        end_line = boundaries[i+1]

        if start_line == end_line:
            continue

        chunk_lines = lines[start_line:end_line]
        chunk_content = "\n".join(chunk_lines)

        # If this detected chunk is still huge, split it manually
        if len(chunk_lines) > 200 or len(chunk_content) > MAX_CHARS_PER_CHUNK:
            sub_chunks = split_by_lines(chunk_lines, start_line + 1, rel_path, language)
            chunks.extend(sub_chunks)
        else:
            chunks.append({
                "file_path": rel_path,
                "start_line": start_line + 1,
                "end_line": end_line,
                "content": chunk_content,
                "language": language,
                "symbols": extract_symbols(chunk_content),
            })

    # Filter empty chunks
    return [c for c in chunks if c["content"].strip()]


def chunk_file(filepath: str, repo_path: str) -> List[Dict]:
    """Read a file and split it using the same deterministic chunking rules."""
    return list(iter_chunk_file(filepath, repo_path))


def iter_chunk_file(filepath: str, repo_path: str) -> Iterator[Dict]:
    """Yield source chunks without retaining an entire large file in memory.

    Small files use the established boundary-aware implementation.  Large
    files use a bounded line window with overlap; this keeps line ranges and
    exact source text deterministic while limiting live memory to one chunk.
    The public ``chunk_file`` function still returns a list for compatibility,
    whereas the ingestion pipeline consumes this iterator incrementally.
    """
    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        return
    rel_path = os.path.relpath(filepath, repo_path).replace(os.sep, "/")
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
            if file_size <= STREAMING_FILE_THRESHOLD:
                content = handle.read()
                yield from chunk_file_content(content, rel_path)
                return
            yield from iter_streaming_chunks(handle, rel_path)
    except (OSError, UnicodeError):
        return


def iter_streaming_chunks(handle, file_path: str) -> Iterator[Dict]:
    """Yield fixed, overlapping line windows from an open text file.

    Boundary detection is deliberately skipped for this large-file path: a
    boundary list and ``splitlines`` would scale with the whole file.  The
    same 150-line/12k-character ceilings and 40-line overlap retain enough
    context for retrieval while keeping the producer's allocation bounded.
    An unusually long line is split by characters rather than allowed to
    bypass the payload ceiling.
    """
    _, ext = os.path.splitext(file_path)
    language = ext[1:].lower() if ext else "text"
    window: list[str] = []
    start_line = 1
    line_number = 0
    window_chars = 0

    def emit(lines: list[str], first_line: int) -> Dict | None:
        if not lines:
            return None
        content = "\n".join(lines)
        if not content.strip():
            return None
        return {
            "file_path": file_path,
            "start_line": first_line,
            "end_line": first_line + len(lines) - 1,
            "content": content,
            "language": language,
            "symbols": extract_symbols(content),
        }

    for raw_line in handle:
        line_number += 1
        line = raw_line.rstrip("\r\n")
        # A generated/minified source file can contain a single very large
        # line. Flush ordinary content first, then split that line safely.
        if len(line) > MAX_CHARS_PER_CHUNK:
            if window:
                item = emit(window, start_line)
                if item:
                    yield item
                window = window[-CHUNK_OVERLAP:]
                start_line = line_number - len(window)
                window_chars = sum(len(value) for value in window)
            for offset in range(0, len(line), MAX_CHARS_PER_CHUNK - 1500):
                fragment = line[offset:offset + MAX_CHARS_PER_CHUNK]
                item = emit([fragment], line_number)
                if item:
                    yield item
            # The long line has been emitted in full. Do not emit the prior
            # overlap again at EOF or prepend it to the next normal window.
            window = []
            start_line = line_number + 1
            window_chars = 0
            continue

        candidate_chars = window_chars + len(line) + (1 if window else 0)
        if window and (len(window) >= MAX_LINES_PER_CHUNK or candidate_chars > MAX_CHARS_PER_CHUNK):
            item = emit(window, start_line)
            if item:
                yield item
            window = window[-CHUNK_OVERLAP:]
            start_line = line_number - len(window)
            window_chars = sum(len(value) for value in window)
        window.append(line)
        window_chars += len(line) + (1 if len(window) > 1 else 0)

    item = emit(window, start_line)
    if item:
        yield item

def split_by_lines(lines: List[str], offset_line: int, file_path: str, language: str) -> List[Dict]:
    """Splits lines into manageable chunks with overlap and a char ceiling."""
    chunks = []
    
    i = 0
    while i < len(lines):
        chunk_lines = lines[i:i + MAX_LINES_PER_CHUNK]
        chunk_content = "\n".join(chunk_lines)
        while len(chunk_content) > MAX_CHARS_PER_CHUNK and len(chunk_lines) > 20:
            chunk_lines = chunk_lines[:-10]
            chunk_content = "\n".join(chunk_lines)

        start_line = offset_line + i
        end_line = start_line + len(chunk_lines) - 1
        
        chunks.append({
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "content": chunk_content,
            "language": language,
            "symbols": extract_symbols(chunk_content),
        })
        
        if i + MAX_LINES_PER_CHUNK >= len(lines):
            break
        i += max(1, len(chunk_lines) - CHUNK_OVERLAP)
        
    return chunks


def split_by_characters(content: str, file_path: str, language: str) -> List[Dict]:
    chunks = []
    window = MAX_CHARS_PER_CHUNK
    overlap = 1500
    start_idx = 0
    newline_offsets = [index for index, character in enumerate(content) if character == "\n"]

    while start_idx < len(content):
        end_idx = min(len(content), start_idx + window)
        chunk_text = content[start_idx:end_idx]
        start_line = bisect_left(newline_offsets, start_idx) + 1
        line_count = max(1, len(chunk_text.splitlines()))
        end_line = start_line + line_count - 1

        chunks.append({
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "content": chunk_text,
            "language": language,
            "symbols": extract_symbols(chunk_text),
        })

        if end_idx >= len(content):
            break
        start_idx = max(0, end_idx - overlap)

    return chunks


def is_probably_minified(content: str, lines: List[str]) -> bool:
    if not lines:
        return False

    longest_line = max(len(line) for line in lines)
    average_line = len(content) / max(1, len(lines))
    return longest_line > 2000 or average_line > 400
