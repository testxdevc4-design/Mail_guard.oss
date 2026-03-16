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

from apps.bot.commands.keys import genkey_command, keys_command
from apps.bot.commands.logs import logs_command
from apps.bot.commands.projects import delete_project_command, projects_command
from apps.bot.commands.senders import senders_command
from apps.bot.commands.start import start_command
from apps.bot.commands.webhooks import remove_webhook_command, webhooks_command
from apps.bot.middleware.admin_gate import admin_gate
from apps.bot.session import SupabasePersistence
from apps.bot.wizards.add_email import add_email_conversation
from apps.bot.wizards.new_project import new_project_conversation
from apps.bot.wizards.set_otp import set_otp_conversation
from apps.bot.wizards.set_webhook import set_webhook_conversation
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
    app.add_handler(CommandHandler("senders", senders_command))
    app.add_handler(CommandHandler("projects", projects_command))
    app.add_handler(CommandHandler("deleteproject", delete_project_command))
    app.add_handler(CommandHandler("genkey", genkey_command))
    app.add_handler(CommandHandler("keys", keys_command))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("webhooks", webhooks_command))
    app.add_handler(CommandHandler("removewebhook", remove_webhook_command))

    # Conversation handlers
    app.add_handler(add_email_conversation)
    app.add_handler(new_project_conversation)
    app.add_handler(set_otp_conversation)
    app.add_handler(set_webhook_conversation)

    return app


def main() -> None:
    """Build and run the bot (long-polling)."""
    logger.info("Starting MailGuard bot…")
    app = build_application()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
