"""
apps/bot/commands/webhooks.py — /webhooks and /removewebhook commands.

/webhooks <slug>
    Lists all webhook endpoints for a project.  The secret is NEVER shown
    (it cannot be retrieved from the database — only the AES-encrypted form
    is stored, and it is never decrypted for display).

/removewebhook <webhook_id>
    Deactivates the specified webhook (sets is_active=False).
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from apps.bot.formatters import format_table
from core.db import get_project_by_slug, get_webhook, list_webhooks, update_webhook

logger = logging.getLogger(__name__)


async def webhooks_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /webhooks <slug> — list webhooks for a project."""
    if update.message is None:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /webhooks <slug>"
        )
        return

    slug = args[0].strip()

    try:
        project = get_project_by_slug(slug)
    except Exception as exc:
        logger.error("webhooks_command: DB error: %s", type(exc).__name__)
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

    try:
        webhooks = list_webhooks(project.id)
    except Exception as exc:
        logger.error("webhooks_command: list error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not fetch webhooks. Please try again."
        )
        return

    if not webhooks:
        await update.message.reply_text(
            f"No webhooks registered for *{slug}*.\n\n"
            "Use /setwebhook to register one.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    rows = []
    for wh in webhooks:
        status = "\u2705" if wh.is_active else "\u274c"
        events_str = ",".join(wh.events)[:30]
        # Truncate ID for display readability
        short_id = wh.id[:8] + "…"
        rows.append([short_id, wh.url[:30], events_str, str(wh.failure_count), status])

    table = format_table(
        ["ID", "URL", "Events", "Fails", "Active"],
        rows,
    )

    await update.message.reply_text(
        f"*Webhooks — {project.name}* ({len(webhooks)} total)\n\n{table}\n\n"
        "_Use /removewebhook <id> to deactivate._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def remove_webhook_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /removewebhook <webhook_id> — deactivate a webhook."""
    if update.message is None:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /removewebhook <webhook_id>"
        )
        return

    webhook_id = args[0].strip()

    try:
        webhook = get_webhook(webhook_id)
    except Exception as exc:
        logger.error("remove_webhook_command: DB error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Database error. Please try again."
        )
        return

    if webhook is None:
        await update.message.reply_text(
            f"\u274c Webhook `{webhook_id}` not found.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not webhook.is_active:
        await update.message.reply_text(
            f"Webhook `{webhook_id}` is already inactive.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        update_webhook(webhook_id, {"is_active": False})
    except Exception as exc:
        logger.error("remove_webhook_command: update error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not deactivate webhook. Please try again."
        )
        return

    await update.message.reply_text(
        f"\u2705 Webhook `{webhook_id}` deactivated.",
        parse_mode=ParseMode.MARKDOWN,
    )
