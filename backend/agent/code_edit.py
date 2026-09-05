"""Validation and authorization primitives for the code-editing workflow.

The model never receives permission to write to GitHub. It can only propose a
small list of exact text replacements. The replacements are checked against
the retrieved evidence here and applied to the current GitHub revision in the
browser after the user reviews the result. A separate signed ticket gates the
file and PR endpoints so ordinary chat modes cannot invoke the write flow.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from pathlib import PurePosixPath
from typing import Any


class CodeEditValidationError(ValueError):
    """Raised when a model proposal is not safe to present as an editable patch."""


class EditingAuthorizationError(ValueError):
    """Raised when a file or PR request lacks a valid editing-mode ticket."""


_CODE_EDIT_TAG = re.compile(r"<code_edit>\s*(.*?)\s*</code_edit>", re.IGNORECASE | re.DOTALL)
_CONTEXT_FILE = re.compile(r"(?m)^File:\s*([^\s]+)\s+\(L\d+-L\d+\)")
_MAX_CHANGES = 20
_MAX_FILES = 8
_MAX_TOTAL_CHANGES = 40
_MAX_SUMMARY_LENGTH = 800
_MAX_REASON_LENGTH = 500
_MAX_VALIDATION_ITEMS = 12
_MAX_VALIDATION_LENGTH = 300


def _normalise_path(value: str) -> str:
    candidate = str(value or "").strip().replace("\\", "/")
    if not candidate or candidate.startswith("/") or "\x00" in candidate:
        raise CodeEditValidationError("The proposed file path is invalid.")
    path = PurePosixPath(candidate)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise CodeEditValidationError("The proposed file path is invalid.")
    return str(path)


def _extract_object(raw: str) -> dict[str, Any]:
    """Extract one JSON object without trusting surrounding model prose."""
    candidate = str(raw or "").strip()
    tagged = _CODE_EDIT_TAG.search(candidate)
    if tagged:
        candidate = tagged.group(1).strip()

    decoder = json.JSONDecoder()
    # Models occasionally wrap the object in a Markdown fence or one sentence
    # of explanation. Try each opening brace, but only accept an object that
    # subsequently passes the strict schema checks below.
    for offset, character in enumerate(candidate):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(candidate[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise CodeEditValidationError("The model did not return a valid structured code edit.")


def parse_code_edit(
    raw: str,
    *,
    allowed_files: set[str] | list[str],
    source_context: str,
    max_change_bytes: int,
) -> dict[str, Any]:
    """Validate a minimal exact-match patch against retrieved source evidence.

    The output deliberately uses search/replace pairs rather than a complete
    replacement file. This prevents a short retrieved chunk from truncating a
    larger file and lets the UI apply the proposal to the latest GitHub blob.
    """
    payload = _extract_object(raw)
    normalised_allowed = {_normalise_path(path) for path in allowed_files}
    context = str(source_context or "")

    # The legacy one-file shape remains accepted for compatibility. New issue
    # fixes use ``files`` so a bounded multi-file change can be reviewed and
    # committed atomically rather than silently producing a partial fix.
    raw_files = payload.get("files")
    if raw_files is None:
        raw_files = [{
            "file_path": payload.get("file_path"),
            "summary": payload.get("summary"),
            "changes": payload.get("changes"),
            "validation": payload.get("validation"),
        }]
    if not isinstance(raw_files, list) or not raw_files or len(raw_files) > _MAX_FILES:
        raise CodeEditValidationError(f"The code edit must contain between one and {_MAX_FILES} files.")

    files: list[dict[str, Any]] = []
    total_bytes = 0
    total_changes = 0
    for raw_file in raw_files:
        if not isinstance(raw_file, dict):
            raise CodeEditValidationError("Every edited file must be an object.")
        try:
            file_path = _normalise_path(raw_file.get("file_path"))
        except (AttributeError, TypeError) as error:
            raise CodeEditValidationError("Each edited file must name an indexed file.") from error
        if file_path not in normalised_allowed:
            suffix_matches = [path for path in normalised_allowed if path.endswith(f"/{file_path}")]
            if len(suffix_matches) == 1:
                file_path = suffix_matches[0]
        if file_path not in normalised_allowed:
            raise CodeEditValidationError("A proposed file was not part of the targeted indexed evidence.")
        if any(item["file_path"] == file_path for item in files):
            raise CodeEditValidationError("The code edit lists the same file more than once.")

        summary = str(raw_file.get("summary") or payload.get("summary") or "").strip()
        if not summary or len(summary) > _MAX_SUMMARY_LENGTH:
            raise CodeEditValidationError("Each edited file needs a short summary.")
        raw_changes = raw_file.get("changes")
        if not isinstance(raw_changes, list) or not raw_changes or len(raw_changes) > _MAX_CHANGES:
            raise CodeEditValidationError(f"Each edited file must contain between one and {_MAX_CHANGES} changes.")

        target_context = _file_context(context, file_path)
        if not target_context:
            raise CodeEditValidationError("A selected file has no retrieved source evidence.")
        changes: list[dict[str, str]] = []
        seen_old: set[str] = set()
        for item in raw_changes:
            if not isinstance(item, dict):
                raise CodeEditValidationError("Every code edit change must be an object.")
            old = item.get("old")
            new = item.get("new")
            if not isinstance(old, str) or not old.strip() or not isinstance(new, str):
                raise CodeEditValidationError("Each code edit needs non-empty old text and string replacement text.")
            if "\x00" in old or "\x00" in new or old in seen_old:
                raise CodeEditValidationError("The code edit contains invalid or duplicate search text.")
            # Exact source grounding: the model cannot invent a search hunk
            # that was not present in this file's bounded context.
            if old not in target_context:
                raise CodeEditValidationError("A proposed search hunk was not present in the indexed evidence.")
            if old == new:
                raise CodeEditValidationError("A code edit must change the matched text.")
            if len(old.encode("utf-8")) > max_change_bytes or len(new.encode("utf-8")) > max_change_bytes:
                raise CodeEditValidationError("A single code edit is too large to review safely.")
            total_bytes += len(new.encode("utf-8"))
            total_changes += 1
            if total_changes > _MAX_TOTAL_CHANGES:
                raise CodeEditValidationError(f"The code edit must contain at most {_MAX_TOTAL_CHANGES} changes.")
            reason = str(item.get("reason") or "").strip()[:_MAX_REASON_LENGTH]
            changes.append({"old": old, "new": new, "reason": reason})
            seen_old.add(old)
        files.append({
            "file_path": file_path,
            "summary": summary,
            "changes": changes,
            "validation": _validation_steps(raw_file.get("validation") or payload.get("validation") or []),
        })
    if total_bytes > max(1, int(max_change_bytes)):
        raise CodeEditValidationError("The total proposed change is too large to review safely.")

    if len(files) == 1:
        # Preserve the response contract consumed by older clients/tests while
        # exposing ``files`` for clients that understand multi-file reviews.
        return {**files[0], "files": files}
    return {
        "files": files,
        "file_path": files[0]["file_path"],
        "summary": f"{len(files)} files: " + "; ".join(file["summary"] for file in files)[:_MAX_SUMMARY_LENGTH],
        "changes": [],
        "validation": [item for file in files for item in file["validation"]][:_MAX_VALIDATION_ITEMS],
    }


def _validation_steps(raw_validation: Any) -> list[str]:
    if not isinstance(raw_validation, list):
        raise CodeEditValidationError("Validation steps must be a list.")
    return [
        str(item).strip()[:_MAX_VALIDATION_LENGTH]
        for item in raw_validation[:_MAX_VALIDATION_ITEMS]
        if str(item).strip()
    ]


def edit_file_paths(edit: dict[str, Any]) -> list[str]:
    """Return normalized target paths from either edit response shape."""
    raw_files = edit.get("files") if isinstance(edit, dict) else None
    if isinstance(raw_files, list):
        paths = [str(item.get("file_path") or "").strip() for item in raw_files if isinstance(item, dict)]
    else:
        paths = [str(edit.get("file_path") or "").strip()] if isinstance(edit, dict) else []
    result: list[str] = []
    for path in paths:
        if not path:
            continue
        normalized = _normalise_path(path)
        if normalized not in result:
            result.append(normalized)
    return result


def context_file_paths(source_context: str) -> set[str]:
    """Extract only the file labels emitted by the server's context builder."""
    return {match.group(1).strip() for match in _CONTEXT_FILE.finditer(str(source_context or ""))}


