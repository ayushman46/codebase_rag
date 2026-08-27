import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from git import GitCommandError, Repo

from config import settings

REPOS_DIR = Path("./repos_temp")

IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build",
    ".next", "vendor", "target", "bin", "obj", ".cache", ".tox", "coverage",
}
SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "composer.lock",
    "cargo.lock", "bun.lockb",
}
TEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".cs", ".swift", ".kt", ".kts",
    ".scala", ".sql", ".sh", ".bash", ".zsh", ".ps1", ".yaml", ".yml", ".json",
    ".toml", ".ini", ".cfg", ".conf", ".md", ".rst", ".txt", ".html", ".css",
    ".scss", ".sass", ".less", ".xml", ".graphql", ".gql", ".proto", ".dockerfile",
}
TEXT_FILENAMES = {"dockerfile", "makefile", "readme", "license", "gitignore", "editorconfig"}


class RepositoryValidationError(ValueError):
    pass


class RepositoryCloneError(RuntimeError):
    pass


def normalize_github_url(github_url: str) -> str:
    """Accept only a cloneable HTTPS URL for one public GitHub repository."""
    candidate = github_url.strip()
    parsed = urlparse(candidate)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RepositoryValidationError("Provide a public HTTPS GitHub repository URL.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or any(part in {".", ".."} for part in parts):
        raise RepositoryValidationError("GitHub URL must have the form https://github.com/owner/repository.")
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not owner or not repository:
        raise RepositoryValidationError("GitHub URL must identify a repository.")
    return f"https://github.com/{owner}/{repository}.git"


def repository_name(github_url: str) -> str:
    return normalize_github_url(github_url).rsplit("/", 1)[-1][:-4]


def clone_repo_shallow(github_url: str) -> str:
    """Clone to a unique temporary directory to avoid concurrent-ingestion collisions."""
    canonical_url = normalize_github_url(github_url)
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    local_path = tempfile.mkdtemp(prefix="repo-", dir=REPOS_DIR)
    try:
        Repo.clone_from(canonical_url, local_path, depth=1)
        return local_path
    except GitCommandError as error:
        shutil.rmtree(local_path, ignore_errors=True)
        raise RepositoryCloneError(
            "Repository clone failed. Verify that it is public, accessible, and a valid GitHub repository."
        ) from error
    except Exception:
        shutil.rmtree(local_path, ignore_errors=True)
        raise


def get_files_to_process(repo_path: str) -> list[str]:
    """Return deterministic, bounded, non-binary source/documentation files."""
    files_list: list[str] = []
    total_bytes = 0
    for root, dirs, files in os.walk(repo_path, followlinks=False):
        dirs[:] = [
            directory for directory in dirs
            if directory not in IGNORE_DIRS and not directory.startswith(".")
            and not os.path.islink(os.path.join(root, directory))
        ]
        for file_name in files:
            if file_name.startswith("."):
                continue
            abs_path = os.path.join(root, file_name)
            if os.path.islink(abs_path) or not should_process_file(abs_path):
                continue
            size = os.path.getsize(abs_path)
            total_bytes += size
            if len(files_list) >= settings.max_repository_files or total_bytes > settings.max_repository_bytes:
                raise RepositoryValidationError(
                    "Repository exceeds the configured ingestion limit. Use a smaller repository."
                )
            files_list.append(abs_path)
    return sorted(files_list)


def cleanup_repo(repo_path: str):
    """Delete only the unique clone directory created for this ingestion."""
    resolved_root = REPOS_DIR.resolve()
    resolved_path = Path(repo_path).resolve()
    if resolved_root not in resolved_path.parents:
        raise ValueError("Refusing to clean up a path outside repos_temp.")
    shutil.rmtree(resolved_path, ignore_errors=True)


def should_process_file(filepath: str) -> bool:
    filename = os.path.basename(filepath)
    lower_name = filename.lower()
    if lower_name in SKIP_FILENAMES or ".min." in lower_name:
        return False
    try:
        if os.path.getsize(filepath) > settings.max_file_size_bytes:
            return False
    except OSError:
        return False
    _, ext = os.path.splitext(lower_name)
    return (ext in TEXT_EXTENSIONS or lower_name in TEXT_FILENAMES) and is_probably_text_file(filepath)


def is_probably_text_file(filepath: str) -> bool:
    try:
        with open(filepath, "rb") as file_handle:
            sample = file_handle.read(4096)
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    text_bytes = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)))
    return not bool(sample.translate(None, text_bytes))
