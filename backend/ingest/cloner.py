import os
import shutil
from git import Repo

REPOS_DIR = "./repos_temp"

IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", 
    "dist", "build", ".next", "vendor", "target", "bin", "obj"
}

def clone_repo_shallow(github_url: str) -> str:
    """Shallow clones a GitHub repo to a temporary directory."""
    repo_name = github_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
        
    local_path = os.path.join(REPOS_DIR, repo_name)
    if os.path.exists(local_path):
        shutil.rmtree(local_path)
        
    os.makedirs(local_path, exist_ok=True)
    Repo.clone_from(github_url, local_path, depth=1)
    return local_path

def get_files_to_process(repo_path: str) -> list[str]:
    """Returns absolute paths of all non-ignored files."""
    files_list = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
        for file in files:
            if not file.startswith('.'):
                files_list.append(os.path.join(root, file))
    return files_list

def cleanup_repo(repo_path: str):
    """Deletes the cloned repo to save space after indexing."""
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
