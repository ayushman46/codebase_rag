import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from ingest.chunker import chunk_file, extract_symbols
from ingest.cloner import RepositoryValidationError, get_file_selection_report, get_files_to_process, normalize_github_url
from ingest.embedder import EMBEDDING_DIMENSION, EmbeddingUnavailableError, embed_chunks


class MemoryStore:
    """Minimal async store used to test the API boundary without a live Turso database."""

    def __init__(self):
        self.rows = []
        self.executed = []

    async def execute(self, sql, args=None):
        self.executed.append((sql, args or []))
        return SimpleNamespace(rows=[], rows_affected=1)

    async def fetch_one(self, sql, args=None):
        self.executed.append((sql, args or []))
        return self.rows[0] if self.rows else None

    async def fetch_all(self, sql, args=None):
        self.executed.append((sql, args or []))
        return list(self.rows)

    async def insert_chunks(self, chunks):
        self.rows.extend(chunks)


class BackendSmokeTests(unittest.TestCase):
    def test_app_imports_and_root_endpoint_works(self):
        from main import app
        client = TestClient(app)
        root = client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertEqual(client.get("/api/health").json(), {"status": "ok"})
        self.assertEqual(root.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", root.headers["content-security-policy"])

    def test_turso_store_handles_parameterized_rows_and_json_metadata(self):
        from database import TursoStore
        with tempfile.TemporaryDirectory() as tmp:
            store = TursoStore(f"file:{Path(tmp) / 'test.db'}", "local-test-token")

            async def run():
                await store.execute("CREATE TABLE records (id TEXT PRIMARY KEY, symbols TEXT NOT NULL)")
                await store.execute("INSERT INTO records VALUES (?, ?)", ["one", '["login"]'])
                return await store.fetch_one("SELECT id, symbols FROM records WHERE id = ?", ["one"])

            row = asyncio.run(run())
        self.assertEqual(row, {"id": "one", "symbols": ["login"]})

    def test_turso_chunk_insert_supports_keyword_only_fallback(self):
        from database import TursoStore
        with tempfile.TemporaryDirectory() as tmp:
            store = TursoStore(f"file:{Path(tmp) / 'test.db'}", "local-test-token")

            async def run():
                await store.execute(
                    "CREATE TABLE chunks (id TEXT PRIMARY KEY, repo_id TEXT, file_path TEXT, start_line INTEGER, "
                    "end_line INTEGER, language TEXT, symbols TEXT, content TEXT, embedding BLOB)"
                )
                await store.insert_chunks([{
                    "id": "chunk-1", "repo_id": "repo-1", "file_path": "src/auth.py", "start_line": 1,
                    "end_line": 2, "language": "py", "symbols": ["login"], "content": "def login(): pass", "embedding": None,
                }])
                return await store.fetch_one("SELECT id, symbols, content FROM chunks WHERE id = ?", ["chunk-1"])

            row = asyncio.run(run())
        self.assertEqual(row["symbols"], ["login"])
        self.assertEqual(row["content"], "def login(): pass")

    def test_turso_configuration_requires_server_only_credentials(self):
        from database import DatabaseConfigurationError, get_turso_store
        with patch("database.settings.turso_database_url", ""), patch("database.settings.turso_auth_token", ""):
            get_turso_store.cache_clear()
            with self.assertRaises(DatabaseConfigurationError):
                get_turso_store()
            get_turso_store.cache_clear()

    def test_answer_model_profiles_are_allow_listed(self):
        from api.query_router import QueryRequest
        from config import get_answer_model_options
        from pydantic import ValidationError
        self.assertEqual(get_answer_model_options("fast")[0], "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(get_answer_model_options("detailed")[0], "nvidia/nemotron-3-ultra-550b-a55b")
        with self.assertRaises(ValidationError):
            QueryRequest(repo_name="demo", question="Where is login?", model_profile="untrusted/model")
        with self.assertRaises(ValidationError):
            QueryRequest(repo_name="demo", question="Where is login?", workflow="untrusted")

    def test_credentials_cors_rejects_a_wildcard_origin(self):
        from config import get_cors_origins
        with patch("config.settings.cors_origins", "https://app.example.com,*"):
            with self.assertRaises(ValueError):
                get_cors_origins()

    def test_github_url_normalization_rejects_non_repository_urls(self):
        self.assertEqual(normalize_github_url(" https://github.com/octocat/Hello-World/ "), "https://github.com/octocat/Hello-World.git")
        for value in ("http://github.com/a/b", "https://github.com/a/b/tree/main", "https://evil.test/a/b"):
            with self.assertRaises(RepositoryValidationError):
                normalize_github_url(value)

    def test_get_files_to_process_accepts_larger_source_files_and_skips_oversized_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "src" / "extended.py").write_text("x" * 1_100_000, encoding="utf-8")
            (root / "src" / "oversized.py").write_text("x" * 2_000_001, encoding="utf-8")
            (root / "README.md").write_text("# Hello\n", encoding="utf-8")
            (root / "link.py").symlink_to(root / "src" / "main.py")
            with patch("ingest.cloner.settings.max_file_size_bytes", 2_000_000):
                names = {Path(path).name for path in get_files_to_process(str(root))}
        self.assertEqual(names, {"main.py", "extended.py", "README.md"})

    def test_chunking_preserves_actual_line_ranges_and_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "app.py"
            file_path.write_text("class Login:\n    pass\n\ndef handle_login():\n    return True\n", encoding="utf-8")
            chunks = chunk_file(str(file_path), str(root))
        self.assertEqual(chunks[0]["start_line"], 1)
        self.assertEqual(chunks[0]["end_line"], 5)
        self.assertEqual(chunks[0]["symbols"], ["Login", "handle_login"])
        self.assertEqual(extract_symbols("const signIn = async () => {}"), ["signIn"])

    def test_embed_chunks_uses_hosted_nvidia_embeddings(self):
        chunks = [{"file_path": "src/app.py", "content": "def hello(): pass", "start_line": 1, "end_line": 1, "language": "py"}]
        fake_client = MagicMock()
        fake_client.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.0] * EMBEDDING_DIMENSION)])
        with patch("ingest.embedder.get_embedding_client", return_value=fake_client):
            embedded = embed_chunks(chunks)
        self.assertEqual(len(embedded[0]["embedding"]), EMBEDDING_DIMENSION)
        self.assertEqual(fake_client.embeddings.create.call_args.kwargs["extra_body"]["input_type"], "passage")

    def test_ensure_repo_record_queues_failed_repository_without_erasing_old_index(self):
        from ingest.pipeline import ensure_repo_record
        store = MemoryStore()
        store.rows = [{"id": "repo-1", "status": "failed"}]
        with patch("ingest.pipeline.timestamp", return_value="2026-01-01T00:00:00+00:00"):
            repo_id, name = asyncio.run(ensure_repo_record(store, "https://github.com/octocat/Hello-World", "user-1"))
        self.assertEqual((repo_id, name), ("repo-1", "Hello-World"))
        self.assertNotIn("DELETE FROM chunks", " ".join(sql for sql, _ in store.executed))
        self.assertTrue(all("user-1" in args for _, args in store.executed if args and "repos" in _))

    def test_file_selection_report_discloses_exclusion_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "src" / "large.py").write_text("x" * 120, encoding="utf-8")
            (root / "image.png").write_bytes(b"\x89PNG\x00")
            (root / ".env").write_text("SECRET=x", encoding="utf-8")
            with patch("ingest.cloner.settings.max_file_size_bytes", 100):
                report = get_file_selection_report(str(root))
        self.assertEqual(report["eligible_files"], 1)
        self.assertEqual(report["excluded_reasons"]["file_size_limit"], 1)
        self.assertEqual(report["excluded_reasons"]["unsupported_format"], 1)
        self.assertEqual(report["excluded_reasons"]["hidden"], 1)
        self.assertEqual(set(report["excluded_paths"]), {"src/large.py", "image.png", ".env"})

    def test_evidence_plan_targets_security_paths(self):
        from retrieval.retriever import build_evidence_plan
        plan = build_evidence_plan("How does authentication work?", "security")
        self.assertEqual(plan["workflow"], "security")
        self.assertIn("middleware", plan["path_hints"])
        self.assertIn("auth", plan["search_terms"])

    def test_navigation_question_excludes_readme_and_targets_header_files(self):
        from retrieval.retriever import build_evidence_plan, is_overview_file, retrieve_context

        plan = build_evidence_plan("How do I change the NAV bar design?", "general")
        self.assertIn("header", plan["path_hints"])
        readme = {
            "id": "readme-1", "file_path": "README.md", "start_line": 1, "end_line": 8,
            "language": "md", "symbols": [], "content": "The navigation is described here.",
        }
        header = {
            "id": "header-1", "file_path": "frontend/src/components/SiteHeader.jsx", "start_line": 1,
            "end_line": 24, "language": "jsx", "symbols": ["SiteHeader"],
            "content": "export function SiteHeader() { return <nav />; }",
        }
        footer = {
            "id": "footer-1", "file_path": "frontend/src/components/Footer.jsx", "start_line": 1,
            "end_line": 12, "language": "jsx", "symbols": ["Footer"],
            "content": "export function Footer() { return <footer />; }",
        }

        store = MemoryStore()

        async def fetch_all(sql, args=None):
            store.executed.append((sql, args or []))
            # Simulate a broad keyword match plus targeted path-hint matches.
            return [header] if "LIKE ?" in sql else [readme, header, footer]

        store.fetch_all = fetch_all
        with patch("retrieval.retriever.embed_query", side_effect=EmbeddingUnavailableError("offline")):
            result = asyncio.run(retrieve_context(store, "repo-1", "How do I change the NAV bar design?", top_k=4))

        self.assertTrue(result)
        self.assertTrue(any(chunk["file_path"].endswith("SiteHeader.jsx") for chunk in result))
        self.assertFalse(any(is_overview_file(chunk["file_path"]) for chunk in result))
        self.assertFalse(any(chunk["file_path"].endswith("Footer.jsx") for chunk in result))

    def test_api_location_question_returns_only_api_path_evidence(self):
        from retrieval.retriever import build_evidence_plan, retrieve_context

        question = "Where is the API defined in this project?"
        plan = build_evidence_plan(question)
        self.assertEqual(plan["query_scope"], "targeted_api_location")
        self.assertIn("api", plan["path_hints"])

        readme = {
            "id": "readme-1", "file_path": "README.md", "start_line": 1, "end_line": 12,
            "language": "md", "symbols": [], "content": "The API is described here.",
        }
        route = {
            "id": "route-1", "file_path": "backend/api/routes.py", "start_line": 1, "end_line": 28,
            "language": "py", "symbols": ["router"], "content": "router = APIRouter()",
        }
        unrelated = {
            "id": "service-1", "file_path": "backend/services/users.py", "start_line": 1, "end_line": 18,
            "language": "py", "symbols": ["UserService"], "content": "class UserService: pass",
        }

        store = MemoryStore()

        async def fetch_all(sql, args=None):
            store.executed.append((sql, args or []))
            # Path-hint queries should return only their matching path; broad
            # retrieval simulates the noisy candidates seen in production.
            if "lower(file_path) LIKE ?" in sql:
                return [route]
            return [readme, route, unrelated]

        store.fetch_all = fetch_all
        with patch("retrieval.retriever.embed_query", side_effect=EmbeddingUnavailableError("offline")):
            result = asyncio.run(retrieve_context(store, "repo-1", question, top_k=4))

        self.assertEqual([chunk["file_path"] for chunk in result], ["backend/api/routes.py"])

    def test_sparse_terms_ignore_question_stopwords(self):
        from retrieval.retriever import search_terms

        terms = search_terms("Where does the API live in this project?")
        self.assertIn("api", terms)
        self.assertNotIn("where", terms)
        self.assertNotIn("does", terms)
        self.assertNotIn("the", terms)

    def test_dependency_manifest_resolves_only_local_imports(self):
        from ingest.dependencies import build_dependency_manifest
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            entry = root / "src" / "main.py"
            auth = root / "src" / "auth.py"
            entry.write_text("from src.auth import login\n", encoding="utf-8")
            auth.write_text("def login(): pass\n", encoding="utf-8")
            edges = build_dependency_manifest([str(entry), str(auth)], str(root))
        self.assertEqual(edges[0]["source_file"], "src/main.py")
        self.assertEqual(edges[0]["target_file"], "src/auth.py")

    def test_dependency_manifest_resolves_relative_imports(self):
        from ingest.dependencies import build_dependency_manifest
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg").mkdir()
            entry = root / "pkg" / "main.py"
            auth = root / "pkg" / "auth.py"
            entry.write_text("from .auth import login\n", encoding="utf-8")
            auth.write_text("def login(): pass\n", encoding="utf-8")
            edges = build_dependency_manifest([str(entry), str(auth)], str(root))
        self.assertEqual(edges[0]["target_file"], "pkg/auth.py")

    def test_file_manifest_changes_only_when_content_changes(self):
        from ingest.pipeline import build_file_manifest
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "app.py"
            source.write_text("print('one')\n", encoding="utf-8")
            first = build_file_manifest([str(source)], str(root))
            source.write_text("print('two')\n", encoding="utf-8")
            second = build_file_manifest([str(source)], str(root))
        self.assertEqual(set(first), {"app.py"})
        self.assertNotEqual(first["app.py"]["content_hash"], second["app.py"]["content_hash"])

    def test_impact_retrieval_query_is_parameterized(self):
        from retrieval.retriever import dependent_file_chunks

        store = MemoryStore()
        store.fetch_all = AsyncMock(return_value=[{"id": "caller", "file_path": "src/main.py"}])
        rows = asyncio.run(dependent_file_chunks(store, "repo-1", ["auth.py"]))
        self.assertEqual(rows[0]["id"], "caller")
        sql, args = store.fetch_all.call_args.args
        self.assertIn("repo_dependencies", sql)
        self.assertEqual(args[:3], ["repo-1", "auth.py", "%/auth.py"])

    def test_worker_claim_keeps_turso_row_as_plain_mapping(self):
        from ingest.pipeline import claim_next_ingestion_job

        class ClaimStore(MemoryStore):
            async def fetch_all(self, sql, args=None):
                return []

            async def execute(self, sql, args=None):
                self.executed.append((sql, args or []))
                return SimpleNamespace(rows=[{
                    "id": "job-1", "repo_id": "repo-1", "user_id": "user-1",
                    "github_url": "https://github.com/octocat/Hello-World.git", "attempts": 1,
                }], rows_affected=1)

        job = asyncio.run(claim_next_ingestion_job(ClaimStore()))
        self.assertEqual(job["id"], "job-1")
        self.assertIn("claim_token", job)

    def test_retrieval_prioritizes_requested_file_and_survives_missing_embeddings(self):
        from retrieval.retriever import retrieve_context
        store = MemoryStore()
        schema = [{"id": "schema-1", "file_path": "sql/schema.sql", "start_line": 1, "end_line": 2, "language": "sql", "symbols": [], "content": "CREATE TABLE repos"}]
        store.fetch_all = AsyncMock(side_effect=[[], schema])
        with patch("retrieval.retriever.embed_query", side_effect=EmbeddingUnavailableError("offline")):
            result = asyncio.run(retrieve_context(store, "repo-1", "show sql/schema.sql", top_k=2))
        self.assertEqual([chunk["id"] for chunk in result], ["schema-1"])

    def test_technical_question_does_not_force_a_readme_citation(self):
        from retrieval.retriever import is_exploratory_repository_question, retrieve_context

        self.assertFalse(is_exploratory_repository_question("Explain how authentication works", []))
        auth_chunk = [{
            "id": "auth-1", "file_path": "backend/api/auth.py", "start_line": 12, "end_line": 30,
            "language": "py", "symbols": ["get_current_user"], "content": "def get_current_user(): pass",
        }]
        store = MemoryStore()
        store.fetch_all = AsyncMock(return_value=auth_chunk)
        with patch("retrieval.retriever.embed_query", side_effect=EmbeddingUnavailableError("offline")):
            result = asyncio.run(retrieve_context(store, "repo-1", "Explain how authentication works", top_k=4))
        self.assertEqual([chunk["file_path"] for chunk in result], ["backend/api/auth.py"])
        self.assertFalse(any("readme" in sql.lower() for sql, _ in store.executed))

    def test_query_endpoint_persists_user_and_assistant_messages(self):
        from api.query_router import query_repo
        store = MemoryStore()
        user = SimpleNamespace(id="user-1")
        request = SimpleNamespace(repo_name="demo", question="Where is login?", model_profile="fast")
        chunks = [{"id": "chunk-1", "file_path": "src/auth.py", "start_line": 1, "end_line": 5, "language": "py", "symbols": ["login"], "content": "def login(): pass"}]
        with patch("api.query_router.assert_turso_schema", new=AsyncMock()), \
             patch("api.query_router.get_turso_store", return_value=store), \
             patch("api.query_router.get_owned_repo", new=AsyncMock(return_value={"id": "repo-1", "status": "ready"})), \
             patch("api.query_router.retrieve_context", new=AsyncMock(return_value=chunks)), \
             patch("api.query_router.get_conversation_history", new=AsyncMock(return_value=[])), \
             patch("api.query_router.run_agent_loop", new=AsyncMock(return_value=("## Direct answer\nLogin is in auth.py.", []))):
            response = asyncio.run(query_repo(request, user))
        self.assertEqual(response["mode"], "rag")
        self.assertEqual(response["citations"][0]["support_status"], "source-backed")
        self.assertTrue(response["citations"][0]["retrieval_reasons"])
        self.assertEqual(sum("INSERT INTO chat_messages" in sql for sql, _ in store.executed), 2)

    def test_query_response_exposes_the_selected_evidence_workflow(self):
        from api.query_router import query_repo
        store = MemoryStore()
        user = SimpleNamespace(id="user-1")
        request = SimpleNamespace(repo_name="demo", question="Review authentication", model_profile="fast", workflow="security")
        chunks = [{"id": "chunk-1", "file_path": "src/auth.py", "start_line": 1, "end_line": 5, "language": "py", "symbols": [], "content": "def login(): pass", "_retrieval_reasons": ["Security review target matching the 'auth' path hint"]}]
        with patch("api.query_router.assert_turso_schema", new=AsyncMock()), \
             patch("api.query_router.get_turso_store", return_value=store), \
             patch("api.query_router.get_owned_repo", new=AsyncMock(return_value={"id": "repo-1", "status": "ready"})), \
             patch("api.query_router.retrieve_context", new=AsyncMock(return_value=chunks)), \
             patch("api.query_router.get_conversation_history", new=AsyncMock(return_value=[])), \
             patch("api.query_router.run_agent_loop", new=AsyncMock(return_value=("## Direct answer\nAuthentication is in auth.py.", []))):
            response = asyncio.run(query_repo(request, user))
        self.assertEqual(response["workflow"], "security")
        self.assertEqual(response["evidence_plan"]["workflow"], "security")

    def test_query_returns_guidance_without_matching_source(self):
        from api.query_router import query_repo
        store = MemoryStore()
        user = SimpleNamespace(id="user-1")
        request = SimpleNamespace(repo_name="demo", question="Explain the deployment topology", model_profile="fast")
        with patch("api.query_router.assert_turso_schema", new=AsyncMock()), \
             patch("api.query_router.get_turso_store", return_value=store), \
             patch("api.query_router.get_owned_repo", new=AsyncMock(return_value={"id": "repo-1", "status": "ready"})), \
             patch("api.query_router.retrieve_context", new=AsyncMock(return_value=[])), \
             patch("api.query_router.get_conversation_history", new=AsyncMock(return_value=[])):
            response = asyncio.run(query_repo(request, user))
        self.assertEqual(response["mode"], "repository_guidance")
        self.assertIn("explore this repository", response["answer"])

    def test_greeting_skips_retrieval_and_never_calls_the_answer_model(self):
        from api.query_router import query_repo
        store = MemoryStore()
        user = SimpleNamespace(id="user-1")
        request = SimpleNamespace(repo_name="demo", question="hi", model_profile="fast")
        with patch("api.query_router.assert_turso_schema", new=AsyncMock()), \
             patch("api.query_router.get_turso_store", return_value=store), \
             patch("api.query_router.get_owned_repo", new=AsyncMock(return_value={"id": "repo-1", "status": "ready"})), \
             patch("api.query_router.retrieve_context", new=AsyncMock()) as retrieve, \
             patch("api.query_router.run_agent_loop", new=AsyncMock()) as answer_model:
            response = asyncio.run(query_repo(request, user))
        self.assertEqual(response["mode"], "greeting")
        self.assertEqual(response["citations"], [])
        self.assertIn("What would you like to understand", response["answer"])
        retrieve.assert_not_awaited()
        answer_model.assert_not_awaited()

    def test_provider_planning_is_rejected_before_it_reaches_chat_history(self):
        from agent.nemotron import LLMProviderError, user_facing_content
        with self.assertRaises(LLMProviderError):
            user_facing_content("The user said 'hi'. I should respond politely without citations.")
        self.assertEqual(user_facing_content("<think>private plan</think>\nHello."), "Hello.")

    def test_recover_stuck_repos_fixes_intermediate_status_when_job_completed(self):
        from ingest.pipeline import recover_stuck_repos

        class RecoveryStore(MemoryStore):
            async def fetch_all(self, sql, args=None):
                self.executed.append((sql, args or []))
                # Return one stuck repo: status='embedding' but job='completed'
                return [{"id": "repo-stuck", "status": "embedding", "job_status": "completed"}]

            async def fetch_one(self, sql, args=None):
                self.executed.append((sql, args or []))
                return {"count": 42, "error_message": None}

        store = RecoveryStore()
        recovered = asyncio.run(recover_stuck_repos(store))
        self.assertEqual(recovered, 1)
        # Verify the repo was updated to 'ready' with the correct chunk count
        update_calls = [(sql, args) for sql, args in store.executed if "UPDATE repos SET" in sql]
        self.assertEqual(len(update_calls), 1)
        update_sql, update_args = update_calls[0]
        self.assertIn("status = ?", update_sql)
        self.assertIn("ready", update_args)
        self.assertIn(42, update_args)

    def test_recover_stuck_repos_returns_zero_when_no_stuck_repos(self):
        from ingest.pipeline import recover_stuck_repos

        class EmptyStore(MemoryStore):
            async def fetch_all(self, sql, args=None):
                self.executed.append((sql, args or []))
                return []

        store = EmptyStore()
        recovered = asyncio.run(recover_stuck_repos(store))
        self.assertEqual(recovered, 0)
        # No repo UPDATE should have been issued
        update_calls = [(sql, args) for sql, args in store.executed if "UPDATE repos SET" in sql]
        self.assertEqual(len(update_calls), 0)

    def test_finalize_successful_job_prefetches_data_before_job_update(self):
        from ingest.pipeline import finalize_successful_job

        call_order = []

        class FinalizeStore(MemoryStore):
            async def fetch_one(self, sql, args=None):
                self.executed.append((sql, args or []))
                if "SELECT COUNT" in sql:
                    call_order.append("fetch_chunk_count")
                    return {"count": 10}
                if "SELECT error_message" in sql:
                    call_order.append("fetch_error_message")
                    return {"error_message": None}
                return None

            async def execute(self, sql, args=None):
                self.executed.append((sql, args or []))
                if "UPDATE ingestion_jobs SET status = 'completed'" in sql:
                    call_order.append("job_update")
                    return SimpleNamespace(rows=[{"id": "job-1"}], rows_affected=1)
                if "UPDATE repos SET" in sql:
                    call_order.append("repo_update")
                    return SimpleNamespace(rows=[], rows_affected=1)
                return SimpleNamespace(rows=[], rows_affected=1)

        store = FinalizeStore()
        job = {"id": "job-1", "repo_id": "repo-1", "claim_token": "token-1"}
        result = asyncio.run(finalize_successful_job(store, job))
        self.assertTrue(result)
        # Critical: data must be fetched BEFORE the job UPDATE, and repo UPDATE after
        self.assertEqual(call_order, ["fetch_chunk_count", "fetch_error_message", "job_update", "repo_update"])


if __name__ == "__main__":
    unittest.main()
