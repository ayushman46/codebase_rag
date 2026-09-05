"""Database boundaries for Supabase Auth and Turso application data.

Supabase remains the identity provider. Repository records, indexing jobs,
source chunks, vector embeddings, metadata, and conversations live in Turso.
"""

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

import libsql
from supabase import create_client

from config import settings

logger = logging.getLogger(__name__)


class DatabaseConfigurationError(RuntimeError):
    """Raised when a required database service is unavailable or unconfigured."""


class DatabaseUnavailableError(DatabaseConfigurationError):
    """Raised after a bounded retry confirms the Turso connection is stale."""


class DeferredSupabaseClient:
    def __init__(self, message: str):
        self.message = message

    def __getattr__(self, _name):
        raise DatabaseConfigurationError(self.message)


def get_supabase_client():
    """Return the public-key client used exclusively to validate user sessions."""
    url = settings.supabase_url.strip()
    key = settings.supabase_key.strip()
    message = (
        "Supabase authentication is not configured. Set SUPABASE_URL and SUPABASE_KEY "
        "in the backend environment, then restart the service."
    )
    if not url or not key or "your_supabase" in url or "your_supabase" in key:
        return DeferredSupabaseClient(message)
    try:
        return create_client(url, key)
    except Exception:
        logger.exception("Could not initialize the Supabase authentication client")
        return DeferredSupabaseClient(message)


supabase = get_supabase_client()

JSON_COLUMNS = {"symbols", "citations", "tool_calls", "tech_stack", "file_summaries", "excluded_reasons", "excluded_paths"}


@dataclass(frozen=True)
class Statement:
    sql: str
    args: list[Any]


@dataclass
class QueryResult:
    rows: list[dict[str, Any]]
    rows_affected: int


