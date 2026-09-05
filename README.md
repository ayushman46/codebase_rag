# Codebase Intelligence

Codebase Intelligence turns a public GitHub repository into a private workspace that can be searched and discussed with source citations. It helps a person understand an unfamiliar system without opening every file manually. Answers are grounded in the indexed source, and each citation shows the file path, the line range, and the reason that the evidence was selected.

## Why this project exists

Modern repositories are difficult to learn because useful context is spread across application code, configuration, database scripts, tests, deployment files, and documentation. A README can describe the intended design while the implementation has changed. A normal chat model can also miss files, invent relationships, or cite a convenient document that does not answer the question.

Codebase Intelligence addresses that gap by building a searchable source workspace before answering questions. It combines exact file lookup, keyword search, semantic search, dependency evidence, file metadata, and a question specific evidence plan.

## Who benefits from it -

### A new intern joining a company

An intern can submit a public repository and ask questions in plain language. The workspace can explain where authentication is implemented, how a request reaches the database, which files create a deployment, how tests are organized, and which terms are important. The intern can learn from the actual source instead of relying on a long meeting or incomplete notes.

The answer includes the relevant paths and line ranges. This gives the intern a direct route from an explanation to the implementation and makes it easier to ask a precise follow up question.

### A senior employee giving knowledge transfer

Knowledge transfer often repeats the same explanation for every new joiner. A senior employee can index the repository once and use the workspace as a durable first layer of context. New joiners can ask about architecture, important flows, configuration, failure handling, or the reason a component exists before requesting help from the senior employee.

The senior employee can also use dependency and impact questions to explain what could be affected by changing a file. This makes a short handover more useful and reduces interruptions without replacing human review.

### A person starting as an open source contributor

An open source contributor can begin with questions such as where an issue should be fixed, how a feature flows through the repository, which tests cover a component, how to run the project, and which files are safe to change. The contributor can ask for the implementation behind a README statement and inspect the cited source directly.

This shortens the time between finding a project and making a useful first contribution. It also helps a contributor understand conventions before opening a pull request.

### A reviewer or technical investigator

The workspace can support a bounded architecture review, security review, onboarding review, or technical due diligence session. The response is limited to evidence that exists in the indexed repository. If the repository does not establish a claim, the answer states that evidence is missing instead of presenting an assumption as a fact.

## Problems it solves

1. It reduces the time needed to find the file that implements a feature.

2. It gives answers based on source rather than only on general model knowledge.

3. It keeps file names, symbols, and real line ranges with every chunk.

4. It uses a question specific retrieval plan. An authentication question can prioritize authentication routes, middleware, sessions, configuration, and tests. A navigation question can prioritize header and navigation components. An API location question can return implementation paths instead of a generic README.

5. It explains the limits of the index. The repository list reports eligible source files, indexed files, omitted files, omission reasons, and omitted paths.

6. It supports incremental re indexing. A SHA 256 manifest lets the worker skip unchanged files and replace changed or removed file evidence.

7. It supports durable indexing jobs. A worker can claim a queued job, renew its lease, recover abandoned work, and allow a user to stop indexing.

8. It continues to support keyword retrieval when the hosted embedding provider is temporarily unavailable.

## How the system works

<img width="677" height="572" alt="image" src="https://github.com/user-attachments/assets/a0b9569d-9e63-4db1-b2d6-f8a4b4dcb59c" />

### Authentication

The user signs in with Google through Supabase Auth. The browser receives a Supabase session token. The FastAPI server validates that token and uses the authenticated user identifier for every repository, conversation, job, usage, and billing query.

Supabase is used as the identity provider. Repository content, vectors, metadata, conversations, jobs, and quota data are stored in Turso. The browser never receives the Turso authentication token, the NVIDIA API key, the Razorpay secret, or a database service credential.

### Repository submission

The user submits a public HTTPS GitHub repository URL. The server normalizes the URL, validates its shape, checks the account limits, and creates or reuses an owned repository row. A durable ingestion job is written before the request returns to the browser.

<img width="343" height="514" alt="image" src="https://github.com/user-attachments/assets/38c41665-47a7-46f3-b632-95aada7ee184" />

### Cloning

The worker creates a unique temporary directory and performs a shallow Git clone. It uses a blob filter to avoid downloading unnecessary history. The clone is removed after the job completes or fails.

