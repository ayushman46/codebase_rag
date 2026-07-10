import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from ingest.chunker import chunk_file
from ingest.embedder import EMBEDDING_DIMENSION, embed_chunks
from ingest.cloner import get_files_to_process


class BackendSmokeTests(unittest.TestCase):
    def test_app_imports_and_root_endpoint_works(self):
        from main import app

        client = TestClient(app)
        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_get_files_to_process_skips_binary_lockfiles_and_large_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "package-lock.json").write_text('{"lock": true}', encoding="utf-8")
            (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
            (root / "bundle.min.js").write_text("var a=1;", encoding="utf-8")
            (root / "README.md").write_text("# Hello\n", encoding="utf-8")

            files = get_files_to_process(str(root))
            names = {Path(path).name for path in files}

            self.assertIn("main.py", names)
            self.assertIn("README.md", names)
            self.assertNotIn("package-lock.json", names)
            self.assertNotIn("image.png", names)
            self.assertNotIn("bundle.min.js", names)

    def test_chunk_file_splits_minified_content_into_multiple_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "app.js"
            file_path.write_text("const data='" + ("x" * 30000) + "';", encoding="utf-8")

            chunks = chunk_file(str(file_path), str(root))

            self.assertGreater(len(chunks), 1)
            self.assertTrue(all(chunk["content"] for chunk in chunks))

    def test_embed_chunks_falls_back_when_transformer_unavailable(self):
        chunks = [{
            "file_path": "src/app.py",
            "content": "def hello():\n    return 'world'",
            "start_line": 1,
            "end_line": 2,
            "language": "py"
        }]

        with patch("ingest.embedder._model", None), patch("ingest.embedder.SentenceTransformer", side_effect=RuntimeError("offline")):
            embedded = embed_chunks(chunks)

        self.assertEqual(len(embedded[0]["embedding"]), EMBEDDING_DIMENSION)

    def test_agent_returns_fallback_answer_when_provider_fails(self):
        from agent.agent import run_agent_loop

        async def run_test():
            with patch("agent.agent.client.chat.completions.create", side_effect=RuntimeError("provider down")):
                answer, trace = await run_agent_loop(object(), "repo-1", "Where is auth handled?", "File: api/auth.py (L1-L10)\nAuth code")
            return answer, trace

        answer, trace = asyncio.run(run_test())
        self.assertIn("I could not reach the LLM provider", answer)
        self.assertEqual(trace, [])

    def test_ingest_endpoint_creates_repo_record_before_background_run(self):
        from main import app
        from api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1", access_token="token-1")
        client = TestClient(app)

        with patch("api.ingest_router.assert_supabase_schema"), \
             patch("api.ingest_router.ensure_repo_record", new=AsyncMock(return_value=("repo-1", "demo"))), \
             patch("api.ingest_router.run_ingestion_for_repo", new=AsyncMock()):
            response = client.post("/api/ingest", json={"github_url": "https://github.com/octocat/demo"})

        app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["repo_name"], "demo")


if __name__ == "__main__":
    unittest.main()
