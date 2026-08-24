create extension if not exists vector;

create table if not exists repos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null, -- links to Supabase auth.users(id)
  repo_name text not null,
  github_url text not null,
  status text not null default 'cloning',
  error_message text,
  chunk_count int default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (user_id, repo_name)
);

alter table repos enable row level security;

create table if not exists chunks (
  id uuid primary key default gen_random_uuid(),
  repo_id uuid references repos(id) on delete cascade,
  file_path text not null,
  start_line int,
  end_line int,
  language text,
  symbols text[] not null default '{}',
  content text not null,
  embedding vector(1024),
  content_tsv tsvector generated always as (to_tsvector('english', content)) stored,
  created_at timestamptz default now()
);

-- Safe for existing projects created before symbol metadata was introduced.
alter table chunks add column if not exists symbols text[] not null default '{}';

-- Drop before a possible vector-dimension change; it is recreated below.
drop index if exists chunks_embedding_idx;

-- The application uses NVIDIA's hosted 1024-dimensional embedding API instead of the
-- heavyweight local PyTorch model. Existing 384-dimensional rows cannot be
-- compared with the new vectors, so intentionally clear them and require a
-- one-time re-index after this migration.
do $$
declare
  existing_dimension integer;
begin
  select a.atttypmod - 4
    into existing_dimension
  from pg_attribute a
  join pg_class c on c.oid = a.attrelid
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public'
    and c.relname = 'chunks'
    and a.attname = 'embedding'
    and not a.attisdropped;

  if existing_dimension is not null and existing_dimension <> 1024 then
    delete from chunks;
    if to_regclass('public.kt_cache') is not null then
      delete from kt_cache;
    end if;
    update repos
      set status = 'failed',
          chunk_count = 0,
          error_message = 'Embeddings were upgraded. Re-ingest this repository.';
    execute 'alter table chunks alter column embedding type vector(1024) using null::vector(1024)';
  end if;
end;
$$;

alter table chunks enable row level security;

create index if not exists chunks_embedding_idx on chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);
create index if not exists chunks_content_tsv_idx on chunks using gin (content_tsv);

create table if not exists kt_cache (
  id uuid primary key default gen_random_uuid(),
  repo_id uuid references repos(id) on delete cascade unique,
  tech_stack jsonb,
  onboarding_manual text,
  file_summaries jsonb,
  created_at timestamptz default now()
);

alter table kt_cache enable row level security;

-- Durable work queue. The API records a job before returning,
-- while the private cron endpoint claims and processes one job at a time.
create table if not exists ingestion_jobs (
  id uuid primary key default gen_random_uuid(),
  repo_id uuid not null references repos(id) on delete cascade unique,
  user_id uuid not null,
  github_url text not null,
  status text not null default 'queued' check (status in ('queued', 'processing', 'completed', 'failed')),
  attempts int not null default 0,
  claimed_at timestamptz,
  finished_at timestamptz,
  last_error text,
  created_at timestamptz not null default now()
);

alter table ingestion_jobs enable row level security;
create index if not exists ingestion_jobs_status_created_idx on ingestion_jobs (status, created_at);

-- Durable, account-scoped conversation history for each repository workspace.
create table if not exists chat_messages (
  id uuid primary key default gen_random_uuid(),
  repo_id uuid not null references repos(id) on delete cascade,
  user_id uuid not null,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  citations jsonb not null default '[]'::jsonb,
  tool_calls jsonb not null default '[]'::jsonb,
  mode text,
  latency_ms int,
  created_at timestamptz not null default now()
);

alter table chat_messages enable row level security;
alter table chat_messages alter column citations set default '[]'::jsonb;
alter table chat_messages alter column tool_calls set default '[]'::jsonb;
create index if not exists chat_messages_repo_user_created_idx on chat_messages (repo_id, user_id, created_at);

-- Recreate the RPCs so an existing deployment receives the symbols column too.
drop function if exists match_chunks_dense(uuid, vector, int);
drop function if exists match_chunks_sparse(uuid, text, int);

-- RPC for Dense Search
create or replace function match_chunks_dense(p_repo_id uuid, p_query_embedding vector(1024), p_limit int)
returns table(id uuid, file_path text, start_line int, end_line int, language text, symbols text[], content text, score float)
language plpgsql
as $$
begin
  return query
  select c.id, c.file_path, c.start_line, c.end_line, c.language, c.symbols, c.content,
         (1 - (c.embedding <=> p_query_embedding))::float as score
  from chunks c
  where c.repo_id = p_repo_id
  order by c.embedding <=> p_query_embedding
  limit p_limit;
