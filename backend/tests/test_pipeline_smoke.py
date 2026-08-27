import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from ingest.chunker import chunk_file, extract_symbols
from ingest.cloner import RepositoryValidationError, get_files_to_process, normalize_github_url
from ingest.embedder import EMBEDDING_DIMENSION, embed_chunks


class BackendSmokeTests(unittest.TestCase):
    @staticmethod
    def _query(data):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.delete.return_value = query
        query.insert.return_value = query
        query.execute.return_value = SimpleNamespace(data=data)
        return query

    def test_app_imports_and_root_endpoint_works(self):
        from main import app

        client = TestClient(app)
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/api/health").json(), {"status": "ok"})

    def test_answer_model_profiles_are_allow_listed(self):
        from api.query_router import QueryRequest
        from config import get_answer_model_options
        from pydantic import ValidationError

        self.assertEqual(get_answer_model_options("fast")[0], "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(get_answer_model_options("detailed")[0], "nvidia/nemotron-3-ultra-550b-a55b")
        with self.assertRaises(ValidationError):
            QueryRequest(repo_name="demo", question="Where is login?", model_profile="untrusted/model")

    def test_github_url_normalization_rejects_non_repository_urls(self):
        self.assertEqual(
            normalize_github_url(" https://github.com/octocat/Hello-World/ "),
            "https://github.com/octocat/Hello-World.git",
        )
        for value in ("http://github.com/a/b", "https://github.com/a/b/tree/main", "https://evil.test/a/b"):
            with self.assertRaises(RepositoryValidationError):
                normalize_github_url(value)

    def test_failed_repository_can_be_requeued_with_the_same_url(self):
        from ingest.pipeline import ensure_repo_record

        supabase_client = MagicMock()
        existing = SimpleNamespace(data=[{"id": "repo-1", "status": "failed"}])
        with patch(
            "ingest.pipeline.run_query",
            new=AsyncMock(side_effect=[existing, SimpleNamespace(data=[]), SimpleNamespace(data=[]), SimpleNamespace(data=[])]),
        ):
            repo_id, repo_name = asyncio.run(
                ensure_repo_record(supabase_client, "https://github.com/octocat/Hello-World", "user-1")
            )

        self.assertEqual((repo_id, repo_name), ("repo-1", "Hello-World"))
        self.assertEqual(
            [call.args[0] for call in supabase_client.table.call_args_list],
            ["repos", "repos", "chunks", "kt_cache"],
        )

    def test_get_files_to_process_accepts_larger_source_files_and_skips_oversized_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "src" / "extended.py").write_text("x" * 1_100_000, encoding="utf-8")
            (root / "src" / "oversized.py").write_text("x" * 2_000_001, encoding="utf-8")
            (root / "package-lock.json").write_text('{"lock": true}', encoding="utf-8")
            (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
            (root / "bundle.min.js").write_text("var a=1;", encoding="utf-8")
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

    def test_chunk_file_splits_minified_content_into_multiple_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "app.js"
            file_path.write_text("const data='" + ("x" * 30000) + "';", encoding="utf-8")
            chunks = chunk_file(str(file_path), str(root))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk["content"] for chunk in chunks))

    def test_embed_chunks_uses_hosted_nvidia_embeddings(self):
        chunks = [{"file_path": "src/app.py", "content": "def hello(): pass", "start_line": 1, "end_line": 1, "language": "py"}]
        fake_client = MagicMock()
        fake_client.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(index=0, embedding=[0.0] * EMBEDDING_DIMENSION)]
        )
        with patch("ingest.embedder.get_embedding_client", return_value=fake_client):
            embedded = embed_chunks(chunks)
        self.assertEqual(len(embedded[0]["embedding"]), EMBEDDING_DIMENSION)
        self.assertEqual(fake_client.embeddings.create.call_args.kwargs["extra_body"]["input_type"], "passage")

    def test_embed_chunks_uses_configured_small_batches(self):
        chunks = [
            {"file_path": f"src/file_{index}.py", "content": "def example(): pass", "start_line": 1, "end_line": 1, "language": "py"}
            for index in range(9)
        ]
        fake_client = MagicMock()

        def embeddings_for_batch(*, input, **_kwargs):
            return SimpleNamespace(
                data=[SimpleNamespace(index=index, embedding=[float(index)] * EMBEDDING_DIMENSION) for index in range(len(input))]
            )

        fake_client.embeddings.create.side_effect = embeddings_for_batch
        with patch("ingest.embedder.get_embedding_client", return_value=fake_client), \
             patch("ingest.embedder.settings.embedding_batch_size", 4):
            embedded = embed_chunks(chunks)

        self.assertEqual(len(embedded), 9)
        self.assertEqual(fake_client.embeddings.create.call_count, 3)
        self.assertEqual(
            [len(call.kwargs["input"]) for call in fake_client.embeddings.create.call_args_list],
            [4, 4, 1],
        )

    def test_embedding_request_retries_transient_nvidia_failure(self):
        from httpx import Request, Response
        from openai import APIStatusError
        from ingest.embedder import embed_texts

        transient_error = APIStatusError(
            "Service unavailable",
            response=Response(503, request=Request("POST", "https://integrate.api.nvidia.com/v1/embeddings")),
            body=None,
        )
        fake_client = MagicMock()
        fake_client.embeddings.create.side_effect = [
            transient_error,
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.0] * EMBEDDING_DIMENSION)]),
        ]
        with patch("ingest.embedder.get_embedding_client", return_value=fake_client), \
                 patch("ingest.embedder.wait_for_embedding_slot"), \
             patch("ingest.embedder.time.sleep"):
            vectors = embed_texts(["retry this embedding"], input_type="passage")

        self.assertEqual(len(vectors[0]), EMBEDDING_DIMENSION)
        self.assertEqual(fake_client.embeddings.create.call_count, 2)

    def test_embedding_retry_honors_nvidia_retry_after_header(self):
        from httpx import Request, Response
        from openai import APIStatusError
        from ingest.embedder import embed_texts

        transient_error = APIStatusError(
            "Service unavailable",
            response=Response(503, headers={"retry-after": "7"}, request=Request("POST", "https://integrate.api.nvidia.com/v1/embeddings")),
            body=None,
        )
        fake_client = MagicMock()
        fake_client.embeddings.create.side_effect = [
            transient_error,
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.0] * EMBEDDING_DIMENSION)]),
        ]
        with patch("ingest.embedder.get_embedding_client", return_value=fake_client), \
                 patch("ingest.embedder.wait_for_embedding_slot"), \
             patch("ingest.embedder.time.sleep") as sleep:
            embed_texts(["retry this embedding"], input_type="passage")

        sleep.assert_called_once_with(7.0)

    def test_embedding_pipeline_reports_progress_for_every_batch(self):
        from ingest.pipeline import embed_repository_chunks

        chunks = [{"file_path": f"file_{index}.py", "content": "pass"} for index in range(5)]
        query = MagicMock()
        query.update.return_value = query
        query.eq.return_value = query
        query.execute.return_value = SimpleNamespace(data=[])
        supabase_client = MagicMock()
        supabase_client.table.return_value = query

        with patch("ingest.pipeline.raise_if_ingestion_cancelled", new=AsyncMock()), \
             patch("ingest.pipeline.run_blocking", new=AsyncMock(side_effect=lambda _func, batch: batch)), \
             patch("ingest.pipeline.run_query", new=AsyncMock()), \
             patch("ingest.pipeline.settings.embedding_batch_size", 2):
            result = asyncio.run(embed_repository_chunks(supabase_client, "repo-1", chunks))

        self.assertEqual(result, chunks)
        progress_messages = [call.args[0]["error_message"] for call in query.update.call_args_list]
        self.assertEqual(progress_messages, [
            "Indexing 0 of 5 code sections (0%). Large repositories can take a few minutes while embeddings are created.",
            "Indexing 2 of 5 code sections (40%). Large repositories can take a few minutes while embeddings are created.",
            "Indexing 4 of 5 code sections (80%). Large repositories can take a few minutes while embeddings are created.",
            "Indexing 5 of 5 code sections (100%). Large repositories can take a few minutes while embeddings are created.",
        ])

    def test_cancelled_job_is_detected_before_the_next_pipeline_stage(self):
        from ingest.pipeline import IngestionCancelledError, raise_if_ingestion_cancelled

        with patch(
            "ingest.pipeline.run_query",
            new=AsyncMock(return_value=SimpleNamespace(data=[{"status": "cancelled"}])),
        ):
            with self.assertRaises(IngestionCancelledError):
                asyncio.run(raise_if_ingestion_cancelled(MagicMock(), "repo-1"))

    def test_nemotron_request_uses_required_model_and_hides_reasoning(self):
        from agent.nemotron import complete
        fake_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Grounded answer", reasoning_content="private"))])
        fake_client = MagicMock()
        fake_client.chat.completions.create = AsyncMock(return_value=fake_response)
        fake_client.close = AsyncMock()

        async def run_test():
            with patch("agent.nemotron.require_nvidia_api_key", return_value="test-key"), \
                 patch("agent.nemotron.AsyncOpenAI", return_value=fake_client):
                return await complete([{"role": "user", "content": "Question"}])

        self.assertEqual(asyncio.run(run_test()), "Grounded answer")
        request = fake_client.chat.completions.create.await_args.kwargs
        self.assertEqual(request["model"], "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(request["max_tokens"], 900)
        self.assertEqual(
            request["extra_body"],
            {"chat_template_kwargs": {"enable_thinking": False, "force_nonempty_content": True}},
        )

    def test_nemotron_retries_a_transient_generation_failure(self):
        from httpx import Request, Response
        from openai import APIStatusError
        from agent.nemotron import complete

        transient_error = APIStatusError(
            "Service unavailable",
            response=Response(503, request=Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")),
            body=None,
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create = AsyncMock(side_effect=[
            transient_error,
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Recovered answer"))]),
        ])
        fake_client.close = AsyncMock()

        async def run_test():
            with patch("agent.nemotron.require_nvidia_api_key", return_value="test-key"), \
                 patch("agent.nemotron.AsyncOpenAI", return_value=fake_client), \
                 patch("agent.nemotron.nvidia_rate_limiter.acquire", new=AsyncMock()), \
                 patch("agent.nemotron.asyncio.sleep", new=AsyncMock()):
                return await complete([{"role": "user", "content": "Question"}])

        self.assertEqual(asyncio.run(run_test()), "Recovered answer")
        self.assertEqual(fake_client.chat.completions.create.await_count, 2)

    def test_grounded_answer_prompt_requests_plain_text_sections(self):
        from agent.agent import run_agent_loop

        async def run_test():
            with patch("agent.agent.complete", new=AsyncMock(return_value="Structured answer")) as complete:
                answer, trace = await run_agent_loop(None, "repo-1", "Where is login?", "File: src/auth.py (L1-L2)")
            return answer, trace, complete.await_args.args[0]

        answer, trace, messages = asyncio.run(run_test())
        self.assertEqual(answer, "Structured answer")
        self.assertEqual(trace, [])
        prompt = messages[0]["content"]
        self.assertIn("Relevant files", prompt)
        self.assertIn("How it works", prompt)
        self.assertIn("client renders standard Markdown", prompt)
        self.assertIn("## Relevant files", prompt)

    def test_grounded_answer_includes_recent_conversation_without_replacing_evidence(self):
        from agent.agent import run_agent_loop

        async def run_test():
            with patch("agent.agent.complete", new=AsyncMock(return_value="Follow-up answer")) as complete:
                await run_agent_loop(
                    None,
                    "repo-1",
                    "What about that handler?",
                    "File: src/auth.py (L1-L2)",
                    [{"role": "user", "content": "Where is login?"}, {"role": "assistant", "content": "It is in auth.py."}],
                )
                return complete.await_args.args[0]

        messages = asyncio.run(run_test())
        self.assertEqual(messages[1], {"role": "user", "content": "Where is login?"})
        self.assertEqual(messages[2], {"role": "assistant", "content": "It is in auth.py."})
        self.assertIn("sole source for factual claims", messages[3]["content"])
        self.assertIn("File: src/auth.py", messages[3]["content"])

    def test_hybrid_retrieval_deduplicates_and_keeps_readme_within_limit(self):
        from retrieval.retriever import retrieve_context

        dense = [{"id": "a", "file_path": "src/auth.py", "start_line": 1, "end_line": 2, "language": "py", "content": "auth"}]
        sparse = [{"id": "a", "file_path": "src/auth.py", "start_line": 1, "end_line": 2, "language": "py", "content": "auth"},
                  {"id": "b", "file_path": "src/login.py", "start_line": 4, "end_line": 8, "language": "py", "content": "login"}]
        readme = [{"id": "readme", "file_path": "README.md", "start_line": 1, "end_line": 3, "language": "md", "content": "overview"}]

        class FakeRequest:
            def __init__(self, data):
                self.data = data
            def execute(self):
                return SimpleNamespace(data=self.data)
            def select(self, *_args): return self
            def eq(self, *_args): return self
            def ilike(self, *_args): return self
            def order(self, *_args): return self
            def limit(self, *_args): return self

        class FakeSupabase:
            def rpc(self, name, _args):
                return FakeRequest(dense if name.endswith("dense") else sparse)
            def table(self, _name):
                return FakeRequest(readme)

        async def run_test():
            with patch("retrieval.retriever.embed_query", return_value=[0.0] * EMBEDDING_DIMENSION):
                return await retrieve_context(FakeSupabase(), "repo-1", "what is this codebase architecture?", top_k=2)
        results = asyncio.run(run_test())
        self.assertEqual([chunk["id"] for chunk in results], ["readme", "a"])

    def test_file_path_question_prioritizes_requested_source_chunks(self):
        from retrieval.retriever import retrieve_context

        dense = [{"id": "other", "file_path": "README.md", "start_line": 1, "end_line": 2, "language": "md", "content": "overview"}]
        sparse = [{"id": "other", "file_path": "README.md", "start_line": 1, "end_line": 2, "language": "md", "content": "overview"}]
        schema = [
            {"id": "schema-1", "file_path": "sql/schema.sql", "start_line": 1, "end_line": 4, "language": "sql", "symbols": [], "content": "create table repos"},
            {"id": "schema-2", "file_path": "sql/schema.sql", "start_line": 5, "end_line": 8, "language": "sql", "symbols": [], "content": "create table chunks"},
        ]

        class FakeRequest:
            def __init__(self, data):
                self.data = data
                self.path_filter = None
            def execute(self):
                if self.path_filter == "sql/schema.sql":
                    return SimpleNamespace(data=schema)
                return SimpleNamespace(data=self.data)
            def select(self, *_args): return self
            def eq(self, *_args): return self
            def ilike(self, _column, value):
                self.path_filter = value
                return self
            def order(self, *_args): return self
            def limit(self, *_args): return self

        class FakeSupabase:
            def rpc(self, name, _args):
                return FakeRequest(dense if name.endswith("dense") else sparse)
            def table(self, _name):
                return FakeRequest([])

        async def run_test():
            with patch("retrieval.retriever.embed_query", return_value=[0.0] * EMBEDDING_DIMENSION):
                return await retrieve_context(FakeSupabase(), "repo-1", "Show me sql/schema.sql", top_k=2)

        results = asyncio.run(run_test())
        self.assertEqual([chunk["id"] for chunk in results], ["schema-1", "schema-2"])

    def test_keyword_retrieval_remains_available_when_query_embeddings_are_unavailable(self):
        from ingest.embedder import EmbeddingUnavailableError
        from retrieval.retriever import retrieve_context

        sparse = [{"id": "sparse", "file_path": "src/login.py", "start_line": 1, "end_line": 2, "language": "py", "content": "login handler"}]

        class FakeRequest:
            def __init__(self, data): self.data = data
            def execute(self): return SimpleNamespace(data=self.data)
            def select(self, *_args): return self
            def eq(self, *_args): return self
            def ilike(self, *_args): return self
            def order(self, *_args): return self
            def limit(self, *_args): return self

        class FakeSupabase:
            def rpc(self, name, _args):
                if name != "match_chunks_sparse":
                    raise AssertionError(f"Unexpected retrieval RPC: {name}")
                return FakeRequest(sparse)
            def table(self, _name): return FakeRequest([])

        async def run_test():
            with patch("retrieval.retriever.embed_query", side_effect=EmbeddingUnavailableError("503")):
                return await retrieve_context(FakeSupabase(), "repo-1", "where is login", top_k=2)

        results = asyncio.run(run_test())
        self.assertEqual([chunk["id"] for chunk in results], ["sparse"])

    def test_query_returns_retrieved_evidence_when_nvidia_is_not_configured(self):
        from config import ModelConfigurationError
        from main import app
        from api.auth import get_current_user

        repo_query = self._query([{"id": "repo-1", "status": "ready"}])
        fake_supabase = MagicMock()
        fake_supabase.table.return_value = repo_query
        chunks = [{
            "id": "chunk-1", "file_path": "src/auth.py", "start_line": 10, "end_line": 20,
            "language": "py", "symbols": ["login"], "content": "def login(): pass",
        }]
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.query_router.assert_supabase_schema"), \
             patch("api.query_router.get_user_scoped_supabase", return_value=fake_supabase), \
             patch("api.query_router.retrieve_context", new=AsyncMock(return_value=chunks)), \
             patch("api.query_router.run_agent_loop", new=AsyncMock(side_effect=ModelConfigurationError("NVIDIA is not configured."))):
            response = TestClient(app).post("/api/query", json={"repo_name": "demo", "question": "Where is login?"})
        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "retrieval_fallback")

    def test_schema_check_turns_missing_symbol_column_into_actionable_error(self):
        from database import DatabaseConfigurationError, assert_supabase_schema
        from postgrest.exceptions import APIError

        query = MagicMock()
        query.select.return_value = query
        query.limit.return_value = query
        query.execute.side_effect = [
            SimpleNamespace(data=[]),
            APIError({"message": "column chunks.symbols does not exist", "code": "42703"}),
        ]
        fake_supabase = MagicMock()
        fake_supabase.table.return_value = query
        assert_supabase_schema.cache_clear()
        with patch("database.supabase", fake_supabase):
            with self.assertRaisesRegex(DatabaseConfigurationError, "Run supabase/00_init.sql"):
                assert_supabase_schema()
        assert_supabase_schema.cache_clear()

    def test_embedding_dimension_mismatch_has_an_actionable_migration_message(self):
        from database import explain_supabase_api_error
        from postgrest.exceptions import APIError

        message = explain_supabase_api_error(
            APIError({"message": "expected 1024 dimensions, not 2048", "code": "22000"})
        )
        self.assertIn("supabase/00_init.sql", message)
        self.assertIn("2048-dimensional", message)

    def test_query_returns_grounded_answer_and_citations(self):
        from main import app
        from api.auth import get_current_user

        repo_query = self._query([{"id": "repo-1", "status": "ready"}])
        fake_supabase = MagicMock()
        fake_supabase.table.return_value = repo_query
        chunks = [{
            "id": "chunk-1", "file_path": "src/auth.py", "start_line": 10, "end_line": 20,
            "language": "py", "symbols": ["login"], "content": "def login(): pass",
        }]
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.query_router.assert_supabase_schema"), \
             patch("api.query_router.require_nvidia_api_key", return_value="test-key"), \
             patch("api.query_router.get_user_scoped_supabase", return_value=fake_supabase), \
             patch("api.query_router.retrieve_context", new=AsyncMock(return_value=chunks)), \
             patch("api.query_router.run_agent_loop", new=AsyncMock(return_value=("Login is in src/auth.py (L10-L20).", []))):
            response = TestClient(app).post("/api/query", json={"repo_name": "demo", "question": "Where is login?"})
        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "rag")
        self.assertEqual(response.json()["citations"][0]["end_line"], 20)
        fake_supabase.table.assert_any_call("chat_messages")
        saved_messages = repo_query.insert.call_args.args[0]
        self.assertEqual(saved_messages[0]["role"], "user")
        self.assertEqual(saved_messages[0]["citations"], [])
        self.assertEqual(saved_messages[0]["tool_calls"], [])

    def test_query_returns_retrieved_evidence_when_live_generation_is_unavailable(self):
        from main import app
        from api.auth import get_current_user
        from agent.nemotron import LLMProviderError

        repo_query = self._query([{"id": "repo-1", "status": "ready"}])
        fake_supabase = MagicMock()
        fake_supabase.table.return_value = repo_query
        chunks = [{
            "id": "chunk-1", "file_path": "src/auth.py", "start_line": 10, "end_line": 20,
            "language": "py", "symbols": ["login"], "content": "def login(): pass",
        }]
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.query_router.assert_supabase_schema"), \
             patch("api.query_router.get_user_scoped_supabase", return_value=fake_supabase), \
             patch("api.query_router.retrieve_context", new=AsyncMock(return_value=chunks)), \
             patch("api.query_router.run_agent_loop", new=AsyncMock(side_effect=LLMProviderError("503"))):
            response = TestClient(app).post("/api/query", json={"repo_name": "demo", "question": "Where is login?"})
        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "retrieval_fallback")
        self.assertIn("Retrieved code context", response.json()["answer"])

    def test_conversation_endpoint_returns_saved_messages_in_chronological_order(self):
        from main import app
        from api.auth import get_current_user

        repo_query = self._query([{"id": "repo-1", "status": "ready"}])
        history_query = self._query([
            {"id": "m-2", "role": "assistant", "content": "The answer.", "citations": [], "tool_calls": [], "mode": "rag", "latency_ms": 42, "created_at": "2026-01-01T00:00:02Z"},
            {"id": "m-1", "role": "user", "content": "The question.", "citations": [], "tool_calls": [], "mode": None, "latency_ms": None, "created_at": "2026-01-01T00:00:01Z"},
        ])
        fake_supabase = MagicMock()
        fake_supabase.table.side_effect = lambda table: repo_query if table == "repos" else history_query
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.query_router.assert_supabase_schema"), \
             patch("api.query_router.get_user_scoped_supabase", return_value=fake_supabase):
            response = TestClient(app).get("/api/conversations/demo")
        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([message["role"] for message in response.json()["messages"]], ["user", "assistant"])

    def test_repository_endpoints_return_compatible_payloads(self):
        from main import app
        from api.auth import get_current_user

        repo = {"id": "repo-1", "repo_name": "demo", "status": "ready", "chunk_count": 4, "error_message": None}
        fake_supabase = MagicMock()
        fake_supabase.table.return_value = self._query([repo])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.repos_router.scoped_client", new=AsyncMock(return_value=fake_supabase)):
            client = TestClient(app)
            status_response = client.get("/api/status/demo")
            list_response = client.get("/api/repos")
            delete_response = client.delete("/api/repos/demo")
        app.dependency_overrides.clear()
        self.assertEqual(status_response.json()["chunk_count"], 4)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(delete_response.status_code, 200)

    def test_ingest_endpoint_validates_url_before_creating_record(self):
        from main import app
        from api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.ingest_router.assert_supabase_schema"), patch("api.ingest_router.ensure_repo_record", new=AsyncMock()) as ensure:
            response = TestClient(app).post("/api/ingest", json={"github_url": "https://github.com/o/r/tree/main"})
        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 400)
        ensure.assert_not_awaited()

    def test_ingest_endpoint_queues_valid_repository(self):
        from main import app
        from api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.ingest_router.assert_supabase_schema"), \
             patch("api.ingest_router.get_ingestion_supabase_client", return_value=MagicMock()), \
             patch("api.ingest_router.ensure_repo_record", new=AsyncMock(return_value=("repo-1", "demo"))), \
             patch("api.ingest_router.enqueue_ingestion_job", new=AsyncMock()) as enqueue:
            response = TestClient(app).post("/api/ingest", json={"github_url": "https://github.com/octocat/demo"})
        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["repo_name"], "demo")
        enqueue.assert_awaited_once()

    def test_ingest_endpoint_explains_missing_service_role_key(self):
        from database import DatabaseConfigurationError
        from main import app
        from api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.ingest_router.assert_supabase_schema"), \
             patch(
                 "api.ingest_router.get_ingestion_supabase_client",
                 side_effect=DatabaseConfigurationError("Repository indexing requires SUPABASE_SERVICE_ROLE_KEY."),
             ):
            response = TestClient(app).post("/api/ingest", json={"github_url": "https://github.com/octocat/demo"})
        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 503)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", response.json()["detail"])

    def test_cancel_endpoint_marks_an_active_repository_stopped(self):
        from main import app
        from api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.repos_router.assert_supabase_schema"), \
             patch("api.repos_router.get_ingestion_supabase_client", return_value=MagicMock()), \
             patch(
                 "api.repos_router.run_query",
                 new=AsyncMock(side_effect=[
                     SimpleNamespace(data=[{"id": "repo-1", "status": "embedding"}]),
                     SimpleNamespace(data=[]),
                     SimpleNamespace(data=[]),
                     SimpleNamespace(data=[]),
                     SimpleNamespace(data=[]),
                 ]),
             ):
            response = TestClient(app).post("/api/repos/demo/cancel-indexing")
        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Indexing stopped")

    def test_reindex_endpoint_uses_the_existing_user_scoped_repository(self):
        from main import app
        from api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        with patch("api.repos_router.assert_supabase_schema"), \
             patch("api.repos_router.get_ingestion_supabase_client", return_value=MagicMock()), \
             patch("api.repos_router.run_query", new=AsyncMock(return_value=SimpleNamespace(data=[{"github_url": "https://github.com/octocat/demo.git"}]))), \
             patch("api.repos_router.ensure_repo_record", new=AsyncMock(return_value=("repo-1", "demo"))), \
             patch("api.repos_router.enqueue_ingestion_job", new=AsyncMock()) as enqueue:
            response = TestClient(app).post("/api/repos/demo/reindex")
        app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["repo_name"], "demo")
        enqueue.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
