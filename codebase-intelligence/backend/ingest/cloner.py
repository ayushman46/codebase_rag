import os
import shutil
from git import Repo

IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", 
    "dist", "build", ".next", "vendor", "target", "bin", "obj"
}

CHUNK_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".ipynb": "python"
}

SINGLE_CHUNK_EXTENSIONS = {
    ".md", ".yml", ".yaml", ".json", ".toml", ".sql", ".txt", ".csv", ".html", ".css", ".sh", ".bash"
}

def clone_repo(github_url: str, repos_dir: str = "./repos") -> str:
    """Clones a GitHub repository and returns the local path."""
    repo_name = github_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    
    local_path = os.path.join(repos_dir, repo_name)
    if os.path.exists(local_path):
        return local_path
    
    os.makedirs(repos_dir, exist_ok=True)
    Repo.clone_from(github_url, local_path)
    return local_path

def get_files_to_index(repo_path: str) -> list[dict]:
    """Walks the repository and returns files to process."""
    files_to_process = []
    
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
        
        for file in files:
            _, ext = os.path.splitext(file)
            ext = ext.lower()
            filepath = os.path.join(root, file)
            
            if ext in CHUNK_EXTENSIONS:
                files_to_process.append({
                    "path": filepath,
                    "type": "chunk",
                    "language": CHUNK_EXTENSIONS[ext]
                })
            elif ext in SINGLE_CHUNK_EXTENSIONS or file == ".env.example":
                files_to_process.append({
                    "path": filepath,
                    "type": "single",
                    "language": "text"
                })
                
    return files_to_process