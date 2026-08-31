-- Additive migration for existing Codebase Intel Turso databases.
-- Safe to run after turso/00_init.sql; all statements are idempotent.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS repo_files (
  repo_id TEXT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  byte_size INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (repo_id, file_path)
);

CREATE INDEX IF NOT EXISTS repo_files_by_repo ON repo_files(repo_id, file_path);

CREATE TABLE IF NOT EXISTS repo_dependencies (
  repo_id TEXT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  source_file TEXT NOT NULL,
  target_file TEXT NOT NULL,
  import_name TEXT NOT NULL,
  line_number INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (repo_id, source_file, target_file, line_number)
);

CREATE INDEX IF NOT EXISTS repo_dependencies_target ON repo_dependencies(repo_id, target_file);

CREATE TABLE IF NOT EXISTS repo_coverage (
  repo_id TEXT PRIMARY KEY REFERENCES repos(id) ON DELETE CASCADE,
  total_seen_files INTEGER NOT NULL DEFAULT 0,
  eligible_files INTEGER NOT NULL DEFAULT 0,
  indexed_files INTEGER NOT NULL DEFAULT 0,
  excluded_files INTEGER NOT NULL DEFAULT 0,
  excluded_bytes INTEGER NOT NULL DEFAULT 0,
  excluded_reasons TEXT NOT NULL DEFAULT '{}',
  excluded_paths TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL
);