### File selection

The selection pass walks the checkout without entering ignored directories. It accepts source code, configuration, documentation, database scripts, and common deployment files. It rejects hidden files, lockfiles, minified files, unsupported formats, binary files, symlinks, files over the configured size, and files that cannot be read as text.

The same selection policy produces the coverage report. This prevents the user interface from claiming that every byte of a checkout was indexed when the policy intentionally omitted files.

### File manifest

Every selected file receives a SHA 256 content hash and a byte size. During re indexing, the worker compares the new manifest with the stored manifest. Unchanged files are left in place. Changed files receive new chunks and vectors. Removed files have their stale chunks and file metadata removed.

### Chunking

The chunker reads a source file and preserves its relative path, language, symbols, starting line, ending line, and content. It uses declaration boundaries where possible and bounded line or character windows for large files. Chunk overlap helps preserve context across a boundary.

The current safety settings allow a maximum of 150 lines per line based chunk window, a character ceiling of 12,000 characters per chunk, and a maximum of 3,500 chunks per repository. The worker streams one changed file at a time and releases vectors after each bounded insert batch, keeping peak memory suitable for a 512 MB Render instance.

### Dependency evidence

The dependency pass recognizes common import and include forms and resolves them only when the target exists in the same checkout. It stores source file, target file, import name, and line number. Impact questions use this graph as additional evidence and label it separately from ordinary content matches. The repository menu also exposes Change impact, which accepts a relative file path and lists the indexed files that import it. Dynamic and external imports are explicitly reported as outside the graph.

### Embeddings

The default embedding model is NVIDIA Nemotron 3 Embed 1B. It produces native 2,048 dimensional float vectors for the configured database schema. The worker sends passage inputs in bounded batches. It starts with eight passages per request and reduces the batch to four if the provider rejects a payload. Every chunk must still receive a vector or be retained for keyword retrieval when the provider is unavailable.

The application keeps a small request budget for interactive questions while indexing. The default application limit is 20 NVIDIA calls per minute, with four calls reserved for queries. This is an application throttle and not a promise about NVIDIA hosted service quotas.

Progress writes are throttled so Turso is not updated after every provider request. Cancellation is still checked before every embedding batch and worker leases continue to receive heartbeats.

### Ingestion performance

File selection, hashing, dependency extraction, and chunking are linear in the selected source size. Local dependency lookups use sets rather than repeated repository scans, and line ranges are calculated with one newline index and binary search. Changed files are chunked with a bounded worker pool, while unchanged files skip chunking and embedding entirely. Chunks are persisted in configurable batches of 250 by default, reducing remote database round trips without changing ordering or evidence. Hosted embedding latency remains the dominant variable because it depends on NVIDIA service capacity.

### Turso persistence

Turso stores repository rows, file manifests, source chunks, native vectors, dependency edges, coverage reports, ingestion jobs, factual metadata, conversations, account usage, and billing orders. Chunk inserts use bounded idempotent batches. Read statements avoid unnecessary remote commits, and vector JSON is compacted before it is passed to the native vector function.

### Retrieval

The retrieval planner first classifies the question. It can identify an explicit file request, an API location question, a security question, an indexing question, an impact question, a documentation question, or a broad architecture question.

The planner then selects the smallest useful evidence set. It combines parameterized keyword search, native cosine vector search, exact file matching, path hints, dependency evidence, and a bounded overview fallback. Results are deduplicated and made file diverse before they reach the answer model.

An explicit request for a file such as sql/schema.sql uses an exact file path route. A question about authentication prioritizes authentication and session implementation paths. A question about the navigation bar prioritizes header and navigation components. README content is retained for documentation and overview questions but is not used as a generic citation for a targeted implementation question.

### Answer generation

The answer model receives the user question, a bounded conversation history, the evidence plan, and the selected source chunks. The prompt requires a structured response, bold file names, concise explanations, source citations, and an evidence limits section when a claim is not established by the index.

The system removes provider planning traces before content is displayed or saved. If the provider returns no usable answer, the API returns a safe failure without exposing internal credentials or stack details.

## Current limits and coverage

The defaults are intentionally finite so one user cannot exhaust the worker or database.

1. Maximum selected files in one repository: 5,000.

2. Maximum eligible source bytes in one repository: 100 MB.

