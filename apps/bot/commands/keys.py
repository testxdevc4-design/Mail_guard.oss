"""
apps/bot/commands/keys.py — /genkey and /keys commands for MailGuard bot.

Security contract
-----------------
/genkey <slug> [label]
    Generates a new API key for the project identified by *slug*.
    The plaintext key is sent in exactly ONE Telegram message and then the
    variable is explicitly set to None.  It is never logged, never stored in
    user_data, and never included in any other message.  The database stores
    only the SHA-256 hash (key_hash) — see core/api_keys.py.

/keys <slug>
    Lists active API keys for a project.  Only the key_prefix column is
    displayed — never the key_hash, never the full plaintext.  The prefix
    is the first 12 characters of the original plaintext (stored at
    creation time) and cannot be used to reconstruct the full key.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from apps.bot.formatters import format_table
from core.api_keys import generate_api_key, revoke_api_key
from core.db import get_api_key, get_project_by_slug, list_api_keys

logger = logging.getLogger(__name__)


async def genkey_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /genkey <slug> [label].

    The plaintext key is shown in one message and immediately zeroed.
    """
    if update.message is None:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /genkey <slug> [label]"
        )
        return

    slug = args[0].strip()
    label = " ".join(args[1:]).strip() if len(args) > 1 else ""

    # Look up project
    try:
        project = get_project_by_slug(slug)
    except Exception as exc:
        logger.error("genkey_command: DB error: %s", type(exc).__name__)
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

    # Generate key — plaintext returned exactly once
    try:
        plaintext, key_row = generate_api_key(
            project_id=project.id,
            label=label,
            is_sandbox=False,
        )
    except Exception as exc:
        logger.error("genkey_command: key generation error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Failed to generate API key. Please try again."
        )
        return

    # Send the key in ONE message — then zero the plaintext immediately
    await update.message.reply_text(
        "\U0001f511 *Your API key — shown ONCE, copy it now:*\n\n"
        f"`{plaintext}`\n\n"
        f"*Prefix:* `{key_row.key_prefix}`\n"
        f"*Project:* {project.name}\n"
        f"*Label:* {label or '(none)'}\n\n"
        "_This key will never be shown again._",
        parse_mode=ParseMode.MARKDOWN,
    )
    plaintext = None  # explicit discard — never log, never store

    logger.info(
        "genkey_command: key generated project_id=%s prefix=%s",
        project.id,
        key_row.key_prefix,
    )


async def keys_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /keys <slug> — list active API keys (prefix only).

    The key_hash is never displayed.  Only the key_prefix column is shown.
    """
    if update.message is None:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /keys <slug>"
        )
        return

    slug = args[0].strip()

    # Look up project
    try:
        project = get_project_by_slug(slug)
    except Exception as exc:
        logger.error("keys_command: DB error: %s", type(exc).__name__)
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
        keys = list_api_keys(project.id)
    except Exception as exc:
        logger.error("keys_command: list error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not fetch API keys. Please try again."
        )
        return

    active_keys = [k for k in keys if k.is_active]

    if not active_keys:
        await update.message.reply_text(
            f"No active API keys for *{slug}*.\n\nUse /genkey {slug} to create one.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    rows = []
    for k in active_keys:
        created = k.created_at.strftime("%Y-%m-%d")
        rows.append([
            k.key_prefix,   # ONLY the prefix — never key_hash
            k.label or "(none)",
            "sandbox" if k.is_sandbox else "live",
            created,
        ])

    table = format_table(
        ["Prefix", "Label", "Type", "Created"],
        rows,
    )

    await update.message.reply_text(
        f"*API Keys — {project.name}* ({len(active_keys)} active)\n\n{table}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def revokekey_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /revokekey <key_id> — revoke an API key by its UUID.

    The key is deactivated (is_active=False) and cannot be used for new requests.
    """
    if update.message is None:
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /revokekey <key_id>\n\n"
            "Provide the UUID of the API key to revoke (visible in /keys <slug>)."
        )
        return

    key_id = args[0].strip()

    try:
        key = get_api_key(key_id)
    except Exception as exc:
        logger.error("revokekey_command: DB error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Database error. Please try again."
        )
        return

    if key is None:
        await update.message.reply_text(
            f"\u274c API key *{key_id}* not found.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        revoke_api_key(key.id)
    except Exception as exc:
        logger.error("revokekey_command: revoke error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not revoke API key. Please try again."
        )
        return

    await update.message.reply_text(
        f"\u2705 API key *{key.key_prefix}…* revoked.",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info("revokekey_command: key revoked id=%s", key.id)
