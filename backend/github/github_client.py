"""Bounded GitHub REST client for reviewed branch and pull request changes."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any
from urllib.parse import quote, urlencode

import httpx

logger = logging.getLogger(__name__)
GITHUB_API_BASE = "https://api.github.com"
GITHUB_OAUTH_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_ACCESS_TOKEN = "https://github.com/login/oauth/access_token"
_REF_INVALID = re.compile(r"[\x00-\x20~^:?*\[\\]|\.\.|@\{")
_PATH_INVALID = re.compile(r"(^/|/$|(^|/)\.\.(/|$)|\x00)")


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns an unexpected response."""


class GitHubAuthRequiredError(GitHubAPIError):
    """Raised when the connected GitHub token is invalid or expired."""


class GitHubConflictError(GitHubAPIError):
    """Raised when a reviewed change is stale or its branch already exists."""


def get_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    return f"{GITHUB_OAUTH_AUTHORIZE}?{urlencode({'client_id': client_id.strip(), 'redirect_uri': redirect_uri.strip(), 'scope': 'public_repo', 'state': state})}"


def _github_headers(access_token: str, *, raw: bool = False) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token.strip()}",
        "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Codebase-Intelligence-App",
    }


def _github_public_headers() -> dict[str, str]:
    """Headers for a read-only request to content already public on GitHub."""
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Codebase-Intelligence-App",
    }


def _api_path(*parts: str) -> str:
    return "/".join(quote(str(part).strip("/"), safe="") for part in parts)


def validate_file_path(file_path: str) -> str:
    value = file_path.strip().replace("\\", "/")
    if not value or len(value) > 500 or _PATH_INVALID.search(value) or any(part in {"", "."} for part in value.split("/")):
        raise GitHubAPIError("File path must be a relative path inside the repository.")
    return value


def validate_branch_name(branch_name: str, *, require_prefix: bool = False) -> str:
    value = branch_name.strip()
    if not value or len(value) > 100 or (require_prefix and not value.startswith("codebase-intel/")):
        raise GitHubAPIError("Branch names must start with codebase-intel/.")
    if _REF_INVALID.search(value) or value.endswith((".", "/")) or value.startswith((".", "/")):
        raise GitHubAPIError("Branch name contains invalid Git characters.")
    return value


async def exchange_code_for_token(client_id: str, client_secret: str, code: str, redirect_uri: str = "") -> dict[str, Any]:
    payload = {"client_id": client_id.strip(), "client_secret": client_secret.strip(), "code": code.strip()}
    if redirect_uri.strip():
        payload["redirect_uri"] = redirect_uri.strip()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(GITHUB_OAUTH_ACCESS_TOKEN, data=payload, headers={"Accept": "application/json", "User-Agent": "Codebase-Intelligence-App"})
    if response.status_code != 200:
        raise GitHubAPIError(f"GitHub OAuth token exchange failed (HTTP {response.status_code})")
    data = response.json()
    if data.get("error") or not str(data.get("access_token") or "").strip():
        raise GitHubAPIError("GitHub OAuth authorization was not completed.")
    return data


def _raise_for_api(response: httpx.Response, action: str) -> None:
    if response.status_code in {401, 403}:
        raise GitHubAuthRequiredError("GitHub credentials expired or do not have the required permission. Reconnect GitHub.")
    if response.status_code == 404:
        raise GitHubAPIError(f"GitHub could not find the requested {action}.")
    if response.status_code >= 400:
        raise GitHubAPIError(f"GitHub could not {action} (HTTP {response.status_code}).")


