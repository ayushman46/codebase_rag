-- Additive ingestion-performance state.  This migration deliberately keeps
-- the existing repos.status CHECK constraint unchanged: the API derives the
-- public `searchable` state from repo_index_state while a durable job is still
-- completing semantic work.

CREATE TABLE IF NOT EXISTS repo_index_state (
  repo_id TEXT PRIMARY KEY REFERENCES repos(id) ON DELETE CASCADE,
  phase TEXT NOT NULL DEFAULT 'queued'
    CHECK (phase IN ('queued', 'cloning', 'scanning', 'manifesting', 'chunking', 'keyword', 'searchable', 'embedding', 'ready', 'failed', 'cancelled')),
  keyword_files INTEGER NOT NULL DEFAULT 0,
  keyword_chunks INTEGER NOT NULL DEFAULT 0,
  semantic_progress INTEGER NOT NULL DEFAULT 0 CHECK (semantic_progress BETWEEN 0 AND 100),
  embedding_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (embedding_status IN ('pending', 'running', 'complete', 'degraded')),
  searchable_at TEXT,
  semantic_ready_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS repo_index_state_phase ON repo_index_state(phase, updated_at);

-- Queue metadata is separate so this migration remains safe for the existing
-- ingestion_jobs table and its foreign-key relationships.
CREATE TABLE IF NOT EXISTS ingestion_job_meta (
  job_id TEXT PRIMARY KEY REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
  priority INTEGER NOT NULL DEFAULT 20,
  phase TEXT NOT NULL DEFAULT 'queued',
  progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ingestion_job_meta_queue ON ingestion_job_meta(priority, updated_at);

-- JSON text avoids coupling the cache to a particular vector extension while
-- still allowing duplicate passage content to reuse an embedding safely.
CREATE TABLE IF NOT EXISTS embedding_cache (
  content_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  dimension INTEGER NOT NULL,
  embedding_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (content_hash, model, dimension)
);

CREATE INDEX IF NOT EXISTS embedding_cache_updated ON embedding_cache(updated_at);

CREATE TABLE IF NOT EXISTS ingestion_metrics (
  job_id TEXT PRIMARY KEY REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
  repo_id TEXT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);
