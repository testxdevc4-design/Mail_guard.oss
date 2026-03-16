"""
apps/bot/commands/projects.py — /projects and /deleteproject commands.

/projects
    Lists all projects with:
    - name and slug
    - sender email (or "—" if unassigned)
    - active / inactive status

/deleteproject <slug>
    Deactivates the project by setting is_active=False.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from apps.bot.formatters import format_table
from core.db import get_project_by_slug, get_sender_email, list_projects, update_project

logger = logging.getLogger(__name__)


async def projects_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /projects — list all projects."""
    if update.message is None:
        return

    try:
        projects = list_projects()
    except Exception as exc:
        logger.error("projects_command: DB error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not fetch projects from database."
        )
        return

    if not projects:
        await update.message.reply_text(
            "No projects yet.  Use /newproject to create one."
        )
        return

    rows = []
    for p in projects:
        # Resolve sender email address
        sender_addr = "\u2014"
        if p.sender_email_id:
            try:
                sender = get_sender_email(p.sender_email_id)
                if sender:
                    sender_addr = sender.email_address
            except Exception:
                pass
        status = "\u2705" if p.is_active else "\u274c"
        rows.append([p.name, p.slug, sender_addr, status])

    table = format_table(
        ["Name", "Slug", "Sender", "Active"],
        rows,
    )

    await update.message.reply_text(
        f"*Projects* ({len(projects)} total)\n\n{table}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def delete_project_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /deleteproject <slug> — deactivate a project."""
    if update.message is None:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /deleteproject <slug>"
        )
        return

    slug = args[0].strip()

    try:
        project = get_project_by_slug(slug)
    except Exception as exc:
        logger.error("delete_project_command: DB error: %s", type(exc).__name__)
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

    if not project.is_active:
        await update.message.reply_text(
            f"Project *{slug}* is already inactive.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        update_project(project.id, {"is_active": False})
    except Exception as exc:
        logger.error("delete_project_command: update error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not deactivate project. Please try again."
        )
        return

    await update.message.reply_text(
        f"\u2705 Project *{slug}* deactivated.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def activateproject_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /activateproject <slug> — re-activate a project."""
    if update.message is None:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /activateproject <slug>\n\n"
            "Provide the project slug to re-activate (visible in /projects)."
        )
        return

    slug = args[0].strip()

    try:
        project = get_project_by_slug(slug)
    except Exception as exc:
        logger.error("activateproject_command: DB error: %s", type(exc).__name__)
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

    if project.is_active:
        await update.message.reply_text(
            f"Project *{slug}* is already active.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        update_project(project.id, {"is_active": True})
    except Exception as exc:
        logger.error("activateproject_command: update error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not activate project. Please try again."
        )
        return

    await update.message.reply_text(
        f"\u2705 Project *{slug}* activated.",
        parse_mode=ParseMode.MARKDOWN,
    )
