"""Small, conservative source dependency extraction for impact-oriented search.

This is intentionally not an AST or build-system replacement. It records only
imports/includes that can be resolved to a file present in the same checkout;
external packages and ambiguous aliases are left out rather than presented as
facts.
"""

import hashlib
import os
import posixpath
import re
from bisect import bisect_left

IMPORT_PATTERNS = (
    re.compile(r"^\s*from\s+([.A-Za-z_][\w.]*(?:/[^\s]+)?)(?:\s+import\s+.+)?", re.MULTILINE),
    re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)", re.MULTILINE),
    re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    re.compile(r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE),
    re.compile(r"^\s*(?:#\s*include|include)\s*[<\"]([^>\"]+)[>\"]", re.MULTILINE),
    re.compile(r"^\s*use\s+(?:crate::)?([A-Za-z_][\w:]*)", re.MULTILINE),
)
SOURCE_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt", ".kts", ".scala")


def _normalise(path: str) -> str:
    return path.replace(os.sep, "/").lstrip("./")


def _resolve_import(raw_target: str, source_path: str, known_files: set[str]) -> str | None:
    target = raw_target.strip().split("?", 1)[0].split("#", 1)[0]
    if not target or target.startswith(("http://", "https://", "@")):
        return None
    source_dir = posixpath.dirname(source_path)
    candidates: list[str] = []
    if target.startswith("."):
        dot_count = len(target) - len(target.lstrip("."))
        relative_target = target[dot_count:].lstrip("/")
        base_dir = source_dir
        for _ in range(max(0, dot_count - 1)):
            base_dir = posixpath.dirname(base_dir)
        base = posixpath.normpath(posixpath.join(base_dir, relative_target))
    elif "::" in target:
        base = target.split("::", 1)[0].replace(".", "/")
    elif "." in target and "/" not in target:
        base = target.replace(".", "/")
    elif "/" in target:
        base = posixpath.normpath(target)
    else:
        return None
    base = _normalise(base)
    candidates.append(base)
    if not posixpath.splitext(base)[1]:
        candidates.extend(base + extension for extension in SOURCE_EXTENSIONS)
        candidates.extend(posixpath.join(base, "index" + extension) for extension in SOURCE_EXTENSIONS)
    for candidate in candidates:
        if candidate in known_files:
            return candidate
    return None


def _scan_dependency_edges(content: str, source_path: str, known_files: set[str], edges: list[dict], seen: set[tuple[str, str, int]]) -> None:
    """Append resolved imports for one already-read source file."""
    newline_offsets = [index for index, character in enumerate(content) if character == "\n"]
    for pattern in IMPORT_PATTERNS:
        for match in pattern.finditer(content):
            target_path = _resolve_import(match.group(1), source_path, known_files)
            if not target_path or target_path == source_path:
                continue
            line_number = bisect_left(newline_offsets, match.start()) + 1
            key = (source_path, target_path, line_number)
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                "source_file": source_path,
                "target_file": target_path,
                "import_name": match.group(1),
                "line_number": line_number,
            })


def build_manifest_and_dependency_manifest(files: list[str], repo_path: str) -> tuple[dict[str, dict[str, int | str]], list[dict]]:
    """Hash files and resolve local imports in one bounded read pass."""
    known_files = {_normalise(os.path.relpath(path, repo_path)) for path in files}
    manifest: dict[str, dict[str, int | str]] = {}
    edges: list[dict] = []
    seen: set[tuple[str, str, int]] = set()
    for file_path in files:
        source_path = _normalise(os.path.relpath(file_path, repo_path))
        try:
            with open(file_path, "rb") as handle:
                raw_content = handle.read()
        except OSError:
            continue
        manifest[source_path] = {"content_hash": hashlib.sha256(raw_content).hexdigest(), "byte_size": len(raw_content)}
        _scan_dependency_edges(raw_content.decode("utf-8", errors="ignore"), source_path, known_files, edges, seen)
    return manifest, sorted(edges, key=lambda edge: (edge["source_file"], edge["line_number"], edge["target_file"]))


def build_dependency_manifest(files: list[str], repo_path: str) -> list[dict]:
    """Build a dependency graph for callers that do not need file hashes."""
    _manifest, dependencies = build_manifest_and_dependency_manifest(files, repo_path)
    return dependencies