async def get_authenticated_user(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{GITHUB_API_BASE}/user", headers=_github_headers(access_token))
    _raise_for_api(response, "read the connected account")
    return response.json()


async def get_repo_details(
    access_token: str,
    owner: str,
    repo: str,
    *,
    allow_public_fallback: bool = False,
) -> dict[str, Any]:
    """Read repository metadata, optionally retrying without OAuth.

    Organization OAuth policies can deny an application while the repository
    remains public. The review screen only needs public metadata, so it may
    retry anonymously. Write operations leave this disabled and still require
    the connected GitHub token.
    """
    endpoint = f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(endpoint, headers=_github_headers(access_token))
        if response.status_code in {401, 403} and allow_public_fallback:
            public_response = await client.get(endpoint, headers=_github_public_headers())
            if public_response.status_code < 400:
                return public_response.json()
    _raise_for_api(response, "read the repository")
    return response.json()


async def fork_repo(access_token: str, owner: str, repo: str, *, username: str = "") -> dict[str, Any]:
    """Create a fork and wait briefly for GitHub's asynchronous fork to appear."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}/forks", headers=_github_headers(access_token))
        if response.status_code == 422:
            # GitHub returns 422 when this account already owns the fork. It
            # is safe to reuse it instead of making a retry look like a hard
            # failure or creating a second branch in the upstream repository.
            existing_owner = username.strip()
            if existing_owner:
                existing = await client.get(
                    f"{GITHUB_API_BASE}/repos/{_api_path(existing_owner, repo)}",
                    headers=_github_headers(access_token),
                )
                if existing.status_code == 200:
                    return existing.json()
        if response.status_code not in {200, 202}:
            _raise_for_api(response, "create a repository fork")
        data = response.json()
        fork_owner = str(data.get("owner", {}).get("login") or username).strip()
        fork_name = str(data.get("name") or repo).strip()
        if response.status_code == 202 and fork_owner:
            for delay in (0.5, 1, 2, 3, 5):
                await asyncio.sleep(delay)
                ready = await client.get(f"{GITHUB_API_BASE}/repos/{_api_path(fork_owner, fork_name)}", headers=_github_headers(access_token))
                if ready.status_code == 200:
                    return ready.json()
        return data


async def get_file_at_ref(
    access_token: str,
    owner: str,
    repo: str,
    file_path: str,
    ref: str,
    *,
    metadata_only: bool = False,
    max_content_bytes: int | None = None,
    allow_public_fallback: bool = False,
) -> dict[str, Any]:
    """Return file text and revision, or only metadata for large files."""
    path = validate_file_path(file_path)
    endpoint = f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(endpoint, headers=_github_headers(access_token))
        if response.status_code in {401, 403} and allow_public_fallback:
            public_response = await client.get(endpoint, headers=_github_public_headers())
            if public_response.status_code < 400:
                response = public_response
        _raise_for_api(response, "read the requested file")
        data = response.json() if "json" in response.headers.get("content-type", "").lower() else None
        if not isinstance(data, dict) or data.get("type") != "file":
            raise GitHubAPIError("The selected path is not a file.")
        sha = str(data.get("sha") or "").strip()
        size = int(data.get("size") or 0)
        if metadata_only or (max_content_bytes is not None and size > max_content_bytes):
            content = ""
        elif size <= 1_000_000 and data.get("content"):
            try:
                content = base64.b64decode(str(data["content"]).encode(), validate=False).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as error:
                raise GitHubAPIError("GitHub returned a non-text file.") from error
        else:
            if not sha:
                raise GitHubAPIError("GitHub did not return a file revision.")
            blob_endpoint = f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}/git/blobs/{quote(sha, safe='')}"
            blob = await client.get(blob_endpoint, headers=_github_headers(access_token))
            if blob.status_code in {401, 403} and allow_public_fallback:
                public_blob = await client.get(blob_endpoint, headers=_github_public_headers())
                if public_blob.status_code < 400:
                    blob = public_blob
            _raise_for_api(blob, "read the requested file blob")
            if "json" in blob.headers.get("content-type", "").lower():
                blob_data = blob.json()
                try:
                    content = base64.b64decode(str(blob_data.get("content") or "").encode(), validate=False).decode("utf-8")
                except (ValueError, UnicodeDecodeError) as error:
                    raise GitHubAPIError("GitHub returned a non-text file.") from error
            else:
                content = blob.text
        return {"path": path, "sha": sha, "size": size, "content": content, "ref": ref}


async def create_branch_and_commit_files(
    access_token: str,
    owner: str,
    repo: str,
    base_branch: str,
    branch_name: str,
    files: list[dict[str, Any]],
    commit_message: str,
    *,
    expected_base_sha: str = "",
) -> dict[str, Any]:
    """Create one atomic commit for a bounded set of reviewed files.

    Every blob is created from the complete current file content supplied by
    the review UI. The base ref and each expected file SHA are checked before
    any branch is created, so a stale multi-file review cannot overwrite a
    concurrent GitHub change.
    """
    clean_branch = validate_branch_name(branch_name)
    if not isinstance(files, list) or not files or len(files) > 8:
        raise GitHubAPIError("A pull request must contain between one and eight files.")
    clean_files: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise GitHubAPIError("Each pull request file must be an object.")
        clean_path = validate_file_path(str(item.get("file_path") or ""))
        if clean_path in seen_paths:
            raise GitHubAPIError("A pull request cannot contain the same file twice.")
        new_content = item.get("new_content")
        if not isinstance(new_content, str) or not new_content:
            raise GitHubAPIError("File content cannot be empty.")
        seen_paths.add(clean_path)
        clean_files.append({
            "file_path": clean_path,
            "new_content": new_content,
            "expected_file_sha": str(item.get("expected_file_sha") or "").strip(),
        })
    headers = _github_headers(access_token)
    async with httpx.AsyncClient(timeout=30.0) as client:
        ref_res = await client.get(f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}/git/ref/heads/{quote(base_branch, safe='')}", headers=headers)
        _raise_for_api(ref_res, "read the base branch")
        base_commit_sha = str(ref_res.json().get("object", {}).get("sha") or "")
        if expected_base_sha and base_commit_sha != expected_base_sha:
            raise GitHubConflictError("The base branch changed while you were reviewing this change. Refresh the file and review again.")
        # Check all file preconditions before creating any blob or ref.
        for item in clean_files:
            if item["expected_file_sha"]:
                file_res = await get_file_at_ref(access_token, owner, repo, item["file_path"], base_branch, metadata_only=True)
                if file_res["sha"] != item["expected_file_sha"]:
                    raise GitHubConflictError("A file changed while you were reviewing it. Refresh the files and review again.")
        commit_res = await client.get(f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}/git/commits/{quote(base_commit_sha, safe='')}", headers=headers)
        _raise_for_api(commit_res, "read the base commit")
        base_tree_sha = str(commit_res.json().get("tree", {}).get("sha") or "")
        tree_entries = []
        for item in clean_files:
            blob_res = await client.post(
                f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}/git/blobs",
                headers=headers,
                json={"content": item["new_content"], "encoding": "utf-8"},
            )
            if blob_res.status_code != 201:
                _raise_for_api(blob_res, "create the file blob")
            blob_sha = str(blob_res.json().get("sha") or "")
            if not blob_sha:
                raise GitHubAPIError("GitHub did not return a blob revision.")
            tree_entries.append({"path": item["file_path"], "mode": "100644", "type": "blob", "sha": blob_sha})
        tree_res = await client.post(f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}/git/trees", headers=headers, json={"base_tree": base_tree_sha, "tree": tree_entries})
        if tree_res.status_code != 201:
            _raise_for_api(tree_res, "create the file tree")
        new_tree_sha = str(tree_res.json().get("sha") or "")
        default_message = "Update " + ", ".join(item["file_path"] for item in clean_files[:3])
        if len(clean_files) > 3:
            default_message += f" and {len(clean_files) - 3} more files"
        new_commit_res = await client.post(f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}/git/commits", headers=headers, json={"message": commit_message.strip() or default_message, "tree": new_tree_sha, "parents": [base_commit_sha]})
        if new_commit_res.status_code != 201:
            _raise_for_api(new_commit_res, "create the commit")
        new_commit_sha = str(new_commit_res.json().get("sha") or "")
        new_ref_res = await client.post(f"{GITHUB_API_BASE}/repos/{_api_path(owner, repo)}/git/refs", headers=headers, json={"ref": f"refs/heads/{clean_branch}", "sha": new_commit_sha})
        if new_ref_res.status_code == 422:
            raise GitHubConflictError("That branch already exists. Choose a new branch name to avoid overwriting it.")
        if new_ref_res.status_code != 201:
            _raise_for_api(new_ref_res, "create the branch")
    return {"commit_sha": new_commit_sha, "branch_name": clean_branch, "owner": owner, "repo": repo}


async def create_branch_and_commit(
    access_token: str,
    owner: str,
    repo: str,
    base_branch: str,
    branch_name: str,
    file_path: str,
    new_content: str,
    commit_message: str,
    *,
    expected_base_sha: str = "",
    expected_file_sha: str = "",
) -> dict[str, Any]:
    """Backward-compatible one-file wrapper around the atomic commit path."""
    return await create_branch_and_commit_files(
        access_token,
        owner,
        repo,
        base_branch,
        branch_name,
        [{"file_path": file_path, "new_content": new_content, "expected_file_sha": expected_file_sha}],
        commit_message,
        expected_base_sha=expected_base_sha,
    )


async def open_pull_request(access_token: str, base_owner: str, base_repo: str, head: str, base_branch: str, title: str, body: str) -> dict[str, Any]:
    headers = _github_headers(access_token)
    payload = {"title": title.strip() or "Codebase Intelligence: Proposed Changes", "head": head.strip(), "base": base_branch.strip(), "body": body.strip() or "Automated pull request created via Codebase Intelligence."}
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{GITHUB_API_BASE}/repos/{_api_path(base_owner, base_repo)}/pulls", headers=headers, json=payload)
        if response.status_code == 422:
            data = response.json()
            if any("already exists" in str(error.get("message", "")).lower() for error in data.get("errors", [])):
                list_res = await client.get(f"{GITHUB_API_BASE}/repos/{_api_path(base_owner, base_repo)}/pulls", params={"head": head, "state": "open"}, headers=headers)
                if list_res.status_code == 200 and list_res.json():
                    existing = list_res.json()[0]
                    return {"pr_url": existing["html_url"], "pr_number": existing["number"], "title": existing["title"], "already_existed": True}
            raise GitHubAPIError("GitHub rejected the pull request. Check the branch and repository permissions.")
        if response.status_code != 201:
            _raise_for_api(response, "create the pull request")
        data = response.json()
        return {"pr_url": data["html_url"], "pr_number": data["number"], "title": data["title"], "already_existed": False}
