"""
core/sender_rotation.py — Sender rotation logic for MailGuard OSS.

Redis key pattern
-----------------
Daily sender usage is stored under::

    sender:daily:{sender_id}

The counter is incremented via INCR and a TTL of 86400 seconds is set in the
same pipeline immediately after every increment.  This ensures the counter
resets automatically 24 hours after first use.  The TTL is never reset
manually and there is no fixed-midnight rollover — the TTL-based approach is
intentional.

Rotation threshold
------------------
``select_best_sender()`` picks the active sender whose usage percentage is
lowest and still below ``settings.ROTATION_THRESHOLD``.  If every active
sender is at or above the threshold the function falls back to the sender
with the lowest absolute usage percentage so that at least one sender is
always returned (no complete outage).

check_and_rotate()
------------------
Called per-project by the rotation cron job.  When the project's current
sender is at or above the threshold, this function:

1. Calls ``select_best_sender()`` to find the next sender.
2. Updates ``projects.sender_email_id`` in Supabase.
3. Fires a Telegram alert with: project slug, old sender address, new sender
   address, and current usage percentage of the old sender.
4. Returns ``True`` if rotation happened, ``False`` otherwise.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from core.config import settings
from core.db import get_project, get_sender_email, list_sender_emails, update_project
from core.models import SenderEmail
from core.redis_client import get_redis

logger = logging.getLogger(__name__)

_DAILY_TTL = 86_400  # seconds — 24 hours from first use


# ---------------------------------------------------------------------------
# Redis usage helpers
# ---------------------------------------------------------------------------


async def increment_sender_usage(sender_id: str) -> int:
    """Increment the daily send counter for *sender_id* and renew its TTL.

    The INCR and EXPIRE commands are executed in a single pipeline so that a
    crash between them cannot leave a key with no TTL.

    Parameters
    ----------
    sender_id:
        UUID of the sender_emails row.

    Returns
    -------
    int
        The new counter value after the increment.
    """
    redis = await get_redis()
    key = f"sender:daily:{sender_id}"
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, _DAILY_TTL)
    results = await pipe.execute()
    return int(results[0])


async def get_usage_pct(sender: SenderEmail) -> float:
    """Return the sender's current daily usage as a fraction (0.0 – 1.0+).

    Parameters
    ----------
    sender:
        A ``SenderEmail`` model instance; ``daily_limit`` is read from it.

    Returns
    -------
    float
        ``daily_count / daily_limit``.  Returns 0.0 when the Redis key does
        not exist or ``daily_limit`` is zero (to avoid division by zero).
    """
    if sender.daily_limit <= 0:
        return 0.0
    redis = await get_redis()
    key = f"sender:daily:{sender.id}"
    raw = await redis.get(key)
    count = int(raw) if raw is not None else 0
    return count / sender.daily_limit


# ---------------------------------------------------------------------------
# Sender selection
# ---------------------------------------------------------------------------


async def select_best_sender(
    senders: list[SenderEmail],
) -> Optional[SenderEmail]:
    """Pick the best available sender from *senders*.

    Algorithm
    ---------
    1. Filter to ``is_active=True`` senders only.
    2. Among those below ``settings.ROTATION_THRESHOLD``, pick the one with
       the **lowest usage percentage**.
    3. If none are below the threshold (all exhausted), fall back to the
       sender with the **lowest absolute usage percentage** so that a complete
       outage is avoided.
    4. Returns ``None`` only when *senders* is empty after filtering.

    Parameters
    ----------
    senders:
        List of ``SenderEmail`` instances (may be pre-filtered or the full
        list returned by ``list_sender_emails``).

    Returns
    -------
    Optional[SenderEmail]
        The best sender, or ``None`` if no active senders exist at all.
    """
    active = [s for s in senders if s.is_active]
    if not active:
        return None

    # Compute usage percentages once.
    pcts: dict[str, float] = {}
    for sender in active:
        pcts[sender.id] = await get_usage_pct(sender)

    threshold = settings.ROTATION_THRESHOLD

    # Primary: senders below the threshold, ordered by ascending usage.
    below = [s for s in active if pcts[s.id] < threshold]
    if below:
        return min(below, key=lambda s: pcts[s.id])

    # Fallback: all senders exhausted — return lowest-usage sender.
    return min(active, key=lambda s: pcts[s.id])


# ---------------------------------------------------------------------------
# Telegram alert helper
# ---------------------------------------------------------------------------


async def _send_telegram_alert(message: str) -> None:
    url = (
        f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )
    payload = {"chat_id": settings.TELEGRAM_ADMIN_UID, "text": message}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)
    except Exception:  # noqa: BLE001
        logger.error("_send_telegram_alert: failed to send alert")


# ---------------------------------------------------------------------------
# Rotation check
# ---------------------------------------------------------------------------


async def check_and_rotate(project_id: str) -> bool:
    """Check the project's current sender and rotate if threshold is met.

    Steps
    -----
    1. Load the project and its current sender.
    2. Compute the current sender's usage percentage.
    3. If below ``settings.ROTATION_THRESHOLD``, return ``False`` immediately.
    4. Select the best available sender via ``select_best_sender()``.
    5. If the best sender is the *same* as the current one (only one active
       sender exists), do **not** update the DB — just return ``False`` to
       avoid a no-op write.
    6. Update ``projects.sender_email_id`` in Supabase.
    7. Fire a Telegram alert with project slug, old address, new address,
       and current usage percentage of the old sender.
    8. Return ``True``.

    Parameters
    ----------
    project_id:
        UUID of the project to check.

    Returns
    -------
    bool
        ``True`` if rotation happened, ``False`` otherwise.
    """
    project = await asyncio.to_thread(get_project, project_id)
    if project is None:
        logger.warning("check_and_rotate: project not found project_id=%s", project_id)
        return False

    if project.sender_email_id is None:
        logger.warning(
            "check_and_rotate: project has no sender project_id=%s", project_id
        )
        return False

    current_sender = await asyncio.to_thread(get_sender_email, project.sender_email_id)
    if current_sender is None:
        logger.warning(
            "check_and_rotate: sender not found sender_id=%s", project.sender_email_id
        )
        return False

    usage_pct = await get_usage_pct(current_sender)

    if usage_pct < settings.ROTATION_THRESHOLD:
        return False

    # Load all active senders and pick the best one.
    all_senders = await asyncio.to_thread(list_sender_emails, is_active=True)
    if not all_senders:
        logger.warning(
            "check_and_rotate: no active senders for project_id=%s", project_id
        )
        return False

    best = await select_best_sender(all_senders)
    if best is None or best.id == current_sender.id:
        # No rotation possible (only one sender).
        return False

    # Update the project's sender in Supabase.
    await asyncio.to_thread(update_project, project_id, {"sender_email_id": best.id})

    usage_pct_display = round(usage_pct * 100, 1)
    alert_msg = (
        f"[MailGuard] Sender rotated for project '{project.slug}'\n"
        f"Old sender: {current_sender.email_address}\n"
        f"New sender: {best.email_address}\n"
        f"Old sender usage: {usage_pct_display}%"
    )
    await _send_telegram_alert(alert_msg)

    logger.info(
        "check_and_rotate: rotated project_id=%s old=%s new=%s usage=%.1f%%",
        project_id,
        current_sender.email_address,
        best.email_address,
        usage_pct_display,
    )
    return True
