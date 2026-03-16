"""
apps/api/routes/webhooks.py — Webhook endpoint management for MailGuard OSS.

POST   /api/v1/webhooks        — register a new webhook endpoint
GET    /api/v1/webhooks        — list all endpoints for the project
DELETE /api/v1/webhooks/{id}   — deactivate an endpoint

Security
--------
The webhook secret is generated with ``secrets.token_hex(32)`` (256-bit
entropy), returned to the developer **exactly once** in the registration
response, and stored in the database as an AES-256-GCM encrypted value so
it can be decrypted at delivery time for HMAC-SHA256 signing.

The plaintext secret is never stored in the database — only the encrypted
form (``secret_enc``) is persisted via ``core.crypto.encrypt``.

See ``core/webhooks.py`` for the signature header format
(``X-MailGuard-Signature: sha256={hex_digest}``) used on every delivery.
"""
from __future__ import annotations

import asyncio
import secrets
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from apps.api.middleware.auth import require_api_key
from apps.api.schemas import WebhookCreateRequest
from core.crypto import encrypt
from core.db import get_webhook, insert_webhook, list_webhooks, update_webhook
from core.models import ApiKey, Webhook

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _serialize_webhook(w: Webhook, secret: str | None = None) -> Dict[str, Any]:
    """Return a JSON-serialisable dict for a Webhook row.

    The ``secret`` argument is only passed at registration time — it is never
    retrieved from the database afterwards.
    """
    row: Dict[str, Any] = {
        "id": w.id,
        "project_id": w.project_id,
        "url": w.url,
        "events": w.events,
        "is_active": w.is_active,
        "failure_count": w.failure_count,
        "last_triggered_at": (
            w.last_triggered_at.isoformat() if w.last_triggered_at else None
        ),
        "created_at": w.created_at.isoformat(),
    }
    if secret is not None:
        row["secret"] = secret
    return row


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("")
async def register_webhook(
    body: WebhookCreateRequest,
    key_row: ApiKey = Depends(require_api_key),
) -> JSONResponse:
    """Register a new webhook endpoint for the authenticated project.

    Generates a 256-bit secret, returns it **once** in the response body, and
    stores only the AES-256-GCM encrypted form in the database.

    The developer must save the secret immediately — it cannot be retrieved
    again.  They use it to verify the ``X-MailGuard-Signature`` header on
    every incoming webhook delivery.
    """
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_error", "msg": "url must start with http:// or https://"},
        )

    if not body.events:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_error", "msg": "events must not be empty"},
        )

    # Generate secret — returned once, never stored in plaintext
    raw_secret = secrets.token_hex(32)
    secret_enc = encrypt(raw_secret)

    try:
        webhook = await asyncio.to_thread(
            insert_webhook,
            {
                "project_id": key_row.project_id,
                "url": body.url,
                "secret_enc": secret_enc,
                "events": body.events,
                "is_active": True,
                "failure_count": 0,
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable"},
        ) from exc

    return JSONResponse(
        content=_serialize_webhook(webhook, secret=raw_secret),
        status_code=201,
    )


@router.get("")
async def list_project_webhooks(
    key_row: ApiKey = Depends(require_api_key),
) -> JSONResponse:
    """List all webhook endpoints registered for the authenticated project.

    The ``secret`` field is **never** included in list responses.
    """
    try:
        webhooks = await asyncio.to_thread(list_webhooks, key_row.project_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable"},
        ) from exc

    return JSONResponse(content=[_serialize_webhook(w) for w in webhooks])


@router.delete("/{webhook_id}")
async def deactivate_webhook(
    webhook_id: str,
    key_row: ApiKey = Depends(require_api_key),
) -> JSONResponse:
    """Deactivate a webhook endpoint (sets ``is_active=False``).

    Returns 404 if the webhook does not exist or belongs to a different
    project (ownership check prevents cross-project deletions).
    """
    try:
        webhook = await asyncio.to_thread(get_webhook, webhook_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable"},
        ) from exc

    if webhook is None or webhook.project_id != key_row.project_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found"},
        )

    try:
        updated = await asyncio.to_thread(
            update_webhook,
            webhook_id,
            {"is_active": False},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable"},
        ) from exc

    return JSONResponse(content=_serialize_webhook(updated))
