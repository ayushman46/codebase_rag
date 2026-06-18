import os
import uuid
import json
import tree_sitter
from tree_sitter import Language, Parser
from .chunker import CodeChunk
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript
import tree_sitter_java
import tree_sitter_go
import tree_sitter_rust

# tree-sitter setup for each language
LANGUAGES = {
    "python": tree_sitter_python.language(),
    "javascript": tree_sitter_javascript.language(),
    "typescript": tree_sitter_typescript.language_typescript(),
    "java": tree_sitter_java.language(),
    "go": tree_sitter_go.language(),
    "rust": tree_sitter_rust.language(),
}

CHUNK_NODE_TYPES = {
    "python": {
        "function_definition", "class_definition", "decorated_definition"
    },
    "javascript": {
        "function_declaration", "class_declaration", "arrow_function",
        "method_definition", "export_statement"
    },
    "typescript": {
        "function_declaration", "class_declaration", "interface_declaration",
        "type_alias_declaration", "method_definition"
    },
    "java": {
        "method_declaration", "class_declaration", "interface_declaration",
        "constructor_declaration"
    },
    "go": {
        "function_declaration", "method_declaration", "type_declaration"
    },
    "rust": {
        "function_item", "impl_item", "struct_item", "trait_item"
    }
}

def parse_ipynb(content: str, rel_path: str) -> list[CodeChunk]:
    try:
        notebook = json.loads(content)
        chunks = []
        cell_idx = 0
        all_imports = []
        
        # First pass to get imports for context
        for cell in notebook.get("cells", []):
            if cell.get("cell_type") == "code":
                source = "".join(cell.get("source", []))
                if "import " in source or "from " in source:
                    all_imports.append(source)

        for cell in notebook.get("cells", []):
            if cell.get("cell_type") == "code":
                cell_idx += 1
                source = "".join(cell.get("source", []))
                if not source.strip(): continue
                
                chunks.append(CodeChunk(
                    id=str(uuid.uuid4()),
                    content=source,
                    file_path=rel_path,
                    language="python",
                    node_type="notebook_cell",
                    name=f"cell_{cell_idx}",
                    start_line=cell_idx,
                    end_line=cell_idx,
                    parent_class=None,
                    imports=all_imports,
                    calls=[],
                    variables=[],
                    routes=[],
                    docstring=None
                ))
        return chunks
    except Exception as e:
        print(f"Error parsing ipynb {rel_path}: {e}")
        return []

def extract_node_name(node, source_code: bytes) -> str:
    # A simple heuristic to find the name of the function/class
    for child in node.children:
        if child.type in ('identifier', 'name', 'type_identifier', 'property_identifier'):
            return source_code[child.start_byte:child.end_byte].decode('utf8', errors='ignore')
    return "unknown"

def extract_imports(root_node, source_code: bytes, language: str) -> list[str]:
    imports = []
    import_types = {"import_statement", "import_from_statement", "import_declaration", "use_declaration"}
    for child in root_node.children:
        if child.type in import_types:
            imports.append(source_code[child.start_byte:child.end_byte].decode('utf8', errors='ignore'))
    return imports

def extract_docstring(node, source_code: bytes, language: str) -> str | None:
    if language == "python" and node.children:
        block = node.children[-1]
        if block.type == "block" and block.children:
            expr_stmt = block.children[0]
            if expr_stmt.type == "expression_statement" and expr_stmt.children:
                string_node = expr_stmt.children[0]
                if string_node.type == "string":
                    return source_code[string_node.start_byte:string_node.end_byte].decode('utf8', errors='ignore')
    return None

def extract_calls(node, source_code: bytes) -> list[str]:
    calls = []
    def find_calls(n):
        if n.type in ("call", "call_expression"):
            for child in n.children:
                if child.type in ("identifier", "attribute", "member_expression"):
                    calls.append(source_code[child.start_byte:child.end_byte].decode('utf8', errors='ignore'))
                    break
        for child in n.children:
            find_calls(child)
    find_calls(node)
    return list(set(calls))

def extract_variables(node, source_code: bytes) -> list[str]:
    vars = []
    def find_vars(n):
        if n.type in ("assignment", "variable_declarator"):
            for child in n.children:
                if child.type in ("identifier", "variable_name"):
                    vars.append(source_code[child.start_byte:child.end_byte].decode('utf8', errors='ignore'))
                    break
        for child in n.children:
            find_vars(child)
    find_vars(node)
    return list(set(vars))

def parse_file(filepath: str, repo_path: str, language: str, file_type: str) -> list[CodeChunk]:
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    rel_path = os.path.relpath(filepath, repo_path)
    
    if filepath.endswith(".ipynb"):
        return parse_ipynb(content, rel_path)

    if file_type == "single" or len(content.splitlines()) > 1000 or language not in LANGUAGES:
        lines = content.splitlines()[:1000]
        truncated_content = "\n".join(lines)
        return [CodeChunk(
            id=str(uuid.uuid4()),
            content=truncated_content,
            file_path=rel_path,
            language=language if language in LANGUAGES else "text",
            node_type="file",
            name=os.path.basename(rel_path),
            start_line=1,
            end_line=len(lines),
            parent_class=None,
            imports=[],
            calls=[],
            variables=[],
            routes=[],
            docstring=None
        )]

    source_bytes = content.encode('utf8', errors='ignore')
    parser = Parser(LANGUAGES[language])
    tree = parser.parse(source_bytes)
    
    imports = extract_imports(tree.root_node, source_bytes, language)
    chunks = []
    target_types = CHUNK_NODE_TYPES.get(language, set())
    
    def traverse(node, current_class=None):
        if node.type in target_types:
            name = extract_node_name(node, source_bytes)
            docstring = extract_docstring(node, source_bytes, language)
            
            is_class = "class" in node.type or "struct" in node.type or "interface" in node.type
            new_class_context = name if is_class else current_class
            
            calls = extract_calls(node, source_bytes)
            variables = extract_variables(node, source_bytes)

            chunks.append(CodeChunk(
                id=str(uuid.uuid4()),
                content=source_bytes[node.start_byte:node.end_byte].decode('utf8', errors='ignore'),
                file_path=rel_path,
                language=language,
                node_type=node.type,
                name=name,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_class=current_class,
                imports=imports,
                calls=calls,
                variables=variables,
                routes=[],
                docstring=docstring
            ))
            for child in node.children:
                traverse(child, new_class_context)
        else:
            for child in node.children:
                traverse(child, current_class)

    traverse(tree.root_node)
    
    if not chunks:
        lines = content.splitlines()[:500]
        chunks.append(CodeChunk(
            id=str(uuid.uuid4()),
            content="\n".join(lines),
            file_path=rel_path,
            language=language,
            node_type="file",
            name=os.path.basename(rel_path),
            start_line=1,
            end_line=len(lines),
            parent_class=None,
            imports=imports,
            calls=[],
            variables=[],
            routes=[],
            docstring=None
        ))
    return chunks