import json

def get_tools_schema():
    return [
        {
            "type": "function",
            "function": {
                "name": "expand_context",
                "description": "Reads the complete contents of a specific file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "The path to the file."
                        }
                    },
                    "required": ["file_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "trace_symbol",
                "description": "Searches for a specific variable, function, or class name across the repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol_name": {
                            "type": "string",
                            "description": "The exact name of the symbol to trace."
                        }
                    },
                    "required": ["symbol_name"]
                }
            }
        }
    ]

def expand_context(supabase_client, repo_id: str, file_path: str) -> str:
    res = supabase_client.table('chunks').select('content').eq('repo_id', repo_id).eq('file_path', file_path).order('start_line').execute()
    if not res.data:
        return "File not found."
    return "\\n".join(c['content'] for c in res.data)

def trace_symbol(supabase_client, repo_id: str, symbol_name: str) -> str:
    # Use RPC for FTS search
    res = supabase_client.rpc('match_chunks_sparse', {
        'p_repo_id': repo_id,
        'p_query': symbol_name,
        'p_limit': 10
    }).execute()
    
    if not res.data:
        return "No matches found."
        
    matches = []
    for c in res.data:
        if symbol_name in c['content']:
            matches.append(f"{c['file_path']} (L{c['start_line']}-L{c['end_line']}):\\n{c['content']}")
            
    if not matches:
        return "Symbol not found in exact substring matches."
    return "\\n\\n---\\n\\n".join(matches)

def execute_tool(supabase_client, repo_id: str, tool_name: str, args: dict) -> str:
    try:
        if tool_name == "expand_context":
            return expand_context(supabase_client, repo_id, args.get("file_path", ""))
        elif tool_name == "trace_symbol":
            return trace_symbol(supabase_client, repo_id, args.get("symbol_name", ""))
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        return f"Tool error: {str(e)}"
