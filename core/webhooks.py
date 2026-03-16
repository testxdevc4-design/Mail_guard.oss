"""
core/webhooks.py — HMAC-SHA256 signed webhook delivery for MailGuard OSS.

sign_payload()
--------------
Serialises the payload with ``sort_keys=True`` and compact separators so the
bytes are deterministic regardless of Python dict insertion order.
The HMAC-SHA256 hex digest is returned as ``sha256={hex_digest}``.

fire_event()
------------
Looks up all active webhook endpoints subscribed to the given event type and
enqueues one ARQ ``task_deliver_webhook`` job per endpoint.  A failure to
enqueue one job never blocks or cancels delivery to other endpoints.

Webhook delivery header
-----------------------
Every HTTP POST to a developer endpoint carries a custom header::

    X-MailGuard-Signature: sha256={hex_digest}

where ``{hex_digest}`` is the HMAC-SHA256 of the compact-JSON payload signed
with the webhook's raw secret.  To verify the signature in Python:

    import hashlib, hmac, json

    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(f"sha256={expected}", received_header_value)

The Telegram bot (Part 12) may include this snippet in webhook setup
instructions when users register a new endpoint.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Dict

from arq import create_pool

from core.db import list_webhooks
from core.redis_client import arq_redis_settings

logger = logging.getLogger(__name__)


def sign_payload(raw_secret: str, payload: Dict[str, Any]) -> str:
    """Sign *payload* with *raw_secret* using HMAC-SHA256.

    The payload is serialised with ``sort_keys=True`` and compact separators
    ``(',', ':')`` so the signature is deterministic regardless of the
    dictionary key insertion order — a different insertion order for the same
    logical keys will produce identical bytes and therefore an identical
    signature.

    Parameters
    ----------
    raw_secret:
        The plaintext secret returned to the developer at registration time.
    payload:
        Any JSON-serialisable dict to be signed.

    Returns
    -------
    str
        Signature string in the format ``sha256={hex_digest}``.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hmac.new(raw_secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def fire_event(
    project_id: str,
    event: str,
    payload: Dict[str, Any],
) -> None:
    """Enqueue one ARQ webhook delivery job per subscribed, active endpoint.

    Looks up all ``is_active=True`` webhook rows for *project_id* that include
    *event* in their ``events`` array, and enqueues a separate
    ``task_deliver_webhook`` ARQ job for each one.  A failure to enqueue one
    job — or the absence of any subscribed endpoints — never raises an
    exception to the caller.

    Parameters
    ----------
    project_id:
        UUID of the project that owns the webhooks.
    event:
        Event name, e.g. ``"otp.sent"`` or ``"magic_link.verified"``.
    payload:
        Arbitrary JSON-serialisable dict delivered as the webhook body.
    """
    try:
        webhooks = await asyncio.to_thread(list_webhooks, project_id)
    except Exception:
        logger.exception(
            "fire_event: failed to list webhooks project_id=%s", project_id
        )
        return

    subscribed = [
        w for w in webhooks if w.is_active and event in (w.events or [])
    ]

    if not subscribed:
        return

    try:
        arq_redis = await create_pool(arq_redis_settings())
    except Exception:
        logger.exception("fire_event: failed to connect to Redis")
        return

    try:
        for webhook in subscribed:
            try:
                await arq_redis.enqueue_job(
                    "task_deliver_webhook",
                    webhook.id,
                    webhook.url,
                    webhook.secret_enc,  # AES-encrypted; decrypted inside the task
                    event,
                    payload,
                )
            except Exception:
                logger.exception(
                    "fire_event: failed to enqueue job webhook_id=%s", webhook.id
                )
    finally:
        await arq_redis.aclose()
