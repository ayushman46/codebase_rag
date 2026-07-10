import os
import shutil
from git import Repo

REPOS_DIR = "./repos_temp"
MAX_FILE_SIZE_BYTES = 1_000_000

IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", 
    "dist", "build", ".next", "vendor", "target", "bin", "obj"
}

SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "composer.lock", "cargo.lock", "bun.lockb"
}

TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".cs", ".swift", ".kt", ".kts",
    ".scala", ".sql", ".sh", ".bash", ".zsh", ".ps1", ".yaml", ".yml", ".json",
    ".toml", ".ini", ".cfg", ".conf", ".env", ".md", ".rst", ".txt", ".html",
    ".css", ".scss", ".sass", ".less", ".xml", ".graphql", ".gql", ".proto",
    ".dockerfile"
}

TEXT_FILENAMES = {
    "dockerfile", "makefile", "readme", "license", "gitignore", "editorconfig"
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
            if file.startswith('.'):
                continue

            abs_path = os.path.join(root, file)
            if should_process_file(abs_path):
                files_list.append(abs_path)

    files_list.sort()
    return files_list

def cleanup_repo(repo_path: str):
    """Deletes the cloned repo to save space after indexing."""
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)


def should_process_file(filepath: str) -> bool:
    filename = os.path.basename(filepath)
    lower_name = filename.lower()

    if lower_name in SKIP_FILENAMES or ".min." in lower_name:
        return False

    if os.path.getsize(filepath) > MAX_FILE_SIZE_BYTES:
        return False

    _, ext = os.path.splitext(lower_name)
    if ext in TEXT_EXTENSIONS or lower_name in TEXT_FILENAMES:
        return is_probably_text_file(filepath)

    return False


def is_probably_text_file(filepath: str) -> bool:
    try:
        with open(filepath, "rb") as f:
            sample = f.read(4096)
    except OSError:
        return False

    if b"\x00" in sample:
        return False

    text_bytes = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)))
    return not bool(sample.translate(None, text_bytes))
