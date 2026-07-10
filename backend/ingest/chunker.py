import os
import re
from typing import List, Dict

MAX_LINES_PER_CHUNK = 150
CHUNK_OVERLAP = 40
MAX_CHARS_PER_CHUNK = 12000

# Basic boundary patterns for common languages
BOUNDARY_REGEX = re.compile(
    r"^(?:def|class|function|func|interface|struct)\s+"
    r"|^(?:public|private|protected)\s+(?:class|interface|enum|.*?\s+\w+\()"
    r"|^(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>",
    re.MULTILINE
)

def chunk_file(filepath: str, repo_path: str) -> List[Dict]:
    """
    Reads a file and splits it into logical chunks using a regex boundary heuristic.
    Falls back to a recursive line splitter for large chunks or non-code files.
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return []
        
    rel_path = os.path.relpath(filepath, repo_path)
    _, ext = os.path.splitext(filepath)
    ext = ext.lower()
    language = ext[1:] if ext else "text"
    
    lines = content.split('\n')
    
    # 1. If file is small and not obviously minified/generated, treat as single chunk
    if len(lines) <= 200 and len(content) <= MAX_CHARS_PER_CHUNK:
        return [{
            "file_path": rel_path,
            "start_line": 1,
            "end_line": len(lines),
            "content": content,
            "language": language
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
    current_chunk_lines = []
    start_idx = 0
    
    for i in range(len(boundaries) - 1):
        start_line = boundaries[i]
        end_line = boundaries[i+1]
        
        if start_line == end_line:
            continue
            
        chunk_lines = lines[start_line:end_line]
        
        # If this detected chunk is still huge, split it manually
        if len(chunk_lines) > 200 or len("\n".join(chunk_lines)) > MAX_CHARS_PER_CHUNK:
            sub_chunks = split_by_lines(chunk_lines, start_line + 1, rel_path, language)
            chunks.extend(sub_chunks)
        else:
            chunks.append({
                "file_path": rel_path,
                "start_line": start_line + 1,
                "end_line": end_line,
                "content": "\n".join(chunk_lines),
                "language": language
            })
            
    # Filter empty chunks
    chunks = [c for c in chunks if c["content"].strip()]
    return chunks

def split_by_lines(lines: List[str], offset_line: int, file_path: str, language: str) -> List[Dict]:
    """Splits lines into manageable chunks with overlap and a char ceiling."""
    chunks = []
    
    i = 0
    while i < len(lines):
        chunk_lines = lines[i:i + MAX_LINES_PER_CHUNK]
        while len("\n".join(chunk_lines)) > MAX_CHARS_PER_CHUNK and len(chunk_lines) > 20:
            chunk_lines = chunk_lines[:-10]

        start_line = offset_line + i
        end_line = start_line + len(chunk_lines) - 1
        
        chunks.append({
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "content": "\n".join(chunk_lines),
            "language": language
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

    while start_idx < len(content):
        end_idx = min(len(content), start_idx + window)
        chunk_text = content[start_idx:end_idx]
        start_line = content.count("\n", 0, start_idx) + 1
        end_line = start_line + chunk_text.count("\n")

        chunks.append({
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "content": chunk_text,
            "language": language
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
