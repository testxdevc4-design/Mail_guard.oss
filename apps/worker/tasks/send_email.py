"""
apps/worker/tasks/send_email.py — ARQ task for dispatching a single email.

Retry policy
------------
Attempt 1 → fails → wait 10 s
Attempt 2 → fails → wait 60 s
Attempt 3 → fails → set email_log status to 'failed', fire Telegram alert

The task accepts an ``email_log_id`` identifying a pre-created row in the
``email_logs`` table.  On success the row status is updated to ``'delivered'``.

Security note
-------------
The SMTP password is handled exclusively inside ``core.smtp.send_email``
which zeroes the variable in a ``finally`` block.  This task never touches
raw credentials.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from core.config import settings
from core.db import get_sender_email, update_email_log
from core.sender_rotation import increment_sender_usage
from core.smtp import send_email

logger = logging.getLogger(__name__)

# Retry backoff delays in seconds: 10 s after 1st failure, 60 s after 2nd.
_BACKOFF_DELAYS = (10, 60, 300)
_MAX_ATTEMPTS = 3


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


async def task_send_email(
    ctx: dict[str, Any],
    email_log_id: str,
    to_address: str,
    subject: str,
    text_body: str,
    html_body: str,
    sender_id: str,
) -> None:
    """ARQ task: send an email with up to 3 attempts and exponential back-off.

    Parameters
    ----------
    ctx:
        ARQ context dictionary (unused but required by the ARQ contract).
    email_log_id:
        UUID of the ``email_logs`` row to update on success or failure.
    to_address:
        Recipient email address (plaintext — not hashed).
    subject:
        Email subject line.
    text_body:
        Plain-text email body.
    html_body:
        HTML email body.
    sender_id:
        UUID of the ``sender_emails`` row to use for dispatch.
    """
    sender = get_sender_email(sender_id)
    if sender is None:
        logger.error("task_send_email: sender not found sender_id=%s", sender_id)
        update_email_log(email_log_id, {"status": "failed", "error_detail": "sender_not_found"})
        return

    last_exc: Exception | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            await send_email(
                sender=sender,
                to_address=to_address,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
            )
            # Success — update log, track usage, and return.
            update_email_log(email_log_id, {"status": "delivered"})
            try:
                await increment_sender_usage(sender_id)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "task_send_email: failed to increment sender usage sender_id=%s",
                    sender_id,
                )
            logger.info(
                "task_send_email: delivered email_log_id=%s attempt=%d",
                email_log_id,
                attempt,
            )
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "task_send_email: attempt %d/%d failed email_log_id=%s error=%s",
                attempt,
                _MAX_ATTEMPTS,
                email_log_id,
                type(exc).__name__,
            )
            if attempt < _MAX_ATTEMPTS:
                delay = _BACKOFF_DELAYS[attempt - 1]
                logger.info(
                    "task_send_email: retrying in %ds email_log_id=%s",
                    delay,
                    email_log_id,
                )
                await asyncio.sleep(delay)

    # All 3 attempts exhausted.
    error_detail = type(last_exc).__name__ if last_exc is not None else "unknown"
    update_email_log(
        email_log_id,
        {"status": "failed", "error_detail": error_detail},
    )
    alert_msg = (
        f"[MailGuard] Email delivery failed after {_MAX_ATTEMPTS} attempts.\n"
        f"email_log_id: {email_log_id}\n"
        f"error: {error_detail}"
    )
    await _send_telegram_alert(alert_msg)
    logger.error(
        "task_send_email: permanently failed email_log_id=%s after %d attempts",
        email_log_id,
        _MAX_ATTEMPTS,
    )