def _file_context(source_context: str, file_path: str) -> str:
    """Return only the retrieved source sections belonging to one file.

    Exact text grounding must be file-scoped. A common hunk can legitimately
    occur in several files, and checking the whole multi-file prompt would let
    the model name one file while borrowing evidence from another. The
    no-header fallback keeps this helper compatible with direct unit callers;
    production context is always emitted with ``File:`` headers.
    """
    context = str(source_context or "")
    headers = list(_CONTEXT_FILE.finditer(context))
    if not headers:
        return context
    sections: list[str] = []
    for index, header in enumerate(headers):
        try:
            path = _normalise_path(header.group(1).strip())
        except CodeEditValidationError:
            continue
        if path != file_path:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(context)
        sections.append(context[header.end():end])
    return "\n".join(sections)


def format_code_edit_response(edit: dict[str, Any]) -> str:
    """Render a safe, concise explanation while keeping patch data structured."""
    files = edit.get("files") if isinstance(edit.get("files"), list) else [edit]
    lines = [
        "## Proposed change",
        "",
        f"**{len(files)} file{'s' if len(files) != 1 else ''}**: "
        + "; ".join(f"{file['file_path']} — {file['summary']}" for file in files),
        "",
        "The generated patch contains exact replacements from the indexed evidence. Review every current file before creating a pull request.",
        "",
        "## Planned edits",
    ]
    index = 1
    for file in files:
        for change in file.get("changes") or []:
            reason = f" — {change['reason']}" if change.get("reason") else ""
            lines.append(f"{index}. In **{file['file_path']}**, replace the matched source text{reason}.")
            index += 1
    validation = [item for file in files for item in file.get("validation", [])]
    if validation:
        lines.extend(["", "## Validation to run"])
        lines.extend(f"- {item}" for item in validation[:_MAX_VALIDATION_ITEMS])
    return "\n".join(lines)


