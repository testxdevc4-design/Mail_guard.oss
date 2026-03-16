"""
apps/api/routes/magic.py — Magic link send and verify routes.

POST /api/v1/magic/send         — generate a magic link and enqueue the email
GET  /api/v1/magic/verify/{token} — verify token, return HTML page

HTML responses
--------------
The verify endpoint returns HTML, not JSON, so it is accessible by users
who click a link in their email.  The pages work without JavaScript.

Webhook events
--------------
``magic_link.sent``     — fired after the email is enqueued
``magic_link.verified`` — fired after successful token verification

If core/webhooks.py is not yet implemented (Part 09), the import is silently
skipped via try/except ImportError; the routes never crash on a missing module.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

from arq import create_pool
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from apps.api.middleware.auth import require_api_key
from apps.api.schemas import MagicLinkSendRequest
from core.config import settings
from core.crypto import hmac_email
from core.db import get_magic_link_by_token_hash, get_project, insert_email_log
from core.magic_links import create_magic_link, verify_magic_link
from core.models import ApiKey
from core.redis_client import arq_redis_settings
from core.templates import render_magic_expired_page, render_magic_link_email, render_magic_verified_page

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Webhook import — silently skipped if Part 09 is not yet implemented
# ---------------------------------------------------------------------------

try:
    from core.webhooks import fire_event as _fire_event  # type: ignore[import]
except ImportError:
    _fire_event = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/magic", tags=["Magic Links"])

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
async def send_magic_link(
    request: Request,
    body: MagicLinkSendRequest,
    key_row: ApiKey = Depends(require_api_key),
) -> JSONResponse:
    """Generate a magic link, persist it, and enqueue the delivery email.

    Returns JSON ``{"status": "sent"}`` on success.
    """
    # ── 1. Email format validation ───────────────────────────────────────────
    try:
        validate_email(body.email, check_deliverability=False)
    except EmailNotValidError:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_error"},
        )

    # ── 2. Fetch project configuration ───────────────────────────────────────
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

    # ── 3. Generate and persist the magic link token ──────────────────────────
    try:
        raw_token = await asyncio.to_thread(
            create_magic_link,
            project.id,
            body.email,
            body.purpose,
            body.redirect_url,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable"},
        ) from exc

    # ── 4. Construct the verify URL ───────────────────────────────────────────
    base_url = str(request.base_url).rstrip("/")
    magic_link_url = f"{base_url}/api/v1/magic/verify/{raw_token}"

    # ── 5. Enqueue email delivery (non-fatal if it fails) ─────────────────────
    if project.sender_email_id:
        expiry_minutes = max(1, settings.MAGIC_LINK_EXPIRY_MINUTES)
        subject, text_body, html_body = render_magic_link_email(
            magic_link_url=magic_link_url,
            expiry_minutes=expiry_minutes,
            project_name=project.name,
        )
        email_hash = hmac_email(body.email)
        try:
            log_row = await asyncio.to_thread(
                insert_email_log,
                {
                    "project_id": project.id,
                    "sender_id": project.sender_email_id,
                    "recipient_hash": email_hash,
                    "purpose": body.purpose,
                    "type": "magic_link",
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
            pass  # Email failure is non-fatal; magic link is already persisted

    # ── 6. Fire webhook event (fire-and-forget) ──────────────────────────────
    if _fire_event is not None:
        asyncio.create_task(
            _fire_event(
                project.id,
                "magic_link.sent",
                {"purpose": body.purpose},
            )
        )

    return JSONResponse(content={"status": "sent"})

@router.get("/verify/{token}", response_class=HTMLResponse)
async def verify_magic_link_route(token: str) -> HTMLResponse:
    """Verify a magic link token and return an HTML page.

    Returns:
    - ``200 magic_verified.html`` on success (with JWT embedded and optional
      meta-refresh redirect after 2 seconds if ``redirect_url`` is set)
    - ``410 magic_expired.html`` for expired, already-used, or invalid tokens
    """
    # Resolve project_id for the webhook event before verify consumes the token.
    # ``verify_magic_link`` marks the link as used so we look up the row first.
    _magic_project_id = ""
    if _fire_event is not None:
        try:
            _token_hash = hashlib.sha256(token.encode()).hexdigest()
            _ml_row = await asyncio.to_thread(get_magic_link_by_token_hash, _token_hash)
            if _ml_row is not None:
                _magic_project_id = _ml_row.project_id
        except Exception:
            pass  # best-effort; webhook event will be skipped if lookup fails

    try:
        result = await asyncio.to_thread(verify_magic_link, token)
    except Exception:
        return HTMLResponse(
            content=render_magic_expired_page(),
            status_code=410,
        )

    if not result.get("verified"):
        return HTMLResponse(
            content=render_magic_expired_page(),
            status_code=410,
        )

    jwt_token: str = result["token"]
    redirect_url: str | None = result.get("redirect_url")

    # ── Fire webhook event (fire-and-forget) ─────────────────────────────────
    if _fire_event is not None:
        asyncio.create_task(
            _fire_event(
                _magic_project_id,
                "magic_link.verified",
                {"link_id": result.get("link_id", "")},
            )
        )

    return HTMLResponse(
        content=render_magic_verified_page(
            jwt_token=jwt_token,
            redirect_url=redirect_url,
        ),
        status_code=200,
    )
