import asyncio
import hashlib
import hmac
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError


class QuotaStore:
    def __init__(
        self,
        entitlement=None,
        used_bytes=0,
        current_repo_bytes=0,
        legacy_bytes=0,
        legacy_repositories=0,
        legacy_repo_bytes=None,
    ):
        self.entitlement = entitlement
        self.used_bytes = used_bytes
        self.current_repo_bytes = current_repo_bytes
        self.legacy_bytes = legacy_bytes
        self.legacy_repositories = legacy_repositories
        self.legacy_repo_bytes = current_repo_bytes if legacy_repo_bytes is None else legacy_repo_bytes
        self.executed = []

    async def fetch_one(self, sql, args=None):
        if "account_entitlements" in sql:
            return self.entitlement
        if "SUM(rf.byte_size)" in sql:
            return {"used_bytes": self.used_bytes}
        if "SUM(length(CAST(c.content AS BLOB)))" in sql:
            return {"used_bytes": self.legacy_bytes, "legacy_repositories": self.legacy_repositories}
        if "SUM(length(CAST(content AS BLOB)))" in sql:
            return {"used_bytes": self.legacy_repo_bytes}
        if "SUM(byte_size)" in sql:
            return {"used_bytes": self.current_repo_bytes}
        return None

    async def execute(self, sql, args=None):
        self.executed.append((sql, args or []))
        return SimpleNamespace(rows=[], rows_affected=1)