3. Maximum size of one selected source file: 50 MB.

4. Maximum chunks in one repository: 3,500.

5. Explorer indexed source quota: 200 MB across the account.

6. Team indexed source quota: 800 MB while the Team entitlement is active.

7. Team price in the current configuration: 300 Indian rupees for 30 days.

These values are configuration settings, not guarantees of unlimited storage. A user can delete a repository from the indexed codebases section to release its accounted source bytes.

### Files that are not indexed

The current policy excludes hidden files, ignored directories, symlinks, lockfiles, minified files, binary or invalid text, unsupported formats, files over 50 MB, and files rejected by the repository safety limits. The coverage report exposes the reason and path for policy exclusions that are detected during selection.

The worker does not index Git history. It indexes the current shallow checkout. A private GitHub repository is not accepted by the public URL ingestion flow.

## Supported workflows

The chat selector provides bounded modes for different goals.

1. General understanding focuses on the best evidence for the question.

2. New engineer onboarding explains structure, setup, important flows, and vocabulary.

3. Security review focuses on authentication, authorization, secrets, trust boundaries, validation, and security relevant tests that are present in the index.

4. Architecture interview explains components, data flow, boundaries, and tradeoffs supported by source.

5. Open source contribution explains how to set up the project, locate a change, find tests, and understand contribution paths.

6. Technical due diligence gives a bounded summary of architecture, dependencies, operational concerns, and evidence gaps.

7. Code editing and PR is the only mode that can generate a change proposal or expose the GitHub review action. It asks the code-specialized model for exact search and replace hunks across at most eight explicitly evidenced files, checks every hunk against that file's indexed source, and refuses speculative or partial patches. The complete current files are loaded from GitHub before the proposed hunks are applied. A short lived, file set scoped server ticket is required before the file or PR endpoints can be used.

The modes change evidence priorities and answer structure. They do not create facts that are absent from the repository.

### Reviewed GitHub changes

The Review and Push PR action is available only inside Code editing and PR mode and requires a separate GitHub OAuth connection. Google sign in remains the identity used for the Codebase Intel workspace. When a user opens a review, the server loads the exact current files and their Git blob SHAs, applies only validated exact-match hunks, and lets the user review or edit every complete file before confirming. The server checks that the signed in workspace owns the indexed repository, verifies the GitHub token and file-set editing ticket, validates relative paths and the branch name, checks every file SHA again, creates one atomic commit on a new codebase-intel branch, and opens a pull request. A user with write permission gets a branch in the upstream repository. A user without write permission gets a fork and a pull request targeting the upstream repository. Existing branches are never force updated, and any stale file returns a conflict so the user can refresh and review again.

GitHub OAuth states are opaque, short lived, single use records in Turso. OAuth tokens are encrypted at rest with GITHUB_TOKEN_ENCRYPTION_KEY and are never sent to the browser or written to logs. Editing tickets use EDITING_TICKET_SECRET when set, or the existing GitHub encryption key during a rolling deployment. Set the exact callback URL in the GitHub OAuth App and in GITHUB_REDIRECT_URI. Run turso/04_limits_and_github.sql after the existing schema migrations before enabling the feature.

For an issue-driven change, select Code editing and PR mode and paste the issue number and full issue text, for example `Issue #1428: ...`. The retrieval plan records the issue reference, keeps a bounded hybrid search across implementation files, tests, callers, and configuration, and carries the issue number into the proposed pull request. The patch still appears only when every exact replacement is grounded in the selected repository evidence; if the available evidence cannot support a complete fix, the system refuses to expose a push action.

## Dependencies

### Backend dependencies

The backend dependencies are installed from backend/requirements.txt.

1. FastAPI provides the HTTP API and request validation.

2. Uvicorn runs the FastAPI application.

3. OpenAI provides the client for the OpenAI compatible NVIDIA NIM endpoints.

4. Code editing mode uses NVIDIA's hosted Qwen2.5 Coder model with a Qwen3 Next catalog fallback when the primary free endpoint is unavailable. Both models use the same provider-neutral client boundary.

5. Supabase provides Google session validation.

6. libsql version 0.1.11 provides the Turso client.

7. GitPython performs shallow GitHub clones.

8. pydantic settings loads and validates environment configuration.

9. Razorpay creates Team payment orders and supports server side signature verification.

### Frontend dependencies

The frontend dependencies are defined in frontend/package.json.

1. React and React DOM provide the interface.

2. Vite provides the development server and production build.

3. React Router provides page navigation.

4. Zustand stores session, repository, conversation, usage, and indexing state.

5. Axios handles API requests and timeouts.

6. Supabase JavaScript provides browser session management.

7. React Markdown renders structured model answers.

8. Prism provides scoped source code highlighting.

9. Lucide React provides the interface icons.

10. Framer Motion provides restrained interface motion.

11. Tailwind CSS and the Tailwind Vite integration provide utility styling support.

## Repository structure

1. backend/main.py creates the FastAPI application, request telemetry middleware, health and readiness routes, and frontend serving.

2. backend/api/auth.py validates authenticated Supabase sessions.

3. backend/api/ingest_router.py accepts ingestion requests.

4. backend/api/query_router.py handles conversations and grounded questions.

5. backend/api/repos_router.py lists, updates, re indexes, cancels, and deletes owned repositories.

6. backend/api/billing_router.py creates Team orders and verifies Razorpay signatures.

7. backend/ingest/cloner.py validates URLs, clones repositories, and reports file coverage.

8. backend/ingest/chunker.py creates bounded source chunks and line ranges.

9. backend/ingest/dependencies.py builds the local dependency graph.

10. backend/ingest/embedder.py calls the NVIDIA embedding endpoint and validates vector dimensions.

11. backend/ingest/pipeline.py coordinates the durable ingestion workflow.

12. backend/ingest/local_worker.py runs queued jobs in the web service process.

13. backend/ingest/summarizer.py creates factual repository metadata for overview questions.

14. backend/retrieval/retriever.py plans evidence and fuses exact, keyword, semantic, and dependency matches.

15. backend/agent/nemotron.py calls the answer model and removes internal planning output.

16. backend/database.py provides the server only Turso data layer.

17. backend/quota.py enforces indexed source limits.

18. frontend/src/pages contains the landing, dashboard, account, documentation, platform, and pricing pages.

19. frontend/src/components contains the chat, repository, ingestion, authentication, and payment components.

20. frontend/src/store/useStore.js contains the client state and guarded asynchronous actions.

21. turso/00_init.sql creates the application schema.

22. turso/01_trust_features.sql adds coverage, dependency, and evidence metadata.

23. turso/02_billing.sql adds account entitlement and billing tables.

24. supabase/00_init.sql contains the older Supabase schema and is not the active application data layer after the Turso migration.

## Local development

### Requirements

Install Python 3.12, Node.js, npm, Git, a Turso database, a Supabase project with Google sign in, and an NVIDIA API key. Razorpay credentials are needed only when testing Team checkout.

### Install the backend

From the repository root, create the Python environment and install the dependencies.

```bash
python3 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt
```

### Install the frontend

```bash
cd frontend
npm install
cd ..
```

### Create the Turso schema

Create the database with the Turso CLI, then apply each SQL file through shell input redirection.

```bash
turso db create codebase-intel --wait
turso db shell codebase-intel < turso/00_init.sql
turso db shell codebase-intel < turso/01_trust_features.sql
turso db shell codebase-intel < turso/02_billing.sql
turso db show codebase-intel --url
turso db tokens create codebase-intel
```

The less than sign in the shell commands sends the SQL file to the Turso shell. Running the SQL file name as a positional argument makes Turso try to parse the file name as SQL and causes a syntax error.

### Configure the environment

Copy .env.example to .env and fill in the server and browser values. Keep server secrets out of every VITE variable.

