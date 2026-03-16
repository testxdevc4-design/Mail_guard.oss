"""
apps/bot/middleware/admin_gate.py — Silent admin-only gate.

This handler must be registered as a TypeHandler in group=-1 so it runs
before every command, conversation, and callback handler.

Security contract
-----------------
* No reply is sent to unauthorised users.
* No typing indicator is triggered.
* No log entry containing the user's ID or any identifying information
  is emitted.
* ApplicationHandlerStop is raised immediately so no downstream handler
  ever sees the update.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from core.config import settings


async def admin_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Silently drop every update that does not come from the admin UID."""
    user = update.effective_user
    if user is None or user.id != settings.TELEGRAM_ADMIN_UID:
        raise ApplicationHandlerStop
