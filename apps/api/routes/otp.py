"""
OTP send and verify routes for MailGuard OSS.

POST /api/v1/otp/send   — generate, persist, and enqueue OTP email
POST /api/v1/otp/verify — verify submitted code and return JWT on success

Anti-enumeration guarantee
--------------------------
Every response from POST /api/v1/otp/send takes a minimum of
_MIN_RESPONSE_SECS (200 ms) regardless of the code path taken.
``time.monotonic()`` is captured at the very start of ``send_otp`` and
``asyncio.sleep()`` pads the remaining time inside a ``try/finally`` block
so that every exit path — including all ``HTTPException`` raises — is
covered automatically.

ARQ enqueueing
--------------
The route saves the OTP record and then enqueues the email delivery job to
the ARQ worker via ``_enqueue_email()``.  Email sending is **never**
performed synchronously inside the route.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

import redis as sync_redis_lib
from arq import create_pool
from email_validator import validate_email, EmailNotValidError
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from apps.api.middleware.auth import require_api_key
from apps.api.schemas import OtpSendRequest, OtpVerifyRequest
from core.config import settings
from core.crypto import hmac_email
from core.db import get_project, insert_email_log
from core.models import ApiKey
from core.otp import generate_otp, save_otp, verify_and_consume
from core.rate_limiter import check_email_hourly, check_key_hourly
from core.redis_client import arq_redis_settings
from core.templates import render_otp_email

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_RESPONSE_SECS: float = 0.200  # 200 ms anti-enumeration floor
_RETRY_AFTER: int = 3_600          # 1-hour window (key_hourly tier)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/otp", tags=["OTP"])

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_sync_redis_client: Optional[sync_redis_lib.Redis] = None  # type: ignore[type-arg]


def _get_sync_redis() -> sync_redis_lib.Redis:  # type: ignore[type-arg]
    """Return the shared synchronous Redis client (lazy initialisation)."""
    global _sync_redis_client
    if _sync_redis_client is None:
        _sync_redis_client = sync_redis_lib.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _sync_redis_client


def _mask_email(email: str) -> str:
    """Mask everything before @ except the first character.

    ``user@example.com`` → ``u***@example.com``
    """
    local, domain = email.split("@", 1)
    return local[0] + "***@" + domain


async def _enqueue_email(
    email_log_id: str,
    to_address: str,
    subject: str,
    text_body: str,
    html_body: str,
    sender_id: str,
) -> None:
    """Enqueue an email delivery job to the ARQ worker pool."""
    arq_redis = await create_pool(arq_redis_settings())
    try:
        await arq_redis.enqueue_job(
            "task_send_email",
            email_log_id,
            to_address,
            subject,
            text_body,
            html_body,
            sender_id,
        )
    finally:
        await arq_redis.aclose()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/send")
async def send_otp(
    body: OtpSendRequest,
    key_row: ApiKey = Depends(require_api_key),
) -> JSONResponse:
    """Generate an OTP, persist it, and enqueue the delivery email.

    Anti-enumeration guarantee: every response path takes >= 200 ms.
    The ``try/finally`` pattern ensures the timing floor is enforced even
    when an ``HTTPException`` is raised on an early-exit path.
    """
    t0 = time.monotonic()
    try:
        # ── 1. Email format validation ──────────────────────────────────────
        try:
            validate_email(body.email, check_deliverability=False)
        except EmailNotValidError:
            raise HTTPException(
                status_code=422,
                detail={"error": "validation_error"},
            )

        # ── 2. Per-key and per-email rate limiting ───────────────────────────
        email_hash = hmac_email(body.email)
        try:
            redis = _get_sync_redis()
            key_ok = await asyncio.to_thread(check_key_hourly, redis, key_row.id)
            if not key_ok:
                raise HTTPException(
                    status_code=429,
                    detail={"error": "rate_limit_exceeded", "retry_after": _RETRY_AFTER},
                )
            email_ok = await asyncio.to_thread(
                check_email_hourly, redis, key_row.project_id, email_hash
            )
            if not email_ok:
                raise HTTPException(
                    status_code=429,
                    detail={"error": "rate_limit_exceeded", "retry_after": _RETRY_AFTER},
                )
        except HTTPException:
            raise
        except Exception:
            pass  # Redis unavailable — fail open (same policy as IP middleware)

        # ── 3. Fetch project configuration ───────────────────────────────────
        try:
            project = await asyncio.to_thread(get_project, key_row.project_id)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "service_unavailable"},
            ) from exc

        if project is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "service_unavailable"},
            )

        # ── 4. Generate and persist the OTP ──────────────────────────────────
        otp_code = generate_otp(project.otp_length)
        try:
            await asyncio.to_thread(
                save_otp,
                project.id,
                body.email,
                otp_code,
                body.purpose,
                project.otp_expiry_seconds,
                project.otp_max_attempts,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "service_unavailable"},
            ) from exc

        # ── 5. Enqueue email delivery (non-fatal if it fails) ─────────────────
        if project.sender_email_id:
            expiry_minutes = max(1, project.otp_expiry_seconds // 60)
            subject, text_body, html_body = render_otp_email(
                otp_code=otp_code,
                expiry_minutes=expiry_minutes,
                project_name=project.name,
                purpose=body.purpose,
            )
            try:
                log_row = await asyncio.to_thread(
                    insert_email_log,
                    {
                        "project_id": project.id,
                        "sender_id": project.sender_email_id,
                        "recipient_hash": email_hash,
                        "purpose": body.purpose,
                        "type": "otp",
                        "status": "queued",
                        "sent_at": datetime.now(UTC).isoformat(),
                    },
                )
                await _enqueue_email(
                    email_log_id=log_row.id,
                    to_address=body.email,
                    subject=subject,
                    text_body=text_body,
                    html_body=html_body,
                    sender_id=project.sender_email_id,
                )
            except Exception:
                pass  # Email failure is non-fatal; OTP is already persisted

        masked = _mask_email(body.email)
        return JSONResponse(content={"sent": True, "masked_email": masked})

    finally:
        # Anti-enumeration: pad every response (including errors) to >= 200 ms
        elapsed = time.monotonic() - t0
        pad = _MIN_RESPONSE_SECS - elapsed
        if pad > 0:
            await asyncio.sleep(pad)


@router.post("/verify")
async def verify_otp(
    body: OtpVerifyRequest,
    key_row: ApiKey = Depends(require_api_key),
) -> JSONResponse:
    """Verify a submitted OTP code and return a signed JWT on success.

    Delegates all verification logic to ``core.otp.verify_and_consume`` —
    no OTP business logic is reimplemented here.
    """
    try:
        result = await asyncio.to_thread(
            verify_and_consume,
            key_row.project_id,
            body.email,
            body.code,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable"},
        ) from exc

    if result.get("verified"):
        return JSONResponse(
            content={
                "verified": True,
                "token": result["token"],
                "otp_id": result["otp_id"],
            }
        )

    error = result.get("error", "unknown")

    if error == "invalid_code":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_code",
                "attempts_remaining": result.get("attempts_remaining", 0),
            },
        )

    if error == "account_locked":
        raise HTTPException(
            status_code=423,
            detail={"error": "account_locked"},
        )

    if error == "otp_expired":
        raise HTTPException(
            status_code=410,
            detail={"error": "otp_expired"},
        )

    raise HTTPException(
        status_code=500,
        detail={"error": "internal_error"},
    )
