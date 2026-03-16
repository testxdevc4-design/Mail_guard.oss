"""
apps/bot/commands/start.py — /start command for MailGuard bot.

Checks four live systems and reports each status individually:
  1. Supabase DB   — lightweight SELECT on the projects table
  2. Redis         — PING
  3. Internal API  — GET INTERNAL_API_URL/health
  4. Bot itself    — always OK if /start is responding
"""
from __future__ import annotations

import logging

import httpx

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from apps.bot.formatters import format_status_line
from core.config import settings
from core.db import get_client
from core.redis_client import get_redis

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check 4 live systems and send a status report to the admin."""
    if update.message is None:
        return

    lines = ["*MailGuard Status*\n"]

    # ── 1. Supabase DB ────────────────────────────────────────────────
    db_ok = False
    try:
        get_client().table("projects").select("id").limit(1).execute()
        db_ok = True
    except Exception:
        pass
    lines.append(format_status_line("Supabase DB", db_ok))

    # ── 2. Redis ──────────────────────────────────────────────────────
    redis_ok = False
    try:
        redis = await get_redis()
        await redis.ping()
        redis_ok = True
    except Exception:
        pass
    lines.append(format_status_line("Redis", redis_ok))

    # ── 3. Internal API ───────────────────────────────────────────────
    api_ok = False
    if settings.INTERNAL_API_URL:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.INTERNAL_API_URL}/health")
                api_ok = resp.status_code == 200
        except Exception:
            pass
    lines.append(format_status_line("Internal API", api_ok))

    # ── 4. Bot itself ─────────────────────────────────────────────────
    lines.append(format_status_line("Bot", True))

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )
