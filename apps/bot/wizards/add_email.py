"""
apps/bot/wizards/add_email.py — /addemail ConversationHandler.

Flow
----
State 0 — ASK_EMAIL
    Ask for the sender email address.  Validate format and auto-detect
    the SMTP provider from the domain.  For known providers, show the
    detected settings and move to ASK_PASSWORD.  For unknown domains
    (custom), move to ASK_CUSTOM_HOST first.

State 1 — ASK_CUSTOM_HOST  (custom providers only)
    Ask for the SMTP hostname (e.g. smtp.mycompany.com).  Port defaults
    to 587.  After the host is recorded, move to ASK_PASSWORD.

State 2 — ASK_PASSWORD
    Ask for the App Password.  Immediately delete the user's message
    so the password never sits visible in chat history.  Attempt a real
    SMTP login to verify credentials before saving anything.  On
    failure, show the error and remain in ASK_PASSWORD.  On success,
    encrypt the password and insert a row into sender_emails.

Provider detection covers all 6 providers from the build guide:
    Gmail, Outlook/Hotmail, Yahoo, Zoho, iCloud, custom.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import aiosmtplib
from email_validator import EmailNotValidError, validate_email
from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from apps.bot.keyboards import confirm_cancel_keyboard
from core.crypto import encrypt
from core.db import get_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wizard states
# ---------------------------------------------------------------------------

ASK_EMAIL = 0
ASK_CUSTOM_HOST = 1
ASK_PASSWORD = 2

# Default daily sending limit for new senders
_DEFAULT_DAILY_LIMIT = 450

# Default SMTP port for custom providers
_CUSTOM_PORT = 587

# ---------------------------------------------------------------------------
# Provider table  {domain: (label, smtp_host, smtp_port)}
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, tuple[str, str, int]] = {
    "gmail.com": ("Gmail", "smtp.gmail.com", 465),
    "googlemail.com": ("Gmail", "smtp.gmail.com", 465),
    "outlook.com": ("Outlook", "smtp.office365.com", 587),
    "hotmail.com": ("Outlook", "smtp.office365.com", 587),
    "live.com": ("Outlook", "smtp.office365.com", 587),
    "msn.com": ("Outlook", "smtp.office365.com", 587),
    "yahoo.com": ("Yahoo", "smtp.mail.yahoo.com", 465),
    "ymail.com": ("Yahoo", "smtp.mail.yahoo.com", 465),
    "zoho.com": ("Zoho", "smtp.zoho.com", 465),
    "zohomail.com": ("Zoho", "smtp.zoho.com", 465),
    "icloud.com": ("iCloud", "smtp.mail.me.com", 587),
    "me.com": ("iCloud", "smtp.mail.me.com", 587),
    "mac.com": ("iCloud", "smtp.mail.me.com", 587),
}


# RFC 1123 hostname pattern: labels of 1-63 alphanumeric/hyphen chars
# separated by dots; hyphens may not start or end a label.
_HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"\.)*[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$"
)


# ---------------------------------------------------------------------------
# SMTP verification
# ---------------------------------------------------------------------------

async def _verify_smtp(host: str, port: int, username: str, password: str) -> None:
    """Attempt a real SMTP login to verify credentials.

    Raises an exception on authentication failure or network error.
    The password is never logged.
    """
    use_tls = port == 465
    smtp = aiosmtplib.SMTP(hostname=host, port=port, use_tls=use_tls, timeout=15)
    try:
        await smtp.connect()
        if not use_tls:
            await smtp.starttls()
        await smtp.login(username, password)
    finally:
        try:
            await smtp.quit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _safe_delete(message: Optional[Message]) -> None:
    """Delete *message* silently (e.g. message too old → log, no crash)."""
    if message is None:
        return
    try:
        await message.delete()
    except Exception as exc:
        logger.warning(
            "Could not delete App Password message: %s", type(exc).__name__
        )


# ---------------------------------------------------------------------------
# State 0 — ASK_EMAIL
# ---------------------------------------------------------------------------

async def ask_email_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Entry point: prompt the user for a sender email address."""
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text(
        "Please enter the *sender email address* you want to add "
        "(e.g. you@gmail.com):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_EMAIL


async def receive_email(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate the email and detect the SMTP provider."""
    if update.message is None or update.message.text is None:
        return ASK_EMAIL

    raw = update.message.text.strip()

    # --- validate format
    try:
        info = validate_email(raw, check_deliverability=False)
        email = info.normalized
    except EmailNotValidError:
        await update.message.reply_text(
            "\u274c That doesn't look like a valid email address. "
            "Please try again:"
        )
        return ASK_EMAIL

    assert context.user_data is not None
    context.user_data["email"] = email
    domain = email.split("@", 1)[1].lower()

    if domain in _PROVIDERS:
        label, host, port = _PROVIDERS[domain]
        context.user_data["provider"] = label
        context.user_data["smtp_host"] = host
        context.user_data["smtp_port"] = port
        await update.message.reply_text(
            f"\u2705 Detected provider: *{label}*\n"
            f"SMTP: `{host}:{port}`\n\n"
            "Now send the *App Password* for this account.\n"
            "_Your message will be deleted immediately after processing._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_PASSWORD
    else:
        # Custom provider
        context.user_data["provider"] = "custom"
        context.user_data["smtp_port"] = _CUSTOM_PORT
        await update.message.reply_text(
            f"Domain *{domain}* not recognised as a known provider.\n"
            "Please enter the *SMTP hostname* "
            "(e.g. smtp.mycompany.com):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_CUSTOM_HOST


# ---------------------------------------------------------------------------
# State 1 — ASK_CUSTOM_HOST
# ---------------------------------------------------------------------------

async def receive_custom_host(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Record the custom SMTP host and move to the password state."""
    if update.message is None or update.message.text is None:
        return ASK_CUSTOM_HOST

    host = update.message.text.strip()
    if not _HOSTNAME_RE.match(host):
        await update.message.reply_text(
            "\u274c That doesn't look like a valid hostname. Please try again:"
        )
        return ASK_CUSTOM_HOST

    assert context.user_data is not None
    context.user_data["smtp_host"] = host
    port = context.user_data.get("smtp_port", _CUSTOM_PORT)

    await update.message.reply_text(
        f"\u2705 SMTP host set: `{host}:{port}`\n\n"
        "Now send the *App Password* for this account.\n"
        "_Your message will be deleted immediately after processing._",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_PASSWORD


# ---------------------------------------------------------------------------
# State 2 — ASK_PASSWORD
# ---------------------------------------------------------------------------

async def receive_password(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Verify SMTP, encrypt password, and save to the database."""
    if update.message is None or update.message.text is None:
        return ASK_PASSWORD

    password_msg = update.message
    raw_password: Optional[str] = password_msg.text.strip() or None

    assert context.user_data is not None
    email: str = context.user_data.get("email", "")
    host: str = context.user_data.get("smtp_host", "")
    port: int = context.user_data.get("smtp_port", 465)
    provider: str = context.user_data.get("provider", "custom")

    if not raw_password:
        await _safe_delete(password_msg)
        await password_msg.reply_text("\u274c Empty password. Please try again:")
        return ASK_PASSWORD

    # ── Attempt SMTP verification ──────────────────────────────────────
    smtp_ok = False
    error_str = ""
    try:
        await _verify_smtp(host, port, email, raw_password)
        smtp_ok = True
    except Exception as exc:
        error_str = type(exc).__name__

    # ── Encrypt before zeroing the raw value ──────────────────────────
    encrypted = encrypt(raw_password) if smtp_ok else ""
    raw_password = None  # zero the password from memory

    # ── Delete the App Password message regardless of outcome ─────────
    await _safe_delete(password_msg)

    if not smtp_ok:
        await password_msg.reply_text(
            f"\u274c SMTP verification failed: *{error_str}*\n\n"
            "Please send the App Password again (or /cancel to abort):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_PASSWORD

    # ── Save to database ───────────────────────────────────────────────
    try:
        # Use upsert so re-adding the same address updates credentials
        # rather than raising a duplicate-key error.
        get_client().table("sender_emails").upsert({
            "email_address": email,
            "display_name": email.split("@")[0],
            "provider": provider,
            "smtp_host": host,
            "smtp_port": port,
            "app_password_enc": encrypted,
            "daily_limit": _DEFAULT_DAILY_LIMIT,
            "daily_sent": 0,
            "is_active": True,
        }, on_conflict="email_address").execute()
    except Exception as exc:
        logger.error("Failed to save sender_email: %s", type(exc).__name__)
        await password_msg.reply_text(
            "\u274c Database error while saving. Please try /addemail again."
        )
        return ConversationHandler.END

    await password_msg.reply_text(
        f"\u2705 *{email}* ({provider}) added successfully!\n"
        "SMTP verified \u2014 credentials saved securely.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=confirm_cancel_keyboard(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the wizard and clear user data."""
    assert context.user_data is not None
    context.user_data.clear()
    if update.message:
        await update.message.reply_text(
            "Wizard cancelled.", reply_markup=None
        )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ConversationHandler
# ---------------------------------------------------------------------------

add_email_conversation = ConversationHandler(
    entry_points=[CommandHandler("addemail", ask_email_entry)],
    states={
        ASK_EMAIL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email),
        ],
        ASK_CUSTOM_HOST: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_host),
        ],
        ASK_PASSWORD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    name="add_email",
    persistent=True,
)
