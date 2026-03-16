"""
apps/bot/commands/logs.py — /logs command variants for MailGuard bot.

Four variants are supported, all dispatched from a single command handler:

/logs
    Last 20 email_logs entries across all projects, newest first.

/logs <slug>
    Last 20 entries for the project identified by *slug*.

/logs --failed
    All failed deliveries (status='failed'), newest first, limit 20.

/logs --today
    All deliveries today (UTC midnight onwards), newest first, limit 20.

Privacy: recipient_hash (HMAC-SHA256) is shown in every row — the raw email
address is never stored in email_logs so it cannot be displayed here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from apps.bot.formatters import format_table
from core.db import get_project_by_slug, list_email_logs_paged

logger = logging.getLogger(__name__)

_LIMIT = 20
_FLAG_FAILED = "--failed"
_FLAG_TODAY = "--today"


async def logs_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /logs, /logs <slug>, /logs --failed, /logs --today."""
    if update.message is None:
        return

    args = context.args or []

    project_id: str | None = None
    status: str | None = None
    since: datetime | None = None
    label = "all projects"

    if not args:
        # /logs — last 20 across all projects
        pass

    elif args[0] == _FLAG_FAILED:
        # /logs --failed
        status = "failed"
        label = "failed deliveries"

    elif args[0] == _FLAG_TODAY:
        # /logs --today — from UTC midnight
        now = datetime.now(timezone.utc)
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = f"today ({now.strftime('%Y-%m-%d')} UTC)"

    else:
        # /logs <slug>
        slug = args[0].strip()
        try:
            project = get_project_by_slug(slug)
        except Exception as exc:
            logger.error("logs_command: DB error: %s", type(exc).__name__)
            await update.message.reply_text(
                "\u274c Database error. Please try again."
            )
            return

        if project is None:
            await update.message.reply_text(
                f"\u274c Project *{slug}* not found.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        project_id = project.id
        label = f"project *{slug}*"

    try:
        logs = list_email_logs_paged(
            project_id=project_id,
            status=status,
            since=since,
            limit=_LIMIT,
        )
    except Exception as exc:
        logger.error("logs_command: query error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not fetch logs. Please try again."
        )
        return

    if not logs:
        await update.message.reply_text(
            f"No log entries found for {label}."
        )
        return

    rows = []
    for entry in logs:
        sent = entry.sent_at.strftime("%m-%d %H:%M")
        rows.append([
            sent,
            entry.type,
            entry.status,
            entry.purpose[:12],
            entry.recipient_hash[:12] + "…",  # truncated HMAC — never raw email
        ])

    table = format_table(
        ["Sent", "Type", "Status", "Purpose", "Recipient"],
        rows,
    )

    header_label = label if not label.startswith("project") else label
    await update.message.reply_text(
        f"*Logs — {header_label}* (last {len(logs)})\n\n{table}",
        parse_mode=ParseMode.MARKDOWN,
    )