```env
NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NEMOTRON_MODEL=nvidia/nemotron-3-super-120b-a12b
DETAILED_NEMOTRON_MODEL=nvidia/nemotron-3-ultra-550b-a55b
CODE_EDITING_MODEL=nvidia/nemotron-3-super-120b-a12b
CODE_EDITING_FALLBACK_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b
EMBEDDING_DIMENSION=2048
EMBEDDING_BATCH_SIZE=16
EMBEDDING_MIN_BATCH_SIZE=4
EMBEDDING_CHUNK_BUFFER_SIZE=64
NVIDIA_CALLS_PER_MINUTE=20
EMBEDDING_RETRY_ATTEMPTS=5
EMBEDDING_RETRY_BASE_SECONDS=2
EMBEDDING_PROGRESS_INTERVAL_BATCHES=4
EMBEDDING_HEARTBEAT_INTERVAL_BATCHES=2

SUPABASE_URL=
SUPABASE_KEY=
TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=

RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
TEAM_PLAN_AMOUNT_PAISE=30000
TEAM_PLAN_DURATION_DAYS=30
FREE_CODEBASE_BYTES=200000000
TEAM_CODEBASE_BYTES=800000000
MAX_REPOSITORY_BYTES=100000000
MAX_FILE_SIZE_BYTES=50000000
MAX_REPOSITORY_CHUNKS=3500

GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GITHUB_REDIRECT_URI=http://localhost:8000/api/github/callback
GITHUB_FRONTEND_ORIGIN=http://localhost:5173
# On Render, set GITHUB_REDIRECT_URI to the exact public callback URL:
# https://your-service.onrender.com/api/github/callback
# and GITHUB_FRONTEND_ORIGIN to the frontend origin. RENDER_EXTERNAL_URL is
# used as a safe fallback when the explicit callback is omitted.
GITHUB_TOKEN_ENCRYPTION_KEY=
EDITING_TICKET_SECRET=
EDITING_TICKET_TTL_SECONDS=600
GITHUB_OAUTH_STATE_TTL_SECONDS=600
MAX_GITHUB_CHANGE_BYTES=10000000
GITHUB_EDITOR_MAX_BYTES=2000000

VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_RAZORPAY_KEY_ID=
VITE_API_BASE_URL=http://localhost:8000/api
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
EDITING_RETRIEVAL_TOP_K=32
DENSE_CANDIDATE_LIMIT=256
ANSWER_RETRY_ATTEMPTS=2
```

The repository already ignores .env files. Never commit a Turso token, NVIDIA key, Razorpay secret, Supabase service role key, or any private repository credential.

### Start the application

Run the backend from the repository root.

```bash
backend/venv/bin/python -m uvicorn main:app --app-dir backend --reload --port 8000
```

In a second terminal, start the frontend.

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. The backend health endpoint is available at http://localhost:8000/api/health. Deployment readiness, including a live Turso query and a bounded NVIDIA provider probe, is available at http://localhost:8000/api/ready.

The local worker runs inside the FastAPI process by default. It claims one durable Turso job at a time. The worker can be disabled by setting LOCAL_INGESTION_WORKER to false when another worker process is responsible for the queue.

## Google sign in setup

1. Enable Google in the Supabase Authentication providers section.

2. Add the Supabase callback URL to the Google Cloud OAuth client.

3. Add http://localhost:5173 and the deployed application URL to the Supabase redirect allow list.

4. Add the deployed application origin to the Google OAuth authorized JavaScript origins.

5. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in the frontend environment and SUPABASE_URL and SUPABASE_KEY in the backend environment.

The name shown in the Google account chooser comes from the Google Cloud OAuth consent screen. It is not controlled by the React application name.

## Team billing

The pricing page calls the server order endpoint. The server creates or reuses an order using the private Razorpay key and the configured amount. The browser opens the Razorpay Standard Checkout using only the public key.

After payment, the browser sends the payment identifier, order identifier, and signature to the server. The server calculates an HMAC SHA256 signature with the private secret and compares it using a timing safe comparison. Only a verified payment activates the Team entitlement.

The current flow grants 30 days of access and does not automatically renew. Recurring billing would require a separate Razorpay subscription and webhook design.

## API surface

All routes require a valid Supabase bearer token except the health and readiness routes.

1. GET /api/health checks service availability.

2. GET /api/ready performs a dependency readiness check with a Turso query and bounded NVIDIA provider probe.

3. POST /api/ingest validates a public GitHub URL and queues indexing.

4. POST /api/query retrieves evidence and returns a grounded answer.

5. GET /api/conversations/{repo_name} restores the owned conversation.

6. GET /api/repos lists repositories owned by the authenticated user.

7. GET /api/status/{repo_name} returns indexing progress and failure details.

8. GET /api/repos/statuses returns status for all owned repositories in one request.

9. POST /api/repos/{repo_name}/reindex queues a re index.

10. POST /api/repos/{repo_name}/cancel-indexing stops active indexing.

11. PATCH /api/repos/{repo_name} changes the workspace label.

