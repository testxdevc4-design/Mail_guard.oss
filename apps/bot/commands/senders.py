"""
apps/bot/commands/senders.py — /senders command for MailGuard bot.

/senders
    Lists all sender_emails rows with:
    - email address
    - provider
    - daily limit
    - today's usage percentage fetched from Redis via get_usage_pct()

If Redis has no entry for a sender the display shows 0%.
The database daily_sent column is never consulted here because it does not
track intraday counts — only Redis does (see core/sender_rotation.py).
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from apps.bot.formatters import format_table
from core.db import list_sender_emails
from core.sender_rotation import get_usage_pct

logger = logging.getLogger(__name__)


async def senders_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the /senders command.

    Fetches all sender_emails from Supabase, then queries Redis for each
    sender's current daily usage percentage.  Displays results as a
    formatted table.
    """
    if update.message is None:
        return

    try:
        senders = list_sender_emails()
    except Exception as exc:
        logger.error("senders_command: DB error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not fetch senders from database."
        )
        return

    if not senders:
        await update.message.reply_text("No senders configured yet.")
        return

    # Build rows — fetch Redis usage for each sender (async)
    rows = []
    for s in senders:
        try:
            pct = await get_usage_pct(s)
        except Exception:
            pct = 0.0
        status = "\u2705" if s.is_active else "\u274c"
        rows.append([
            s.email_address,
            s.provider,
            str(s.daily_limit),
            f"{round(pct * 100, 1)}%",
            status,
        ])

    table = format_table(
        ["Email", "Provider", "Limit", "Usage", "Active"],
        rows,
    )

    await update.message.reply_text(
        f"*Senders* ({len(senders)} total)\n\n{table}",
        parse_mode=ParseMode.MARKDOWN,
    )
