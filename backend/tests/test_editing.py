"""Safety tests for structured code proposals and editing tickets."""

import time
import unittest

from agent.code_edit import (
    CodeEditValidationError,
    EditingAuthorizationError,
    create_edit_ticket,
    format_code_edit_response,
    parse_code_edit,
    verify_edit_ticket,
)


class CodeEditingTests(unittest.TestCase):
    def setUp(self):
        self.raw = """<code_edit>
        {"file_path":"src/auth.py","summary":"Use the validated session helper","changes":[{"old":"def login():\\n    return True","new":"def login():\\n    return validate_session()","reason":"Reuse the existing session boundary"}],"validation":["python -m compileall src/auth.py"]}
        </code_edit>"""

    def test_parser_accepts_only_exact_grounded_replacements(self):
        edit = parse_code_edit(
            self.raw,
            allowed_files={"src/auth.py"},
            source_context="def login():\n    return True\n",
            max_change_bytes=10_000,
        )
        self.assertEqual(edit["file_path"], "src/auth.py")
        self.assertEqual(edit["changes"][0]["old"], "def login():\n    return True")
        self.assertIn("src/auth.py", format_code_edit_response(edit))

    def test_parser_rejects_unknown_file_and_ungrounded_hunk(self):
        with self.assertRaises(CodeEditValidationError):
            parse_code_edit(
                self.raw.replace("src/auth.py", "src/other.py"),
                allowed_files={"src/auth.py"},
                source_context="def login():\n    return True\n",
                max_change_bytes=10_000,
            )

    def test_parser_does_not_borrow_an_identical_hunk_from_another_file(self):
        raw = self.raw.replace(
            "def login():\\n    return True",
            "def shared():\\n    return True",
        )
        context = (
            "File: src/auth.py (L1-L2)\n"
            "Symbols: login\n"
            "Retrieval reason: source match\n"
            "def login():\n    return True\n\n"
            "File: src/other.py (L1-L2)\n"
            "Symbols: shared\n"
            "Retrieval reason: source match\n"
            "def shared():\n    return True\n"
        )
        with self.assertRaises(CodeEditValidationError):
            parse_code_edit(
                raw,
                allowed_files={"src/auth.py", "src/other.py"},
                source_context=context,
                max_change_bytes=10_000,
            )
        with self.assertRaises(CodeEditValidationError):
            parse_code_edit(
                self.raw.replace("def login():\\n    return True", "def missing():\\n    return False"),
                allowed_files={"src/auth.py"},
                source_context="def login():\n    return True\n",
                max_change_bytes=10_000,
            )

    def test_parser_accepts_bounded_multi_file_issue_patch(self):
        raw = '''<code_edit>
        {"files":[
          {"file_path":"src/auth.py","summary":"Validate the session","changes":[{"old":"def login():\\n    return True","new":"def login():\\n    return validate_session()"}],"validation":["python -m compileall src/auth.py"]},
          {"file_path":"tests/test_auth.py","summary":"Cover the regression","changes":[{"old":"def test_login():\\n    assert True","new":"def test_login():\\n    assert validate_session()"}],"validation":["pytest tests/test_auth.py"]}
        ]}
        </code_edit>'''
        context = (
            "File: src/auth.py (L1-L2)\n"
            "Symbols: login\n"
            "def login():\n    return True\n\n"
            "File: tests/test_auth.py (L1-L2)\n"
            "Symbols: test_login\n"
            "def test_login():\n    assert True\n"
        )
        edit = parse_code_edit(raw, allowed_files={"src/auth.py", "tests/test_auth.py"}, source_context=context, max_change_bytes=10_000)
        self.assertEqual([item["file_path"] for item in edit["files"]], ["src/auth.py", "tests/test_auth.py"])
        self.assertEqual(len(edit["files"][1]["changes"]), 1)

    def test_multi_file_ticket_is_scoped_to_the_declared_paths(self):
        secret = "test-editing-secret"
        ticket = create_edit_ticket(secret, user_id="u1", repo_name="demo", file_path=["src/auth.py", "tests/test_auth.py"], ttl_seconds=60)
        verify_edit_ticket(secret, ticket, user_id="u1", repo_name="demo", file_path="tests/test_auth.py")
        with self.assertRaises(EditingAuthorizationError):
            verify_edit_ticket(secret, ticket, user_id="u1", repo_name="demo", file_path="src/other.py")

    def test_edit_ticket_is_scoped_and_expires(self):
        secret = "test-editing-secret"
        ticket = create_edit_ticket(secret, user_id="u1", repo_name="demo", file_path="src/auth.py", ttl_seconds=60)
        payload = verify_edit_ticket(secret, ticket, user_id="u1", repo_name="demo", file_path="src/auth.py")
        self.assertEqual(payload["p"], "src/auth.py")
        with self.assertRaises(EditingAuthorizationError):
            verify_edit_ticket(secret, ticket, user_id="u2", repo_name="demo", file_path="src/auth.py")
        with self.assertRaises(EditingAuthorizationError):
            verify_edit_ticket(secret, ticket, user_id="u1", repo_name="demo", file_path="src/app.py")

    def test_edit_ticket_rejects_expired_payload(self):
        secret = "test-editing-secret"
        ticket = create_edit_ticket(secret, user_id="u1", repo_name="demo", file_path="src/auth.py", ttl_seconds=60)
        # Keep the signature valid while moving the expiry into the past.
        import base64, hashlib, hmac, json
        _, body, _ = ticket.split(".")
        decoded = json.loads(base64.urlsafe_b64decode((body + "=" * (-len(body) % 4)).encode()))
        decoded["e"] = int(time.time()) - 1
        expired_body = base64.urlsafe_b64encode(json.dumps(decoded, separators=(",", ":")).encode()).decode().rstrip("=")
        signature = hmac.new(secret.encode(), expired_body.encode(), hashlib.sha256).hexdigest()
        with self.assertRaises(EditingAuthorizationError):
            verify_edit_ticket(secret, f"v1.{expired_body}.{signature}", user_id="u1", repo_name="demo", file_path="src/auth.py")


if __name__ == "__main__":
    unittest.main()
