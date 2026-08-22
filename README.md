# Codebase Intelligence System

Codebase Intelligence is a repository-aware question-answering application for developers evaluating, maintaining, or contributing to software projects. It accepts a public GitHub repository URL, creates a searchable source index, and answers questions from retrieved repository evidence rather than generic model knowledge.

The application preserves source file paths, chunk boundaries, languages, declaration symbols when detected, and source line ranges. Responses include the retrieved citations that support the answer.

## What the system does

An authenticated user submits a public GitHub repository through the existing web interface. The backend validates and shallow-clones the repository, filters irrelevant content, chunks supported text files, extracts lightweight symbol metadata, generates local embeddings, and stores the result in Supabase. Later questions use hybrid vector and keyword retrieval before NVIDIA Nemotron generates a grounded answer.

Typical questions include:

- Where is authentication implemented?
- Which file handles login requests?
- How does a request flow from a component to a service?
- Which files should change to modify a login page?
- Where is the database connection initialized?

## Architecture

```text
React frontend
    -> FastAPI API with Supabase bearer-token authentication
    -> repository record and background ingestion job
    -> shallow Git clone and file filtering
    -> chunking, line ranges, language and symbol metadata
    -> local MiniLM embeddings and Supabase pgvector storage
    -> hybrid dense and keyword retrieval
    -> bounded, cited repository context
    -> NVIDIA Nemotron final answer
```

The frontend is intentionally independent of the ingestion internals. It communicates with the backend through JSON endpoints and continues to receive `answer`, `citations`, `tool_calls`, `mode`, and latency fields from `POST /api/query`.

## Repository processing

The ingestion pipeline is implemented in `backend/ingest`.

1. `POST /api/ingest` accepts only an HTTPS URL in the form `https://github.com/owner/repository`.
2. The repository is shallow-cloned into a unique temporary directory.
3. Discovery ignores `.git`, dependency folders, virtual environments, build output, caches, hidden files, lock files, minified bundles, binary files, symlinks, and files over 1 MB.
4. Repository-wide file, byte, and chunk limits protect the service from oversized input.
5. Files are split at common declaration boundaries when possible and otherwise use overlapping line windows. Chunk line ranges are calculated from the actual source file.
6. Lightweight regular expressions record declared functions, classes, interfaces, structs, enums, and common JavaScript arrow functions. They supplement retrieval metadata; they are not presented as a full parser.
7. `sentence-transformers/all-MiniLM-L6-v2` produces 384-dimensional embeddings locally.
8. Chunks and metadata are written to Supabase in bounded batches. A deterministic repository metadata cache records languages, files, directories, and detected symbols without adding an ingestion-time model dependency.

If a clone, embedding, or indexing step fails, the repository is marked `failed` and receives a safe diagnostic message. The exact temporary clone directory is cleaned up in all cases.

## Retrieval and grounding

`backend/retrieval/retriever.py` combines two Supabase RPC searches:

- Dense cosine-similarity search over MiniLM embeddings.
- Sparse PostgreSQL full-text search over source content.

Reciprocal rank fusion combines the result sets. A README chunk is included as an architectural anchor when available, without exceeding the retrieval limit. The context builder then enforces a character budget before the model receives evidence.

Every evidence block contains a file path and `Lstart-Lend` range. The answer prompt explicitly prohibits invented paths, symbols, relationships, and line numbers. If the retrieved evidence is inadequate, the model is instructed to say so.

## NVIDIA Nemotron

The centralized client in `backend/agent/nemotron.py` uses NVIDIA's OpenAI-compatible endpoint:

- Endpoint: `https://integrate.api.nvidia.com/v1`
- Model: `nvidia/nemotron-3-ultra-550b-a55b`
- Authentication: `NVIDIA_API_KEY`
- Request settings: `temperature=0.1`, `top_p=0.95`, and a bounded output limit
- Thinking: enabled for provider processing, but only final answer content is returned to the application

The current frontend uses ordinary JSON responses rather than a streaming protocol, so the backend preserves that contract. Provider timeouts, connection failures, status failures, and malformed responses are mapped to controlled API errors. Model reasoning content is never returned to the frontend.

## Technology stack

- Frontend: React, Vite, Zustand, Supabase JavaScript client
- API: Python, FastAPI, Uvicorn
- Authentication and storage: Supabase Auth, PostgreSQL, pgvector, PostgREST
- Embeddings: Sentence Transformers, `all-MiniLM-L6-v2`
- Answer generation: NVIDIA Nemotron through the OpenAI-compatible Python client
- Git ingestion: GitPython

## Project structure

```text
backend/
  api/             FastAPI routes and authentication dependency
  agent/           Nemotron client and grounded-answer prompt
  ingest/          cloning, filtering, chunking, embeddings, metadata cache
  retrieval/       dense/sparse retrieval and result fusion
  tests/           backend, API, ingestion, retrieval, and provider tests
  config.py        environment-backed runtime settings
  database.py      Supabase client and schema validation
  main.py          FastAPI application
supabase/
  00_init.sql      schema, RLS policies, pgvector, and retrieval RPCs
frontend/          frozen React application
```

## Configuration

