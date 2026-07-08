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
