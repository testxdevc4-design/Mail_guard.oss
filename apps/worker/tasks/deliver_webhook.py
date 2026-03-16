"""
apps/worker/tasks/deliver_webhook.py — ARQ task for delivering webhook events.

Retry policy
------------
Attempt 1 → fails → wait 10 s
Attempt 2 → fails → wait 60 s
Attempt 3 → fails → set webhook failure_count += 1, fire Telegram alert

On success the ``webhooks.last_triggered_at`` column is updated to now().

HTTP transport
--------------
Every delivery is a POST request with a 10-second ``aiohttp.ClientTimeout``.
If the developer's server is slow or unreachable the worker never hangs
indefinitely — a timeout counts as a failure and is retried according to
the schedule above.

Signature header
----------------
Every request carries the header::

    X-MailGuard-Signature: sha256={hex_digest}

The signature is produced by ``core.webhooks.sign_payload`` using the raw
secret decrypted from ``secret_enc`` at delivery time.  The secret itself is
never logged or included in any exception message.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

import aiohttp
import httpx

from core.config import settings
from core.crypto import decrypt
from core.db import get_webhook, update_webhook
from core.webhooks import _serialize_payload, sign_payload

logger = logging.getLogger(__name__)

UTC = timezone.utc

# Retry backoff delays applied *before* attempts 2 and 3.  The third value
# (300 s) is reserved for documentation — it is the delay that would be
# applied before a hypothetical 4th attempt, but we mark the delivery as
# permanently failed after the 3rd attempt instead of sleeping again.
_BACKOFF_DELAYS = (10, 60, 300)
_MAX_ATTEMPTS = 3
_HTTP_TIMEOUT_SECONDS = 10


async def _send_telegram_alert(message: str) -> None:
    """Fire a Telegram message to the configured admin chat."""
    url = (
        f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )
    payload = {"chat_id": settings.TELEGRAM_ADMIN_UID, "text": message}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)
    except Exception as exc:  # noqa: BLE001
        logger.error("Telegram alert failed: %s", type(exc).__name__)


async def task_deliver_webhook(
    ctx: Dict[str, Any],
    webhook_id: str,
    url: str,
    secret_enc: str,
    event: str,
    payload: Dict[str, Any],
) -> None:
    """ARQ task: deliver a webhook event with up to 3 attempts and backoff.

    Parameters
    ----------
    ctx:
        ARQ context dictionary (unused but required by the ARQ contract).
    webhook_id:
        UUID of the ``webhooks`` row — updated on success or permanent failure.
    url:
        Developer's endpoint URL to POST the event payload to.
    secret_enc:
        AES-256-GCM encrypted webhook secret (decrypted inside this task).
    event:
        Event name, e.g. ``"otp.sent"``.
    payload:
        JSON-serialisable dict to deliver as the webhook body.
    """
    # Decrypt the secret inside the task — the raw secret is never logged.
    try:
        raw_secret = decrypt(secret_enc)
    except Exception as exc:
        logger.error(
            "task_deliver_webhook: failed to decrypt secret webhook_id=%s error=%s",
            webhook_id,
            type(exc).__name__,
        )
        return

    # Serialize payload deterministically so the sent bytes match the signature.
    # Both sign_payload() and this send use _serialize_payload() which applies
    # sort_keys=True internally, guaranteeing the signed bytes == wire bytes.
    body_bytes = _serialize_payload(payload)
    signature = sign_payload(raw_secret, payload)
    headers = {
        "Content-Type": "application/json",
        "X-MailGuard-Signature": signature,
        "X-MailGuard-Event": event,
        "User-Agent": "MailGuard-Webhook/1.0",
    }

    timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SECONDS)
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=body_bytes, headers=headers) as resp:
                    if 200 <= resp.status < 300:
                        # Success — update last_triggered_at and return.
                        await asyncio.to_thread(
                            update_webhook,
                            webhook_id,
                            {"last_triggered_at": datetime.now(UTC).isoformat()},
                        )
                        logger.info(
                            "task_deliver_webhook: delivered webhook_id=%s attempt=%d status=%d",
                            webhook_id,
                            attempt,
                            resp.status,
                        )
                        return
                    # Non-2xx response counts as a failure.
                    raise RuntimeError(f"HTTP {resp.status}")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "task_deliver_webhook: attempt %d/%d failed webhook_id=%s error=%s",
                attempt,
                _MAX_ATTEMPTS,
                webhook_id,
                type(exc).__name__,
            )
            if attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                logger.info(
                    "task_deliver_webhook: retrying in %ds webhook_id=%s",
                    delay,
                    webhook_id,
                )
                await asyncio.sleep(delay)

    # All 3 attempts exhausted — mark as permanently failed.
    error_detail = type(last_exc).__name__ if last_exc is not None else "unknown"
    try:
        # Fetch current failure_count and increment it.
        current = await asyncio.to_thread(get_webhook, webhook_id)
        new_count = (current.failure_count + 1) if current is not None else 1
        await asyncio.to_thread(
            update_webhook,
            webhook_id,
            {"failure_count": new_count},
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "task_deliver_webhook: failed to update failure_count webhook_id=%s",
            webhook_id,
        )

    alert_msg = (
        f"[MailGuard] Webhook delivery failed after {_MAX_ATTEMPTS} attempts.\n"
        f"webhook_id: {webhook_id}\n"
        f"url: {url}\n"
        f"event: {event}\n"
        f"error: {error_detail}"
    )
    await _send_telegram_alert(alert_msg)
    logger.error(
        "task_deliver_webhook: permanently failed webhook_id=%s after %d attempts",
        webhook_id,
        _MAX_ATTEMPTS,
    )
