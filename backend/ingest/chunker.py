import os
import re
from typing import List, Dict

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
    
    # 1. If file is small, treat as single chunk
    if len(lines) <= 200:
        return [{
            "file_path": rel_path,
            "start_line": 1,
            "end_line": len(lines),
            "content": content,
            "language": language
        }]
        
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
        if len(chunk_lines) > 200:
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
    """Splits lines into chunks of ~150 lines with 40-line overlap."""
    CHUNK_SIZE = 150
    OVERLAP = 40
    chunks = []
    
    i = 0
    while i < len(lines):
        chunk_lines = lines[i:i + CHUNK_SIZE]
        start_line = offset_line + i
        end_line = start_line + len(chunk_lines) - 1
        
        chunks.append({
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "content": "\n".join(chunk_lines),
            "language": language
        })
        
        if i + CHUNK_SIZE >= len(lines):
            break
        i += (CHUNK_SIZE - OVERLAP)
        
    return chunks
