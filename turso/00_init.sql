-- Codebase Intelligence application data schema for Turso/libSQL.
-- Supabase remains responsible only for Google OAuth and session validation.
-- Run this file once with: turso db shell YOUR_DATABASE < turso/00_init.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS repos (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  repo_name TEXT NOT NULL,
  github_url TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'cloning', 'chunking', 'embedding', 'summarizing', 'ready', 'failed', 'cancelled')),
  chunk_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, repo_name)
);

CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  language TEXT NOT NULL,
  symbols TEXT NOT NULL DEFAULT '[]',
  content TEXT NOT NULL,
  embedding F32_BLOB(2048),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS chunks_by_repo_file ON chunks(repo_id, file_path, start_line);

-- Full-text retrieval keeps code search responsive without making semantic
-- retrieval approximate. The external-content index stores no duplicate
-- source text and its triggers keep it in sync with chunks.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  content,
  file_path,
  content='chunks',
  content_rowid='rowid',
  tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_fts_after_insert AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, content, file_path) VALUES (new.rowid, new.content, new.file_path);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_after_delete AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content, file_path)
  VALUES ('delete', old.rowid, old.content, old.file_path);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_after_update AFTER UPDATE OF content, file_path ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content, file_path)
  VALUES ('delete', old.rowid, old.content, old.file_path);
  INSERT INTO chunks_fts(rowid, content, file_path) VALUES (new.rowid, new.content, new.file_path);
END;

-- Populate the index when this schema is applied to a database that already
-- contains chunks. `rebuild` is the FTS5-safe, idempotent way to synchronize
-- an external-content index; a normal SELECT from chunks_fts can read the
-- source table even when its index itself is empty.
INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild');

CREATE TABLE IF NOT EXISTS ingestion_jobs (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL UNIQUE REFERENCES repos(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  github_url TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'processing', 'failed', 'cancelled', 'completed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  claimed_at TEXT,
  heartbeat_at TEXT,
  claim_token TEXT,
  finished_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ingestion_jobs_queue ON ingestion_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS ingestion_jobs_user_status ON ingestion_jobs(user_id, status);

CREATE TABLE IF NOT EXISTS kt_cache (
  repo_id TEXT PRIMARY KEY REFERENCES repos(id) ON DELETE CASCADE,
  tech_stack TEXT NOT NULL DEFAULT '[]',
  onboarding_manual TEXT NOT NULL DEFAULT '',
  file_summaries TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  citations TEXT NOT NULL DEFAULT '[]',
  tool_calls TEXT NOT NULL DEFAULT '[]',
  mode TEXT,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS chat_messages_by_repo_user ON chat_messages(repo_id, user_id, created_at, id);