Copy `.env.example` to `.env` and set the values required by the deployment:

```env
NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

`SUPABASE_SERVICE_ROLE_KEY` is recommended for backend writes. The frontend uses only the `VITE_` public Supabase settings. `.env` is ignored by Git and must never be committed.

The backend also supports these optional limits:

```env
NVIDIA_TIMEOUT_SECONDS=90
NVIDIA_CALLS_PER_MINUTE=20
MAX_REPOSITORY_FILES=10000
MAX_REPOSITORY_BYTES=50000000
MAX_REPOSITORY_CHUNKS=20000
MAX_CONTEXT_CHARACTERS=60000
```

### Supabase schema

Run `supabase/00_init.sql` in the Supabase SQL editor before starting the application. It creates the pgvector extension, tables, row-level-security policies, `symbols` metadata column, and both retrieval RPCs.

Existing deployments created before the symbol-metadata change must run the updated SQL file and restart the backend. The backend reports this condition as a `503` configuration error instead of attempting ingestion against an incompatible schema.

### Embedding model

The embedding model must be available locally before the first ingestion. The backend deliberately does not substitute hash vectors, because that would make retrieval appear to work while losing semantic quality.

For an environment without a cached model, download it once while network access is available:

```bash
cd backend
./venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
```

## Local installation and startup

Requirements: Python 3.12 or compatible Python 3 release, Node.js for the existing frontend, Git, a Supabase project, and an NVIDIA API key.

```bash
python3 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt
backend/venv/bin/python -m uvicorn main:app --app-dir backend --reload --port 8000
```

The backend health endpoint is available at `GET /` and returns:

```json
{"status":"ok","message":"Codebase Intelligence System API v2"}
```

The existing frontend can then be started separately:

```bash
cd frontend
npm install
npm run dev
```

## API behavior

All repository endpoints require a Supabase bearer token, which the existing frontend attaches automatically.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/ingest` | Validate a public GitHub URL, create/reset a repository record, and start ingestion. |
| `POST /api/query` | Retrieve repository evidence and return a grounded Nemotron answer with citations. |
| `GET /api/repos` | List repositories owned by the authenticated user. |
| `GET /api/status/{repo_name}` | Return indexing state, chunk count, and safe failure message. |
| `DELETE /api/repos/{repo_name}` | Remove an owned repository and its cascaded records. |

Important response behavior:

- Invalid GitHub URLs return `400`.
- A duplicate active ingestion returns `409`.
- A repository that is not ready returns `409` from the query endpoint.
- Missing NVIDIA configuration or an incompatible/unavailable Supabase schema returns `503`.
- NVIDIA provider failures return `502` with a safe message.
- Unsupported or empty repository content is stored as a failed ingestion rather than leaving the repository in an in-progress state.

## End-to-end usage

1. Configure `.env` and apply `supabase/00_init.sql`.
2. Start the backend and existing frontend.
3. Sign in through the frontend.
4. Submit a public GitHub repository URL.
5. Wait for the repository status to become `ready`.
6. Select the repository and ask a repository-specific question.
7. Inspect the returned citations for the files and line ranges used as evidence.

## Testing

The backend test suite is run with:

```bash
cd backend
../backend/venv/bin/python -m unittest discover -s tests -v
```

The current suite covers application import/startup, API validation and response compatibility, URL normalization, file filtering, line-range and symbol extraction, embedding integration, hybrid retrieval, missing configuration handling, schema migration diagnostics, and NVIDIA request construction.

The following verification was executed during the current implementation work:

- Python compilation and 14 backend tests passed.
- The FastAPI application started successfully and served `GET /` with HTTP 200.
- A public GitHub repository was cloned, filtered, chunked, and cleaned up successfully.
- The local embedding model produced a 384-dimensional vector.
- A live NVIDIA Nemotron request succeeded using the configured environment key.

## Security and operational notes

- API keys are loaded only from environment settings and are not included in source, README examples, or API error messages.
- Ingestion accepts only public GitHub HTTPS repository URLs and rejects embedded credentials, query strings, fragments, and non-repository paths.
- Temporary clone cleanup is constrained to the configured temporary repository directory.
- User repository access is scoped by authenticated user ID and reinforced by Supabase row-level-security policies.
- The backend uses configured CORS origins rather than credentialed wildcard CORS.
- Background tasks run inside the FastAPI process. A production deployment that requires durable job execution across process restarts should replace this mechanism with a queue or worker before relying on long-running large-repository ingestion.

## Current limitations and extension points

- The application supports public GitHub repositories only; private repository credentials are intentionally not accepted.
- The current frontend uses non-streaming JSON responses. Streaming can be introduced later only with a compatible frontend contract.
- Symbol extraction is heuristic and intentionally lightweight. A language-aware parser can be added later when the additional dependency and operational complexity are justified.
- Supabase schema migrations are applied through the SQL editor in this repository's current deployment model.
- NVIDIA and Supabase availability remain external dependencies; the backend returns controlled errors when either service is unavailable.

The provider client, retrieval layer, and ingestion components are separated so a future model, parser, queue, or vector strategy can be introduced without changing the frontend API contract.