class BillingTests(unittest.TestCase):
    def test_signature_is_timing_safe_and_rejects_tampering(self):
        from api.billing_router import verify_signature

        order_id = "order_test_123"
        payment_id = "pay_test_456"
        secret = "test-secret"
        signature = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(order_id, payment_id, signature, secret))
        self.assertFalse(verify_signature(order_id, payment_id, "0" * 64, secret))

    def test_payment_payload_requires_bounded_non_empty_fields(self):
        from api.billing_router import VerifyPaymentRequest

        with self.assertRaises(ValidationError):
            VerifyPaymentRequest(razorpay_payment_id="", razorpay_order_id="order", razorpay_signature="sig")
        with self.assertRaises(ValidationError):
            VerifyPaymentRequest(razorpay_payment_id="p", razorpay_order_id="o", razorpay_signature="x" * 129)

    def test_explorer_quota_blocks_a_repository_before_publish(self):
        from quota import RepositoryQuotaExceededError, ensure_repository_usage_capacity

        store = QuotaStore(used_bytes=190_000_000)
        with self.assertRaises(RepositoryQuotaExceededError) as context:
            asyncio.run(ensure_repository_usage_capacity(store, "user-1", 20_000_000))
        self.assertIn("200 MB", str(context.exception))

    def test_format_bytes_does_not_round_small_index_to_zero(self):
        from quota import format_bytes

        self.assertEqual(format_bytes(0), "0 bytes")
        self.assertEqual(format_bytes(999), "999 bytes")
        self.assertEqual(format_bytes(1_500), "1.5 KB")
        self.assertEqual(format_bytes(250_000), "250 KB")
        self.assertEqual(format_bytes(200_000_000), "200 MB")

    def test_reindex_excludes_existing_repository_bytes_from_projection(self):
        from quota import ensure_repository_usage_capacity

        store = QuotaStore(used_bytes=200_000_000, current_repo_bytes=50_000_000)
        # The replacement is 50 MB, so total usage remains exactly 200 MB.
        asyncio.run(ensure_repository_usage_capacity(store, "user-1", 50_000_000, replacing_repo_id="repo-1"))

    def test_expired_team_payment_falls_back_to_explorer_quota(self):
        from quota import get_account_usage

        store = QuotaStore(
            entitlement={
                "plan": "team",
                "status": "active",
                "quota_bytes": 800_000_000,
                "updated_at": (datetime.now(UTC) - timedelta(days=31)).isoformat(),
            },
            used_bytes=100,
        )
        usage = asyncio.run(get_account_usage(store, "user-1"))
        self.assertEqual(usage["plan"], "explorer")
        self.assertEqual(usage["status"], "expired")
        self.assertEqual(usage["quota_bytes"], 200_000_000)

    def test_usage_includes_legacy_chunks_without_double_counting_manifests(self):
        from quota import get_account_usage

        store = QuotaStore(used_bytes=12_000, legacy_bytes=4_000, legacy_repositories=1)
        usage = asyncio.run(get_account_usage(store, "user-1"))
        self.assertEqual(usage["used_bytes"], 16_000)
        self.assertEqual(usage["legacy_repositories"], 1)
        self.assertTrue(usage["usage_estimated"])

    def test_reindex_capacity_subtracts_legacy_repository_chunks(self):
        from quota import ensure_repository_usage_capacity

        store = QuotaStore(
            used_bytes=160_000_000,
            current_repo_bytes=0,
            legacy_bytes=40_000_000,
            legacy_repositories=1,
            legacy_repo_bytes=40_000_000,
        )
        # The fallback makes the old indexed payload removable from the
        # projection, just like a modern repo_files manifest.
        asyncio.run(ensure_repository_usage_capacity(store, "user-1", 40_000_000, replacing_repo_id="repo-1"))

    def test_create_order_uses_fixed_server_amount_and_authenticated_user(self):
        from api.billing_router import CreateOrderRequest, create_order

        store = QuotaStore()
        razorpay_client = MagicMock()
        razorpay_client.order.create.return_value = {"id": "order_test_1", "amount": 30_000, "currency": "INR"}
        user = SimpleNamespace(id="user-1")
        with patch("api.billing_router.assert_turso_schema", new=AsyncMock()), \
             patch("api.billing_router.get_turso_store", return_value=store), \
             patch("api.billing_router._require_credentials", return_value=("rzp_test", "secret")), \
             patch("api.billing_router.get_razorpay_client", return_value=razorpay_client):
            result = asyncio.run(create_order(CreateOrderRequest(), user))
        self.assertEqual(result, {"order_id": "order_test_1", "amount": 30_000, "currency": "INR", "key_id": "rzp_test"})
        args = razorpay_client.order.create.call_args.args[0]
        self.assertEqual(args, {"amount": 30_000, "currency": "INR", "receipt": args["receipt"]})
        self.assertTrue(any("billing_orders" in sql for sql, _ in store.executed))

    def test_create_order_maps_provider_auth_failure_to_401(self):
        from api.billing_router import CreateOrderRequest, create_order

        store = QuotaStore()
        razorpay_client = MagicMock()
        razorpay_client.order.create.side_effect = RuntimeError("Authentication failed")
        user = SimpleNamespace(id="user-1")
        with patch("api.billing_router.assert_turso_schema", new=AsyncMock()), \
             patch("api.billing_router.get_turso_store", return_value=store), \
             patch("api.billing_router._require_credentials", return_value=("rzp_test", "secret")), \
             patch("api.billing_router.get_razorpay_client", return_value=razorpay_client):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(create_order(CreateOrderRequest(), user))
        self.assertEqual(context.exception.status_code, 401)

    def test_verify_payment_does_not_write_for_invalid_signature(self):
        from api.billing_router import VerifyPaymentRequest, verify_payment

        store = QuotaStore()
        store.fetch_one = AsyncMock(return_value={
            "id": "billing-1", "razorpay_order_id": "order_test_1", "amount": 30_000,
            "currency": "INR", "status": "created",
        })
        user = SimpleNamespace(id="user-1")
        payload = VerifyPaymentRequest(
            razorpay_payment_id="pay_test_1",
            razorpay_order_id="order_test_1",
            razorpay_signature="0" * 64,
        )
        with patch("api.billing_router.assert_turso_schema", new=AsyncMock()), \
             patch("api.billing_router.get_turso_store", return_value=store), \
             patch("api.billing_router._require_credentials", return_value=("rzp_test", "secret")):
            with self.assertRaises(HTTPException) as context:
                asyncio.run(verify_payment(payload, user))
        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(store.executed, [])


if __name__ == "__main__":
    unittest.main()
