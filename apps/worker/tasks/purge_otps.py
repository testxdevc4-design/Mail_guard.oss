"""
apps/worker/tasks/purge_otps.py — ARQ cron task to purge expired OTP records.

Runs every 15 minutes via ARQ's cron scheduler (registered in WorkerSettings).

Deletes all rows from ``otp_records`` where:
  - ``expires_at < now()``   AND
  - ``is_verified = false``

These rows are no longer useful — the OTP has expired and was never consumed.
Keeping them indefinitely would grow the table unboundedly.
"""
from __future__ import annotations

import logging
from typing import Any

from core.db import get_client

logger = logging.getLogger(__name__)


async def purge_expired_otps(ctx: dict[str, Any]) -> None:  # noqa: ARG001
    """Delete expired, unverified OTP records from the database.

    This function is invoked by ARQ's cron scheduler every 15 minutes.
    It uses a raw Supabase RPC-style filter rather than a hand-rolled SQL
    string so that the existing service-role client handles auth transparently.

    Parameters
    ----------
    ctx:
        ARQ context dictionary (provided by the scheduler; not used here).
    """
    try:
        client = get_client()
        result = (
            client
            .table("otp_records")
            .delete()
            .lt("expires_at", "now()")
            .eq("is_verified", False)
            .execute()
        )
        deleted_count = len(result.data) if result.data else 0
        logger.info("purge_expired_otps: deleted %d expired OTP record(s)", deleted_count)
    except Exception as exc:  # noqa: BLE001
        logger.error("purge_expired_otps: error during purge: %s", type(exc).__name__)
