# Codebase Intelligence

Codebase Intelligence indexes a public GitHub repository and answers questions with cited source evidence. It preserves source paths, line ranges, detected symbols, and conversation history for each signed-in user.

## Architecture

```text
React + Vite frontend
  -> FastAPI /api routes in the same Render service
  -> Supabase Auth validates the Google session
  -> Turso stores repository data, queue jobs, chunks, vectors, and chats
  -> Git shallow clone -> filtering -> chunking -> NVIDIA embeddings
  -> Turso hybrid retrieval -> NVIDIA Nemotron grounded answer
```

Supabase is deliberately used **only for authentication**. The browser never receives a Turso credential. Every repository, job, conversation, and chunk query includes the authenticated Supabase user id, which prevents cross-account data access at the application boundary.

## Turso migration

This version replaces the previous Supabase/Postgres data layer. Existing Supabase repository records and chunks are not used by the application after this migration; create the Turso schema and re-index repositories once.

1. Install and authenticate the [Turso CLI](https://docs.turso.tech/cli/introduction).
2. Create a database and wait for it to be available:

   ```bash
   turso db create codebase-intel --wait
   ```

3. Create the application schema:

   ```bash
   turso db shell codebase-intel < turso/00_init.sql
   ```

   If the database already has the original schema, apply the additive trust
   metadata migration as well:

   ```bash
   turso db shell codebase-intel < turso/01_trust_features.sql
   ```

   Apply the billing and account-quota tables after the trust migration:

   ```bash
   turso db shell codebase-intel < turso/02_billing.sql
   ```

4. Copy the database URL and create a write-capable application token:

   ```bash
   turso db show codebase-intel --url
   turso db tokens create codebase-intel
   ```

5. Put both values in the backend environment. Keep the token private; do not put either value in a `VITE_` variable.

   ```env
   TURSO_DATABASE_URL=libsql://YOUR_DATABASE-YOUR_ORGANIZATION.turso.io
   TURSO_AUTH_TOKEN=
   ```

The schema declares the `chunks.embedding` column as Turso native `F32_BLOB(2048)`. This matches the default NVIDIA `nvidia/nemotron-3-embed-1b` output. Turso also retains chunks without vectors when NVIDIA embeddings are temporarily unavailable, so keyword retrieval and source citations continue to work.

## Configuration

Copy `.env.example` to `.env` and fill in the values below.

```env
# Server only: NVIDIA
NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NEMOTRON_MODEL=nvidia/nemotron-3-super-120b-a12b
DETAILED_NEMOTRON_MODEL=nvidia/nemotron-3-ultra-550b-a55b
EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b
EMBEDDING_DIMENSION=2048

# Server only: Supabase verifies bearer tokens from Google sign-in.
SUPABASE_URL=
SUPABASE_KEY=

# Server only: application data in Turso.
TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=

# Server only: Razorpay Team checkout. The secret must never be exposed to Vite.
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
TEAM_PLAN_AMOUNT_PAISE=30000
TEAM_PLAN_DURATION_DAYS=30
FREE_CODEBASE_BYTES=500000000
TEAM_CODEBASE_BYTES=5000000000

# Browser-safe Supabase settings.
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
# Browser-safe Razorpay checkout key (public key only).
VITE_RAZORPAY_KEY_ID=
VITE_API_BASE_URL=http://localhost:8000/api
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

Do not add `TURSO_AUTH_TOKEN`, `NVIDIA_API_KEY`, or any service role credential to the frontend or repository.

## Local development

```bash
python3 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt
backend/venv/bin/python -m uvicorn main:app --app-dir backend --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The FastAPI process starts a durable ingestion worker by default. It atomically claims one Turso job at a time, renews a lease during long ingestion, recovers abandoned work, and permits users to cancel a queued or in-progress repository safely.

## Repository indexing

1. `POST /api/ingest` accepts a normalized public `https://github.com/owner/repository` URL.
2. The service queues a Turso job before returning to the browser.
3. A worker shallow-clones, filters unsupported/binary/generated files, chunks source content, and records file paths and true line ranges.
4. NVIDIA produces 2,048-dimensional embeddings in small retrying batches.
5. The worker records a SHA-256 manifest, writes chunks and vectors in bounded batches, builds factual file metadata, and marks the repository ready.
6. Re-indexing compares the manifest and re-embeds only changed files; removed files have their stale chunks deleted. If a re-index fails, unchanged evidence remains available.
7. A conservative dependency pass records only imports/includes resolved to files in the same checkout. Impact questions use those edges to retrieve likely dependents and label them as dependency evidence.
8. A failed embedding service does not discard usable source: the repository becomes ready with keyword retrieval and a clear status note.

Repository limits are configurable. Defaults allow up to 5,000 files, 25 MB total source, 5 MB per individual source file, and 1,500 chunks per repository.

Each account also has a cumulative indexed-source quota. Explorer accounts have
500 MB across all repositories. The Team checkout is ₹300 for one month and
activates a configurable 5 GB quota after the server verifies the Razorpay
signature. Usage is shown only on the signed-in Account page; deleting a
repository releases its indexed bytes.

The current integration uses Razorpay Standard Checkout for the Team payment
and activates the entitlement only after server-side verification. Each
verified payment grants 30 days of Team access; it does not automatically
renew. Automatic recurring billing requires a separate Razorpay Subscriptions
plan and webhook flow. This checkout never grants access from a client-side
success callback alone.

The repository list reports coverage as indexed files versus eligible source
files and records omission reasons and paths for hidden files, lockfiles,
unsupported formats, binary content, chunking failures, and the per-file size limit. Files in
intentionally ignored directories are not traversed; the report therefore
describes the indexing policy rather than claiming that every byte of a
checkout is indexed.

## Retrieval and answers

Retrieval combines:

- Turso native cosine vector search for semantic matches.
- Parameterized keyword matching over source contents and paths.
- Exact/suffix matching when a question names a file such as `sql/schema.sql`.
- A bounded README and source overview for architecture or comparison questions.
- Resolved same-repository dependency edges for impact questions such as “what breaks if this file changes?”.

Results are fused and made file-diverse before a bounded context reaches the answer model. Each citation includes the exact path and line range plus why it was selected (explicit file request, keyword match, semantic similarity, or overview fallback). The response also returns the deterministic evidence plan used for the question.

The chat workflow selector can target general questions, new-engineer
onboarding, security review, architecture interviews, open-source contribution,
or technical due diligence. These profiles bias retrieval toward relevant files
and constrain the answer organization; they never assert that a target exists
when the index does not contain it. The answer prompt requires Markdown
headings, bold file names, concise steps, and an explicit `Evidence limits`
section when a claim is not established by the supplied source.

## Google sign-in

1. Enable Google in Supabase **Authentication → Providers** and save your Google client ID and secret.
2. In Google Cloud, register the Supabase callback URL: `https://PROJECT_REF.supabase.co/auth/v1/callback`.
3. In Supabase **URL Configuration**, set the site URL and redirect URLs for `http://localhost:5173` and the deployed application URL.
4. Add the same deployed application origin to Google OAuth Authorized JavaScript origins.

The Google consent screen’s application name comes from Google Cloud’s OAuth consent screen settings, not from the codebase.

## Render deployment

`render.yaml` deploys one web service: its build command builds `frontend/dist`, then FastAPI serves the frontend and `/api` together.

In Render, provide these secret environment variables:

- `NVIDIA_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `VITE_RAZORPAY_KEY_ID` (public checkout key; safe for the browser)
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `CORS_ORIGINS` set to the final `https://YOUR-SERVICE.onrender.com` origin

After deployment, open `/api/health`, sign in, submit a repository, and verify it moves through queued, cloning, reading, indexing, mapping, and ready states.

## API

All endpoints require a valid Supabase bearer token except `/api/health`.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/ingest` | Validate a public GitHub URL and queue indexing. |
| `POST /api/query` | Retrieve evidence and return a grounded answer with citations. |
| `GET /api/conversations/{repo_name}` | Restore one owned workspace conversation. |
| `GET /api/repos` | List repositories owned by the current user. |
| `GET /api/status/{repo_name}` | Get safe indexing progress or failure details. |
| `POST /api/repos/{repo_name}/reindex` | Re-index an owned repository. |
| `POST /api/repos/{repo_name}/cancel-indexing` | Stop active indexing and remove partial chunks. |
| `PATCH /api/repos/{repo_name}` | Rename an owned workspace. |
| `DELETE /api/repos/{repo_name}` | Delete an owned workspace and related data. |
| `GET /api/account/usage` | Show the signed-in account's indexed-source usage and quota. |
| `POST /api/create-order` | Create or reuse the authenticated user's Team Razorpay order. |
| `POST /api/verify-payment` | Verify the Razorpay signature and activate the Team entitlement. |

## Verification

```bash
cd backend
./venv/bin/python -m unittest discover -s tests -v
./venv/bin/python -m py_compile $(rg --files -g '*.py' | tr '\n' ' ')
cd ..
npm --prefix frontend run build
```

The suite covers configuration failures, parameterized Turso storage, JSON metadata, chunk persistence without embeddings, authentication-independent API flows, repository ownership queries, source filtering/chunking, coverage/exclusion reporting, allow-listed evidence workflows, resilient retrieval, and incremental manifest behavior.
