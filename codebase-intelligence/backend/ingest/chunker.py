from dataclasses import dataclass
from typing import List, Optional

@dataclass
class CodeChunk:
    id: str                  # uuid4
    content: str             # full source text of the node
    file_path: str           # relative path from repo root
    language: str
    node_type: str           # "function_definition", "class_declaration" etc
    name: str                # extracted function/class name
    start_line: int
    end_line: int
    parent_class: Optional[str] # if method, name of containing class
    imports: List[str]       # top-of-file imports for this file
    calls: List[str]         # function/method calls inside this chunk
    variables: List[str]     # variables defined in this chunk
    routes: List[str]        # detected API routes (path + method)
    docstring: Optional[str]    # extracted docstring if present
    embedding: Optional[List[float]] = None  # filled in by embedder.py
