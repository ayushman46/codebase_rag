create extension if not exists vector;

create table repos (
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

create table chunks (
  id uuid primary key default gen_random_uuid(),
  repo_id uuid references repos(id) on delete cascade,
  file_path text not null,
  start_line int,
  end_line int,
  language text,
  content text not null,
  embedding vector(384),
  content_tsv tsvector generated always as (to_tsvector('english', content)) stored,
  created_at timestamptz default now()
);

alter table chunks enable row level security;

create index on chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);
create index on chunks using gin (content_tsv);

create table kt_cache (
  id uuid primary key default gen_random_uuid(),
  repo_id uuid references repos(id) on delete cascade unique,
  tech_stack jsonb,
  onboarding_manual text,
  file_summaries jsonb,
  created_at timestamptz default now()
);

alter table kt_cache enable row level security;

-- RPC for Dense Search
create or replace function match_chunks_dense(p_repo_id uuid, p_query_embedding vector(384), p_limit int)
returns table(id uuid, file_path text, start_line int, end_line int, language text, content text, score float)
language plpgsql
as $$
begin
  return query
  select c.id, c.file_path, c.start_line, c.end_line, c.language, c.content, 
         (1 - (c.embedding <=> p_query_embedding))::float as score
  from chunks c
  where c.repo_id = p_repo_id
  order by c.embedding <=> p_query_embedding
  limit p_limit;
end;
$$;

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

-- RPC for Sparse Search
create or replace function match_chunks_sparse(p_repo_id uuid, p_query text, p_limit int)
returns table(id uuid, file_path text, start_line int, end_line int, language text, content text, score float)
language plpgsql
as $$
begin
  return query
  select c.id, c.file_path, c.start_line, c.end_line, c.language, c.content, 
         ts_rank(c.content_tsv, plainto_tsquery('english', p_query))::float as score
  from chunks c
  where c.repo_id = p_repo_id and c.content_tsv @@ plainto_tsquery('english', p_query)
  order by score desc
  limit p_limit;
end;
$$;