def format_invalid_code_edit_response() -> str:
    """Do not expose malformed model output or present an unsafe push action."""
    return (
        "## Code review\n\n"
        "I could not produce a safe patch from the indexed evidence. Ask for one specific file and a focused change; "
        "the editor will only appear when every proposed replacement exactly matches the retrieved source."
    )


def _ticket_key(secret: str) -> bytes:
    value = str(secret or "").strip()
    if len(value) < 16:
        raise EditingAuthorizationError("Code editing is not configured on the server.")
    return value.encode("utf-8")


def create_edit_ticket(secret: str, *, user_id: str, repo_name: str, file_path: str | list[str], ttl_seconds: int) -> str:
    """Create an opaque, short-lived ticket scoped to one user/repository/file set."""
    key = _ticket_key(secret)
    paths = edit_file_paths({"files": [{"file_path": path} for path in file_path]}) if isinstance(file_path, list) else edit_file_paths({"file_path": file_path})
    if not paths:
        raise EditingAuthorizationError("Code editing needs at least one target file.")
    payload = {
        "v": 1,
        "u": str(user_id),
        "r": str(repo_name),
        "p": paths[0] if len(paths) == 1 else paths,
        "e": int(time.time()) + max(60, int(ttl_seconds)),
        "n": hashlib.sha256(f"{user_id}:{repo_name}:{file_path}:{time.time_ns()}".encode()).hexdigest()[:16],
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    return f"v1.{body}.{signature}"


def verify_edit_ticket(secret: str, ticket: str, *, user_id: str, repo_name: str, file_path: str) -> dict[str, Any]:
    """Verify signature, expiry, and exact scope using constant-time comparison."""
    key = _ticket_key(secret)
    parts = str(ticket or "").split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise EditingAuthorizationError("Open this change from Code editing mode before continuing.")
    body, signature = parts[1], parts[2]
    expected = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise EditingAuthorizationError("The editing session is invalid. Start the review again.")
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise EditingAuthorizationError("The editing session is invalid. Start the review again.") from error
    try:
        if int(payload.get("e", 0)) <= int(time.time()):
            raise EditingAuthorizationError("The editing session expired. Generate the change again.")
        if str(payload.get("u")) != str(user_id) or str(payload.get("r")) != str(repo_name):
            raise EditingAuthorizationError("The editing session is not valid for this repository.")
        raw_paths = payload.get("p")
        if isinstance(raw_paths, list):
            ticket_paths = edit_file_paths({"files": [{"file_path": path} for path in raw_paths]})
        else:
            ticket_paths = edit_file_paths({"file_path": raw_paths})
        requested_path = _normalise_path(file_path)
        if requested_path not in ticket_paths:
            raise EditingAuthorizationError("The editing session is not valid for this file.")
    except (AttributeError, TypeError, ValueError) as error:
        raise EditingAuthorizationError("The editing session is invalid. Start the review again.") from error
    return payload
