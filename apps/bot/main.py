"""
apps/bot/main.py — MailGuard Telegram bot entry point.

Application factory
-------------------
build_application() creates the PTB Application, attaches
SupabasePersistence for session survival across restarts, registers the
admin gate at group=-1 (runs before all other handlers), then registers
the /start command and the /addemail ConversationHandler.

Start command
-------------
    python -m apps.bot.main
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, TypeHandler

from apps.bot.commands.start import start_command
from apps.bot.middleware.admin_gate import admin_gate
from apps.bot.session import SupabasePersistence
from apps.bot.wizards.add_email import add_email_conversation
from core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_application() -> Application:  # type: ignore[type-arg]
    """Create and configure the PTB Application.

    Handler registration order
    --------------------------
    group=-1  TypeHandler(Update, admin_gate)   — runs before everything
    group=0   CommandHandler("start", …)
    group=0   add_email ConversationHandler
    """
    persistence = SupabasePersistence()

    app: Application = (  # type: ignore[type-arg]
        ApplicationBuilder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .persistence(persistence)
        .build()
    )

    # Admin gate must be the very first handler to run for every update.
    # group=-1 ensures it fires before group=0 command/conversation handlers.
    app.add_handler(TypeHandler(Update, admin_gate), group=-1)

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))

    # Conversation handlers
    app.add_handler(add_email_conversation)

    return app


def main() -> None:
    """Build and run the bot (long-polling)."""
    logger.info("Starting MailGuard bot…")
    app = build_application()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
