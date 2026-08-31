"""Database boundaries for Supabase Auth and Turso application data.

Supabase remains the identity provider. Repository records, indexing jobs,
source chunks, vector embeddings, metadata, and conversations live in Turso.
"""

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

import libsql
from supabase import create_client

from config import settings

logger = logging.getLogger(__name__)


class DatabaseConfigurationError(RuntimeError):
    """Raised when a required database service is unavailable or unconfigured."""


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
        self._client = libsql.connect(database=url, auth_token=auth_token, _check_same_thread=False)
        self._lock = asyncio.Lock()

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
                if attempt == attempts - 1 or not self._is_transient_error(error):
                    raise
                await asyncio.sleep(self._retry_delay(attempt))

        raise RuntimeError("Turso retry loop ended unexpectedly.")  # pragma: no cover

    @staticmethod
    def _is_read_statement(sql: str) -> bool:
        return sql.lstrip().upper().startswith(("SELECT", "EXPLAIN", "PRAGMA"))

    @staticmethod
    def _is_transient_error(error: Exception) -> bool:
        message = str(error).lower()
        return any(marker in message for marker in (
            "database is locked", "database is busy", "busy", "timeout", "timed out",
            "connection", "temporarily unavailable", "http 429", "http 500", "http 502",
            "http 503", "http 504",
        ))

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        return min(1.5, 0.15 * (2 ** attempt)) + random.uniform(0, 0.1)

    def _execute_sync(self, sql: str, args: list[Any]) -> QueryResult:
        cursor = self._client.execute(sql, args)
        columns = [item[0] for item in cursor.description] if cursor.description else []
        rows = [self._row_to_dict(columns, row) for row in cursor.fetchall()] if columns else []
        affected = cursor.rowcount if cursor.rowcount >= 0 else len(rows)
        self._client.commit()
        return QueryResult(rows=rows, rows_affected=affected)

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
                if attempt == 2 or not self._is_transient_error(error):
                    raise
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
                with_embeddings.append(Statement(vector_sql, values + [json.dumps(chunk["embedding"])]))
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
    except Exception as error:
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
            for table in ("repos", "chunks", "repo_files", "repo_dependencies", "repo_coverage", "ingestion_jobs", "chat_messages", "kt_cache"):
                await store.execute(f"SELECT 1 FROM {table} LIMIT 1")
        except DatabaseConfigurationError:
            raise
        except Exception as error:
            raise DatabaseConfigurationError(
                "Turso schema is not initialized or is unavailable. Run turso/00_init.sql in the Turso SQL shell, "
                "then restart the backend."
            ) from error
        _turso_schema_verified = True


def explain_database_error(error: Exception) -> str:
    """Return safe, actionable messages without exposing database credentials or SQL."""
    message = str(error).lower()
    if "no such table" in message or "does not exist" in message:
        return "Turso schema is not initialized. Run turso/00_init.sql, then restart the backend."
    if "vector" in message and ("dimension" in message or "length" in message):
        return (
            "The configured embedding dimension does not match the Turso schema. "
            "Set EMBEDDING_DIMENSION=2048 and run the current turso/00_init.sql."
        )
    if "unauthorized" in message or "auth" in message or "token" in message:
        return "Turso rejected the database credential. Replace TURSO_AUTH_TOKEN and restart the backend."
    logger.error("Unhandled Turso database error: %s", type(error).__name__)
    return "The database could not complete that request. Please try again shortly."
