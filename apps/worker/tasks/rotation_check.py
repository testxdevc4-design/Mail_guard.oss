"""
apps/worker/tasks/rotation_check.py — ARQ cron task for sender rotation.

Runs every 60 minutes (registered in WorkerSettings.cron_jobs).

For every active project that has a sender assigned, the task calls
``check_and_rotate()`` which:

- Computes the current sender's usage percentage from Redis.
- Rotates to the best available sender when the threshold is met.
- Updates the project's ``sender_email_id`` in Supabase on rotation.
- Fires a Telegram alert with project slug, old sender, new sender, and
  current usage percentage.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.db import list_projects
from core.sender_rotation import check_and_rotate

logger = logging.getLogger(__name__)


async def rotation_check(ctx: dict[str, Any]) -> None:  # noqa: ARG001
    """Check every active project and rotate its sender if threshold is met.

    Parameters
    ----------
    ctx:
        ARQ context dictionary (unused but required by the ARQ cron contract).
    """
    try:
        projects = await asyncio.to_thread(list_projects, True)
    except Exception:
        logger.exception("rotation_check: failed to list active projects")
        return

    # Filter to projects that have a sender assigned.
    projects_with_sender = [p for p in projects if p.sender_email_id is not None]

    for project in projects_with_sender:
        try:
            rotated = await check_and_rotate(project.id)
            if rotated:
                logger.info(
                    "rotation_check: rotated sender for project_id=%s slug=%s",
                    project.id,
                    project.slug,
                )
        except Exception:
            logger.exception(
                "rotation_check: error checking project_id=%s", project.id
            )
