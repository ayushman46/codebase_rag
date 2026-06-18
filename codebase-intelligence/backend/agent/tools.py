import os
import subprocess
from git import Repo

REPOS_DIR = "./repos"

def expand_context(repo_name: str, filepath: str) -> str:
    """Fetch the complete contents of a file."""
    full_path = os.path.join(REPOS_DIR, repo_name, filepath)
    if not os.path.exists(full_path):
        return f"Error: File {filepath} not found."
        
    try:
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return f"--- Content of {filepath} ---\n{content}\n--- End of file ---"
    except Exception as e:
        return f"Error reading file: {e}"

def trace_imports(repo_name: str, symbol: str, from_file: str) -> str:
    """Find where a symbol is defined by following import statements."""
    repo_path = os.path.join(REPOS_DIR, repo_name)
    try:
        pattern = f"(class|def|function|interface|type|struct|impl)\\s+{symbol}"
        cmd = ["grep", "-rnE", pattern, repo_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.stdout:
            # Clean up paths to be relative
            output = result.stdout.replace(repo_path + "/", "")
            return f"Symbol '{symbol}' definitions found at:\n{output[:2000]}"
        else:
            return f"Symbol '{symbol}' definition not found."
    except Exception as e:
        return f"Error tracing imports: {e}"

def git_blame(repo_name: str, filepath: str) -> str:
    """Get git commit history for a file."""
    repo_path = os.path.join(REPOS_DIR, repo_name)
    full_path = os.path.join(repo_path, filepath)
    if not os.path.exists(full_path):
        return f"Error: File {filepath} not found."
        
    try:
        repo = Repo(repo_path)
        blame_data = repo.git.log("-p", "-n", "3", filepath) # Get last 3 commits modifying it
        return f"Git history for {filepath}:\n{blame_data[:2000]}"
    except Exception as e:
        return f"Error getting git blame: {e}"

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "expand_context",
            "description": "Fetch the complete contents of a file when a chunk is insufficient",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "relative path from repo root"}
                },
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "trace_imports",
            "description": "Find where a symbol is defined by following import statements",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "from_file": {"type": "string"}
                },
                "required": ["symbol", "from_file"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_blame",
            "description": "Get git commit history for a file to understand why code was written this way",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"}
                },
                "required": ["filepath"]
            }
        }
    }
]