end;
$$;

drop policy if exists repos_select_own on repos;
drop policy if exists repos_insert_own on repos;
drop policy if exists repos_update_own on repos;
drop policy if exists repos_delete_own on repos;
drop policy if exists chunks_select_own on chunks;
drop policy if exists chunks_insert_own on chunks;
drop policy if exists chunks_update_own on chunks;
drop policy if exists chunks_delete_own on chunks;
drop policy if exists kt_cache_select_own on kt_cache;
drop policy if exists kt_cache_insert_own on kt_cache;
drop policy if exists kt_cache_update_own on kt_cache;
drop policy if exists kt_cache_delete_own on kt_cache;
drop policy if exists ingestion_jobs_service_role_only on ingestion_jobs;
drop policy if exists chat_messages_select_own on chat_messages;
drop policy if exists chat_messages_insert_own on chat_messages;
drop policy if exists chat_messages_delete_own on chat_messages;

create policy repos_select_own on repos
for select
to authenticated
using (auth.uid() = user_id);

create policy repos_insert_own on repos
for insert
to authenticated
with check (auth.uid() = user_id);

create policy repos_update_own on repos
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy repos_delete_own on repos
for delete
to authenticated
using (auth.uid() = user_id);

create policy chunks_select_own on chunks
for select
to authenticated
using (
  exists (
    select 1
    from repos
    where repos.id = chunks.repo_id
      and repos.user_id = auth.uid()
  )
);

create policy chunks_insert_own on chunks
for insert
to authenticated
with check (
  exists (
    select 1
    from repos
    where repos.id = chunks.repo_id
      and repos.user_id = auth.uid()
  )
);

create policy chunks_update_own on chunks
for update
to authenticated
using (
  exists (
    select 1
    from repos
    where repos.id = chunks.repo_id
      and repos.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from repos
    where repos.id = chunks.repo_id
      and repos.user_id = auth.uid()
  )
);

create policy chunks_delete_own on chunks
for delete
to authenticated
using (
  exists (
    select 1
    from repos
    where repos.id = chunks.repo_id
      and repos.user_id = auth.uid()
  )
);

create policy kt_cache_select_own on kt_cache
for select
to authenticated
using (
  exists (
    select 1
    from repos
    where repos.id = kt_cache.repo_id
      and repos.user_id = auth.uid()
  )
);

create policy kt_cache_insert_own on kt_cache
for insert
to authenticated
with check (
  exists (
    select 1
    from repos
    where repos.id = kt_cache.repo_id
      and repos.user_id = auth.uid()
  )
);

create policy kt_cache_update_own on kt_cache
for update
to authenticated
using (
  exists (
    select 1
    from repos
    where repos.id = kt_cache.repo_id
      and repos.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from repos
    where repos.id = kt_cache.repo_id
      and repos.user_id = auth.uid()
  )
);

create policy kt_cache_delete_own on kt_cache
for delete
to authenticated
using (
  exists (
    select 1
    from repos
    where repos.id = kt_cache.repo_id
      and repos.user_id = auth.uid()
  )
);

-- Browser clients never access queue rows; the backend uses the
-- Supabase service-role key, which bypasses RLS.
create policy ingestion_jobs_service_role_only on ingestion_jobs
for all
to service_role
using (true)
with check (true);

create policy chat_messages_select_own on chat_messages
for select
to authenticated
using (auth.uid() = user_id);

create policy chat_messages_insert_own on chat_messages
for insert
to authenticated
with check (
  auth.uid() = user_id
  and exists (
    select 1
    from repos
    where repos.id = chat_messages.repo_id
      and repos.user_id = auth.uid()
  )
);

create policy chat_messages_delete_own on chat_messages
for delete
to authenticated
using (auth.uid() = user_id);

-- RPC for Sparse Search
create or replace function match_chunks_sparse(p_repo_id uuid, p_query text, p_limit int)
returns table(id uuid, file_path text, start_line int, end_line int, language text, symbols text[], content text, score float)
language plpgsql
as $$
begin
  return query
  select c.id, c.file_path, c.start_line, c.end_line, c.language, c.symbols, c.content,
         ts_rank(c.content_tsv, plainto_tsquery('english', p_query))::float as score
  from chunks c
  where c.repo_id = p_repo_id and c.content_tsv @@ plainto_tsquery('english', p_query)
  order by score desc
  limit p_limit;
end;
$$;