class TursoStore:
    """Small asynchronous, parameterized data-access layer for Turso.

    This is a server-only client. Ownership is enforced by including the
    authenticated user id in each repository and conversation query.
    """

    def __init__(self, url: str, auth_token: str):
        self._database_url = url
        self._auth_token = auth_token
        self._client = self._connect_sync()
        self._lock = asyncio.Lock()

    def _connect_sync(self):
        return libsql.connect(
            database=self._database_url,
            auth_token=self._auth_token,
            _check_same_thread=False,
        )

    @staticmethod
    def _row_to_dict(columns: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
        value = dict(zip(columns, row, strict=True))
        for column in JSON_COLUMNS:
            raw = value.get(column)
            if isinstance(raw, str):
                try:
                    value[column] = json.loads(raw)
                except json.JSONDecodeError:
                    value[column] = [] if column in {"symbols", "citations", "tool_calls", "tech_stack", "excluded_paths"} else {}
        return value

    async def execute(self, sql: str, args: list[Any] | tuple[Any, ...] | None = None):
        """Execute one parameterized statement.

        Read statements are safe to retry when a remote database connection has
        a short-lived failure. Writes intentionally are *not* retried here: a
        connection can fail after a successful commit, and retrying a generic
        write can create a duplicate side effect. Idempotent write paths use a
        caller-supplied primary key or an upsert instead.
        """
        arguments = list(args or [])
        attempts = 3 if self._is_read_statement(sql) else 1
        for attempt in range(attempts):
            try:
                async with self._lock:
                    return await asyncio.to_thread(self._execute_sync, sql, arguments)
            except Exception as error:
                if not self._is_transient_error(error):
                    raise
                # Hrana streams can expire while a process remains alive. A
                # retry against the same client repeats the dead stream, so
                # replace it before retrying. Writes are deliberately not
                # retried (they may have committed before the transport
                # failed), but refreshing here lets the next request recover.
                try:
                    await self._refresh_connection()
                except Exception as reconnect_error:
                    raise DatabaseUnavailableError(
                        "Turso connection was lost and could not be restored. Please retry shortly."
                    ) from reconnect_error
                if attempt == attempts - 1:
                    raise DatabaseUnavailableError(
                        "Turso connection was lost while processing the request. Please retry shortly."
                    ) from error
                await asyncio.sleep(self._retry_delay(attempt))

        raise RuntimeError("Turso retry loop ended unexpectedly.")  # pragma: no cover

    @staticmethod
    def _is_read_statement(sql: str) -> bool:
        normalized = sql.lstrip().upper()
        if normalized.startswith(("SELECT", "EXPLAIN", "PRAGMA")):
            return True
        # The retrieval planner uses a read-only window-function CTE. Treat
        # WITH statements as reads unless they contain a mutating verb, so the
        # optimization above also applies to that single batched lookup.
        return normalized.startswith("WITH") and not re.search(
            r"\b(?:INSERT|UPDATE|DELETE|REPLACE)\b", normalized
        )

    @staticmethod
    def _is_transient_error(error: Exception) -> bool:
        message = str(error).lower()
        return any(marker in message for marker in (
            "database is locked", "database is busy", "busy", "timeout", "timed out",
            "connection", "temporarily unavailable", "http 429", "http 500", "http 502",
            "http 503", "http 504", "stream not found", "broken pipe", "connection reset",
        ))

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        return min(1.5, 0.15 * (2 ** attempt)) + random.uniform(0, 0.1)

    def _execute_sync(self, sql: str, args: list[Any]) -> QueryResult:
        cursor = self._client.execute(sql, args)
        columns = [item[0] for item in cursor.description] if cursor.description else []
        rows = [self._row_to_dict(columns, row) for row in cursor.fetchall()] if columns else []
        affected = cursor.rowcount if cursor.rowcount >= 0 else len(rows)
        # Read statements do not open a write transaction. Avoiding an
        # unnecessary remote COMMIT removes one round trip from every SELECT
        # while leaving DDL and mutations fully durable.
        if not self._is_read_statement(sql):
            self._client.commit()
        return QueryResult(rows=rows, rows_affected=affected)

    async def _refresh_connection(self) -> None:
        """Close a dead Hrana client and establish a fresh stream safely."""
        async with self._lock:
            old_client = self._client
            try:
                await asyncio.to_thread(old_client.close)
            except Exception:
                logger.debug("Ignoring failure while closing stale Turso client", exc_info=True)
            self._client = await asyncio.to_thread(self._connect_sync)

    async def batch(self, statements: Iterable[Statement]) -> None:
        """Run an idempotent batch with bounded recovery for transient outages.

        This method is intentionally used only for chunk insertion. Each chunk
        carries a UUID and uses ``INSERT OR IGNORE``, so a retry after an
        ambiguous network failure cannot duplicate a chunk.
        """
        statements = list(statements)
        if not statements:
            return
        grouped: dict[str, list[list[Any]]] = {}
        for statement in statements:
            grouped.setdefault(statement.sql, []).append(statement.args)
        for attempt in range(3):
            try:
                async with self._lock:
                    await asyncio.to_thread(self._batch_sync, grouped)
                return
            except Exception as error:
                if not self._is_transient_error(error):
                    raise
                try:
                    await self._refresh_connection()
                except Exception as reconnect_error:
                    raise DatabaseUnavailableError(
                        "Turso connection was lost and could not be restored. Please retry shortly."
                    ) from reconnect_error
                if attempt == 2:
                    raise DatabaseUnavailableError(
                        "Turso connection was lost while writing. Please retry shortly."
                    ) from error
                await asyncio.sleep(self._retry_delay(attempt))

    def _batch_sync(self, grouped: dict[str, list[list[Any]]]) -> None:
        for sql, argument_sets in grouped.items():
            self._client.executemany(sql, argument_sets)
        self._client.commit()

    async def fetch_all(self, sql: str, args: list[Any] | tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        return (await self.execute(sql, args)).rows

    async def fetch_one(self, sql: str, args: list[Any] | tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        rows = await self.fetch_all(sql, args)
        return rows[0] if rows else None

    async def insert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        """Insert a bounded chunk batch and encode vectors in Turso natively."""
        with_embeddings: list[Statement] = []
        without_embeddings: list[Statement] = []
        vector_sql = (
            "INSERT OR IGNORE INTO chunks (id, repo_id, file_path, start_line, end_line, language, symbols, content, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, vector32(?))"
        )
        plain_sql = (
            "INSERT OR IGNORE INTO chunks (id, repo_id, file_path, start_line, end_line, language, symbols, content, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)"
        )
        for chunk in chunks:
            values = [
                chunk["id"], chunk["repo_id"], chunk["file_path"], chunk["start_line"],
                chunk["end_line"], chunk["language"], json.dumps(chunk.get("symbols") or []), chunk["content"],
            ]
            if chunk.get("embedding") is None:
                without_embeddings.append(Statement(plain_sql, values))
            else:
                with_embeddings.append(Statement(
                    vector_sql,
                    values + [json.dumps(chunk["embedding"], separators=(",", ":"))],
                ))
        await self.batch(with_embeddings + without_embeddings)

    async def close(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._client.close)


@lru_cache(maxsize=1)
def get_turso_store() -> TursoStore:
    url = settings.turso_database_url.strip()
    token = settings.turso_auth_token.strip()
    if not url or not token:
        raise DatabaseConfigurationError(
            "Turso is not configured. Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in the backend environment."
        )
    try:
        return TursoStore(url, token)
    except BaseException as error:
        # libsql's Rust TLS layer can raise pyo3_runtime.PanicException when
        # the host has no usable certificate/keychain (common in local CI and
        # macOS sandboxes). Convert that panic into the same safe dependency
        # error as an ordinary connection failure instead of crashing a
        # request task or taking down the health endpoint.
        if type(error).__name__ != "PanicException":
            raise
        raise DatabaseConfigurationError("Could not initialize the Turso database client.") from error


_turso_schema_verified = False
_turso_schema_lock = asyncio.Lock()


async def assert_turso_schema() -> None:
    """Fail early with a migration instruction instead of leaving requests hanging."""
    global _turso_schema_verified
    if _turso_schema_verified:
        return
    async with _turso_schema_lock:
        if _turso_schema_verified:
            return
        try:
            store = get_turso_store()
            required_tables = (
                "repos", "chunks", "repo_files", "repo_dependencies", "repo_coverage",
                "ingestion_jobs", "chat_messages", "kt_cache", "account_entitlements", "billing_orders",
            )
            placeholders = ", ".join("?" for _ in required_tables)
            rows = await store.fetch_all(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (" + placeholders + ")",
                list(required_tables),
            )
            present = {str(row.get("name")) for row in rows}
            missing = [table for table in required_tables if table not in present]
            if missing:
                raise DatabaseConfigurationError(
                    "Turso schema is missing required tables: " + ", ".join(missing)
                )
        except DatabaseConfigurationError:
            raise
        except BaseException as error:
            if type(error).__name__ != "PanicException":
                raise
            raise DatabaseConfigurationError(
                "Turso schema is not initialized or is unavailable. Run turso/00_init.sql, turso/02_billing.sql, and turso/04_limits_and_github.sql in the Turso SQL shell, "
                "then restart the backend."
            ) from error
        _turso_schema_verified = True


def explain_database_error(error: Exception) -> str:
    """Return safe, actionable messages without exposing database credentials or SQL."""
    message = str(error).lower()
    if "no such table" in message or "does not exist" in message:
        return "Turso schema is not initialized. Run turso/00_init.sql and the current additive migrations, then restart the backend."
    if "vector" in message and ("dimension" in message or "length" in message):
        return (
            "The configured embedding dimension does not match the Turso schema. "
            "Set EMBEDDING_DIMENSION=2048 and run the current turso/00_init.sql."
        )
    if "unauthorized" in message or "auth" in message or "token" in message:
        return "Turso rejected the database credential. Replace TURSO_AUTH_TOKEN and restart the backend."
    logger.error("Unhandled Turso database error: %s", type(error).__name__)
    return "The database could not complete that request. Please try again shortly."
