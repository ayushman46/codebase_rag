"""Authenticated Team-plan billing endpoints for Razorpay Standard Checkout."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user
from config import settings
from database import DatabaseConfigurationError, assert_turso_schema, explain_database_error, get_turso_store
from quota import get_account_usage

logger = logging.getLogger(__name__)
router = APIRouter()
_order_lock = asyncio.Lock()
_PENDING_ORDER_WINDOW = timedelta(minutes=15)


class BillingConfigurationError(RuntimeError):
    """Raised when Razorpay server credentials are not configured."""


class CreateOrderRequest(BaseModel):
    plan: Literal["team"] = "team"


class VerifyPaymentRequest(BaseModel):
    razorpay_payment_id: str = Field(min_length=1, max_length=128)
    razorpay_order_id: str = Field(min_length=1, max_length=128)
    razorpay_signature: str = Field(min_length=1, max_length=128)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _require_credentials() -> tuple[str, str]:
    key_id = settings.razorpay_key_id.strip()
    secret = settings.razorpay_key_secret.strip()
    if not key_id or not secret:
        raise BillingConfigurationError(
            "Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET on the backend."
        )
    return key_id, secret


def get_razorpay_client():
    """Create the SDK client lazily so the API can still import without secrets."""
    key_id, secret = _require_credentials()
    try:
        import razorpay
    except ImportError as error:  # pragma: no cover - exercised by deployment setup
        raise BillingConfigurationError("The Razorpay SDK is not installed. Install the backend requirements and restart.") from error
    return razorpay.Client(auth=(key_id, secret))


def verify_signature(order_id: str, payment_id: str, signature: str, secret: str) -> bool:
    """Verify the exact server-created order with a timing-safe comparison."""
    payload = f"{order_id}|{payment_id}".encode("utf-8")
    generated = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(generated, signature)


def _is_razorpay_auth_error(error: Exception) -> bool:
    """Recognize SDK auth failures without returning provider internals."""
    message = str(error).lower()
    return any(marker in message for marker in ("authentication", "unauthorized", "invalid api key", "invalid key", "401"))


def _is_recent(created_at: str | None) -> bool:
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return created >= datetime.now(UTC) - _PENDING_ORDER_WINDOW


@router.get("/account/usage")
async def account_usage(current_user=Depends(get_current_user)):
    """Return quota information for the signed-in profile only."""
    try:
        await assert_turso_schema()
        return await get_account_usage(get_turso_store(), current_user.id)
    except DatabaseConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not fetch account usage")
        raise HTTPException(status_code=502, detail=explain_database_error(error)) from error


@router.post("/create-order")
async def create_order(payload: CreateOrderRequest, current_user=Depends(get_current_user)):
    """Create (or reuse) the fixed ₹300 Team-plan order on the server."""
    if payload.plan != "team":  # defensive; Literal validation already enforces this
        raise HTTPException(status_code=422, detail="Unsupported plan.")
    amount = int(settings.team_plan_amount_paise)
    if amount < 100:
        raise HTTPException(status_code=500, detail="The Team plan amount is below Razorpay's minimum order value.")
    try:
        await assert_turso_schema()
        store = get_turso_store()
        key_id, _ = _require_credentials()
        async with _order_lock:
            pending = await store.fetch_one(
                "SELECT razorpay_order_id, amount, currency, created_at FROM billing_orders "
                "WHERE user_id = ? AND plan = 'team' AND status = 'created' "
                "ORDER BY created_at DESC LIMIT 1",
                [current_user.id],
            )
            if (
                pending
                and _is_recent(pending.get("created_at"))
                and int(pending.get("amount") or 0) == amount
                and str(pending.get("currency") or "") == "INR"
            ):
                return {
                    "order_id": pending["razorpay_order_id"],
                    "amount": int(pending["amount"]),
                    "currency": pending["currency"],
                    # The public key is safe to return and keeps the browser
                    # in sync with the backend even when a Vite build was
                    # created before its local environment was refreshed.
                    "key_id": key_id,
                }

            receipt = f"team-{uuid4().hex[:24]}"
            order = await asyncio.to_thread(
                get_razorpay_client().order.create,
                {"amount": amount, "currency": "INR", "receipt": receipt},
            )
            order_id = str(order.get("id") or "").strip()
            if not order_id:
                raise BillingConfigurationError("Razorpay returned an invalid order response.")
            currency = str(order.get("currency") or "")
            returned_amount = int(order.get("amount") or 0)
            if returned_amount != amount or currency != "INR":
                raise BillingConfigurationError("Razorpay returned an unexpected Team-plan amount.")
            now = _timestamp()
            await store.execute(
                "INSERT INTO billing_orders "
                "(id, user_id, plan, razorpay_order_id, amount, currency, status, created_at, updated_at) "
                "VALUES (?, ?, 'team', ?, ?, ?, 'created', ?, ?)",
                [str(uuid4()), current_user.id, order_id, amount, currency, now, now],
            )
            return {"order_id": order_id, "amount": amount, "currency": currency, "key_id": key_id}
    except (BillingConfigurationError, DatabaseConfigurationError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        if _is_razorpay_auth_error(error):
            logger.warning("Razorpay rejected the configured server credentials")
            raise HTTPException(status_code=401, detail="Razorpay rejected the server credentials. Check the backend configuration.") from error
        logger.exception("Could not create Razorpay order")
        raise HTTPException(status_code=500, detail="Razorpay could not create the order. Please try again.") from error


@router.post("/verify-payment")
async def verify_payment(payload: VerifyPaymentRequest, current_user=Depends(get_current_user)):
    """Verify the server-created order and activate Team only after a valid signature."""
    values = (
        payload.razorpay_payment_id.strip(),
        payload.razorpay_order_id.strip(),
        payload.razorpay_signature.strip(),
    )
    if not all(values):
        raise HTTPException(status_code=400, detail="Payment verification fields are required.")
    try:
        await assert_turso_schema()
        store = get_turso_store()
        _, secret = _require_credentials()
        order = await store.fetch_one(
            "SELECT id, razorpay_order_id, amount, currency, status, razorpay_payment_id FROM billing_orders "
            "WHERE user_id = ? AND razorpay_order_id = ? AND plan = 'team'",
            [current_user.id, values[1]],
        )
        if not order:
            raise HTTPException(status_code=400, detail="This payment order is not valid for your account.")
        if int(order.get("amount") or 0) != int(settings.team_plan_amount_paise) or order.get("currency") != "INR":
            raise HTTPException(status_code=400, detail="This payment order does not match the Team plan.")
        # Use the order id stored on our server, not an untrusted client value,
        # when constructing the HMAC payload.
        if not verify_signature(order["razorpay_order_id"], values[0], values[2], secret):
            raise HTTPException(status_code=400, detail="Payment signature could not be verified.")
        if order.get("status") == "paid":
            if order.get("razorpay_payment_id") != values[0]:
                raise HTTPException(status_code=400, detail="This order has already been verified with another payment.")
            return {"verified": True, "plan": "team"}

        now = _timestamp()
        await store.execute(
            "INSERT INTO account_entitlements "
            "(user_id, plan, quota_bytes, status, razorpay_order_id, razorpay_payment_id, updated_at) "
            "VALUES (?, 'team', ?, 'active', ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET plan = 'team', quota_bytes = excluded.quota_bytes, "
            "status = 'active', razorpay_order_id = excluded.razorpay_order_id, "
            "razorpay_payment_id = excluded.razorpay_payment_id, updated_at = excluded.updated_at",
            [current_user.id, settings.team_codebase_bytes, order["razorpay_order_id"], values[0], now],
        )
        await store.execute(
            "UPDATE billing_orders SET status = 'paid', razorpay_payment_id = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ? AND status = 'created'",
            [values[0], now, order["id"], current_user.id],
        )
        return {"verified": True, "plan": "team"}
    except HTTPException:
        raise
    except (BillingConfigurationError, DatabaseConfigurationError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Could not verify Razorpay payment")
        raise HTTPException(status_code=500, detail="Payment verification could not be completed. Please try again.") from error
