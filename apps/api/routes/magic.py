"""
Magic-link send and verify routes for MailGuard OSS.

POST /api/v1/magic/send
    Requires a valid API key (Bearer token).
    Generates a single-use magic link, persists its SHA-256 hash, and
    enqueues a delivery email via the ARQ worker.

GET  /api/v1/magic/verify/{token}
    Public endpoint — no API key required (the raw token IS the credential).
    Returns an HTML page (never JSON):
      - magic_verified.html (HTTP 200) on success
      - magic_expired.html  (HTTP 410) on expired / already-used / invalid token
    A meta-refresh redirect to ``redirect_url`` fires after 2 seconds when
    ``redirect_url`` was set at link-creation time.

Webhook events
--------------
  magic_link.sent     — fired after enqueuing the delivery email
  magic_link.verified — fired after successful verification

Both events are imported from ``core.webhooks`` (Part 09).  If webhooks are
not yet implemented, the import is silently skipped; no crash will occur.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import redis as sync_redis_lib
from arq import create_pool
from email_validator import validate_email, EmailNotValidError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
import os

from apps.api.middleware.auth import require_api_key
from apps.api.schemas import MagicLinkSendRequest
from core.config import settings
from core.crypto import hmac_email
from core.db import get_project, insert_email_log
from core.magic_links import create_magic_link, verify_magic_link
from core.models import ApiKey
from core.redis_client import arq_redis_settings
from core.templates import render_magic_link_email

# ---------------------------------------------------------------------------
# Optional webhook support (Part 09) — fail-open if not yet implemented
# ---------------------------------------------------------------------------

try:
    from core.webhooks import fire_event as _fire_event  # type: ignore[import]
except ImportError:
    # TODO: remove this fallback once core/webhooks.py is implemented (Part 09)
    async def _fire_event(project_id: str, event: str, payload: dict) -> None:  # type: ignore[misc]
        pass

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Jinja2 environment for response HTML pages
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "templates"
)

_jinja_env = Environment(
    loader=FileSystemLoader(os.path.abspath(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _render(template_name: str, **ctx: object) -> str:
    return _jinja_env.get_template(template_name).render(**ctx)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/magic", tags=["Magic Links"])

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
    body: MagicLinkSendRequest,
    key_row: ApiKey = Depends(require_api_key),
) -> JSONResponse:
    """Generate a magic link and enqueue the delivery email.

    Returns ``{"status": "sent"}`` on success.
    The raw token is embedded in the email link only; it is never returned
    in this HTTP response.
    """
    # ── 1. Email format validation ──────────────────────────────────────
    try:
        validate_email(body.email, check_deliverability=False)
    except EmailNotValidError:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_error"},
        )

    # ── 2. Fetch project configuration ────────────────────────────────────
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

    # ── 3. Generate and persist the magic link ────────────────────────────
    try:
        raw_token, link_id = await asyncio.to_thread(
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

    # ── 4. Enqueue delivery email (non-fatal if it fails) ─────────────────
    if project.sender_email_id:
        expiry_minutes = settings.MAGIC_LINK_EXPIRY_MINUTES
        verify_url = (
            f"{settings.INTERNAL_API_URL}/api/v1/magic/verify/{raw_token}"
        )
        subject, text_body, html_body = render_magic_link_email(
            magic_link_url=verify_url,
            expiry_minutes=expiry_minutes,
            project_name=project.name,
        )
        try:
            log_row = await asyncio.to_thread(
                insert_email_log,
                {
                    "project_id": project.id,
                    "sender_id": project.sender_email_id,
                    "recipient_hash": __import__("core.crypto", fromlist=["hmac_email"]).hmac_email(body.email),
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

    # ── 5. Fire webhook event ─────────────────────────────────────────────
    try:
        await _fire_event(
            project_id=project.id,
            event="magic_link.sent",
            payload={"magic_link_id": link_id, "purpose": body.purpose},
        )
    except Exception:
        pass  # Webhook failure must never fail the send request

    return JSONResponse(content={"status": "sent"})


@router.get("/verify/{token}", response_class=HTMLResponse)
async def verify_magic_link_route(token: str) -> HTMLResponse:
    """Verify a magic-link token and return an HTML page.

    On success:  HTTP 200 — magic_verified.html
    On failure:  HTTP 410 — magic_expired.html

    The response is always HTML — never JSON.  The page works without
    JavaScript for accessibility.

    A ``<meta http-equiv="refresh">`` tag redirects to ``redirect_url``
    after 2 seconds when a redirect URL was set at link-creation time.
    """
    try:
        result = await asyncio.to_thread(verify_magic_link, token)
    except Exception:
        html = _render("magic_expired.html", reason="internal_error")
        return HTMLResponse(content=html, status_code=410)

    if result.get("verified"):
        redirect_url = result.get("redirect_url") or ""
        html = _render(
            "magic_verified.html",
            redirect_url=redirect_url,
            token=result["token"],
            magic_link_id=result["magic_link_id"],
        )

        # ── Fire webhook event (non-fatal) ────────────────────────────
        try:
            await _fire_event(
                project_id="",  # no project_id in result; fire best-effort
                event="magic_link.verified",
                payload={
                    "magic_link_id": result["magic_link_id"],
                    "email_hash": result.get("email_hash", ""),
                },
            )
        except Exception:
            pass

        return HTMLResponse(content=html, status_code=200)

    error = result.get("error", "unknown")
    html = _render("magic_expired.html", reason=error)
    return HTMLResponse(content=html, status_code=410)
