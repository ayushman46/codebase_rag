-- Additive GitHub integration migration for Codebase Intel Turso databases.
-- Run after turso/00_init.sql, turso/01_trust_features.sql, and turso/02_billing.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS user_github_tokens (
  user_id TEXT PRIMARY KEY,
  github_user_id TEXT,
  github_username TEXT NOT NULL,
  access_token TEXT NOT NULL,
  scope TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS user_github_tokens_username ON user_github_tokens(github_username);

CREATE TABLE IF NOT EXISTS github_oauth_states (
  state_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  redirect_to TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);

CREATE INDEX IF NOT EXISTS github_oauth_states_expiry ON github_oauth_states(expires_at);

CREATE TABLE IF NOT EXISTS github_change_operations (
  operation_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  repo_name TEXT NOT NULL,
  file_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS github_change_operations_user ON github_change_operations(user_id, created_at);
