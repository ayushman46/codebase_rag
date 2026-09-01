"""Account-level indexed-source quota helpers.

Supabase owns identity; these helpers only read the verified user id and
account entitlements from Turso. Quota is based on the bytes of eligible files
that are currently indexed, not on temporary clone size or excluded files.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from config import settings


class RepositoryQuotaExceededError(ValueError):
    """Raised when a repository would exceed the user's current plan quota."""


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return fallback


def format_bytes(value: int) -> str:
    """Format bytes for concise user-facing account information."""
    value = _as_int(value)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f} GB"
    return f"{value / 1_000_000:.0f} MB"


async def get_account_usage(store, user_id: str) -> dict[str, Any]:
    """Return plan, quota, and current indexed bytes for one account."""
    entitlement = await store.fetch_one(
        "SELECT plan, quota_bytes, status, updated_at FROM account_entitlements WHERE user_id = ?",
        [user_id],
    )
    plan = str((entitlement or {}).get("plan") or "explorer")
    status = str((entitlement or {}).get("status") or "active")
    team_active = plan == "team" and status == "active"
    if team_active:
        # Standard Checkout is a one-time payment. Treat the verified payment
        # timestamp as the start of a 30-day entitlement so a stale payment
        # cannot grant the higher quota indefinitely.
        try:
            paid_at = datetime.fromisoformat(str(entitlement.get("updated_at")).replace("Z", "+00:00"))
            team_active = datetime.now(UTC) < paid_at + timedelta(days=max(1, settings.team_plan_duration_days))
        except (TypeError, ValueError):
            team_active = False
    if team_active:
        quota_bytes = _as_int((entitlement or {}).get("quota_bytes"), settings.team_codebase_bytes)
    else:
        if plan == "team" and status == "active":
            status = "expired"
        plan = "explorer"
        quota_bytes = settings.free_codebase_bytes
    usage = await store.fetch_one(
        "SELECT COALESCE(SUM(rf.byte_size), 0) AS used_bytes "
        "FROM repo_files rf JOIN repos r ON r.id = rf.repo_id WHERE r.user_id = ?",
        [user_id],
    )
    used_bytes = _as_int((usage or {}).get("used_bytes"))
    return {
        "plan": plan,
        "status": status,
        "used_bytes": used_bytes,
        "quota_bytes": quota_bytes,
        "remaining_bytes": max(0, quota_bytes - used_bytes),
        "used_label": format_bytes(used_bytes),
        "quota_label": format_bytes(quota_bytes),
        "remaining_label": format_bytes(max(0, quota_bytes - used_bytes)),
    }


async def ensure_repository_usage_capacity(
    store,
    user_id: str,
    requested_bytes: int,
    replacing_repo_id: str | None = None,
) -> None:
    """Fail before publishing an index that would exceed the plan quota.

    During re-indexing the previous version of the same repository is removed
    from the calculation, so unchanged files do not count twice.
    """
    usage = await get_account_usage(store, user_id)
    current_repo_bytes = 0
    if replacing_repo_id:
        current = await store.fetch_one(
            "SELECT COALESCE(SUM(byte_size), 0) AS used_bytes FROM repo_files WHERE repo_id = ?",
            [replacing_repo_id],
        )
        current_repo_bytes = _as_int((current or {}).get("used_bytes"))
    committed_bytes = max(0, usage["used_bytes"] - current_repo_bytes)
    requested_bytes = _as_int(requested_bytes)
    projected_bytes = committed_bytes + requested_bytes
    if projected_bytes <= usage["quota_bytes"]:
        return
    upgrade_message = (
        f"Your Explorer workspace includes up to {format_bytes(usage['quota_bytes'])} of indexed source. "
        "This repository would exceed that limit. Choose the Team plan for ₹300/month to continue."
    )
    if usage["plan"] == "team":
        upgrade_message = (
            f"Your Team workspace includes up to {format_bytes(usage['quota_bytes'])} of indexed source. "
            "Remove a repository or contact support for a higher limit."
        )
    raise RepositoryQuotaExceededError(upgrade_message)