12. DELETE /api/repos/{repo_name} removes the owned repository and related data.

13. GET /api/repos/{repo_name}/impact?file_path=src/example.py lists indexed files that import a selected file.

14. GET /api/account/usage returns indexed source usage and quota.

15. POST /api/create-order creates or reuses a Team Razorpay order.

16. POST /api/verify-payment verifies payment and activates the entitlement.

## Render deployment

The Render blueprint builds the Vite frontend and serves it from the FastAPI application. It runs the local ingestion worker in the same web service and uses Turso as the durable database.

Set the secret values in the Render environment for NVIDIA, Supabase, Turso, Razorpay, and the browser safe Supabase and Razorpay keys. Set CORS_ORIGINS to the final deployed origin. Do not put a private secret in a VITE variable.

After deployment, verify the following flow.

1. Open /api/health.

2. Sign in with Google.

3. Submit a small public repository.

4. Confirm the status moves through queued, cloning, chunking, embedding, summarizing, and ready.

5. Ask an implementation question and inspect the cited file paths and line ranges.

6. Re index the repository and confirm unchanged files are reused.

7. Test cancellation on a repository that takes long enough to show progress.

8. Test Team checkout only with Razorpay test credentials.

9. Open the repository three dot menu, choose Change impact, and enter a relative source path to verify the dependency graph.

## Reliability and security notes

The server validates authentication and ownership at the data access boundary. Repository names and paths are treated as untrusted input. SQL values are parameterized. Payment signatures are verified on the server. The API does not return database credentials, provider keys, stack traces, or private service details.

The queue uses atomic claims and worker leases. Idempotent inserts and repository scoped ownership checks reduce duplicate work and cross account access. Requests have bounded retries, timeouts, and safe user facing errors.

The hosted NVIDIA endpoint remains an external dependency. A temporary provider outage can delay semantic indexing. When embedding creation is unavailable, the repository can still be stored with keyword retrieval and a clear status message. A sustained provider outage cannot be solved entirely by application code.

## Verification

Run the backend tests from the backend directory.

```bash
cd backend
./venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
./venv/bin/python -m compileall -q .
cd ..
```

Build the frontend from the repository root.

```bash
npm --prefix frontend run build
```

The tests cover authentication boundaries, Turso storage, vector and keyword fallback behavior, file selection, chunking, exclusion reporting, evidence planning, dependency resolution, payment signature verification, quota enforcement, health probes, and guarded asynchronous flows. A CI workflow runs these checks and the frontend build on every push and pull request. The optional browser smoke suite lives in frontend/e2e and the standard library load probe lives in scripts/load_test.py.

## Contributing

Contributions are welcome when they improve source coverage, answer accuracy, security, reliability, accessibility, performance, or interface clarity.

### Before making a change

1. Read the architecture and indexing sections in this document.

2. Run the backend test suite and the frontend build so you know the starting state.

3. Find the narrowest component or flow that owns the behavior you want to change.

4. Check whether the change affects authentication, repository ownership, quota accounting, indexing coverage, citations, or payment verification.

### Development workflow

1. Fork the repository on GitHub.

2. Create a focused branch for one change.

3. Keep credentials and local database files out of the branch.

4. Make the smallest change that solves the problem.

5. Add or update a regression test for the behavior.

6. Run the backend tests, compilation check, frontend build, and Git whitespace check.

7. Test the affected flow with an empty state, a failure state, a slow network, and a long file name when those states apply.

8. Open a pull request with the problem, the solution, the affected files, test output, and any configuration or migration step.

### Contribution areas

New contributors can help improve token aware chunking, language specific dependency resolution, citation ranking evaluation, repository coverage reporting, accessibility testing, responsive layouts, provider failover, and documentation examples.

Changes to retrieval should include examples showing why the selected evidence is more relevant. Changes to indexing should show that file counts, line ranges, vectors, cancellation, and re indexing behavior remain correct. Changes to security boundaries should include tests proving that one user cannot read or mutate another user data.

## Project principles

1. Source evidence should be easier to inspect than a generated claim.

2. A targeted question should receive targeted citations.

3. Missing evidence should be stated clearly.

4. A slower answer with accurate evidence is better than a fast answer with invented context.

5. Every user owned resource must be protected on the server.

6. The interface should remain calm, readable, and useful on a small screen as well as a large screen.
