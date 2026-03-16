"""
apps/bot/wizards/new_project.py — /newproject ConversationHandler.

Wizard flow
-----------
State 0 — ASK_NAME
    Ask for the project display name (1–100 characters).

State 1 — ASK_SLUG
    Ask for the URL slug.  Validated to be:
    - Lowercase alphanumeric with hyphens only (regex ``[a-z0-9-]+``)
    - At most 50 characters
    - Unique across all existing projects
    If validation fails the error is shown and the wizard stays in ASK_SLUG.

State 2 — ASK_SENDER
    Show a paginated InlineKeyboard of active senders via
    ``paginated_list_keyboard()``.  The user selects one by tapping a button
    (callback_data format: ``"item:<email_address>"``).
    Page navigation uses ``"page:<n>"`` callback_data.

State 3 — ASK_OTP_EXPIRY
    Ask for OTP expiry in seconds.  Valid range: 60–86400.  Default: 600.

State 4 — CONFIRM
    Show a summary of all collected settings and present
    ``confirm_cancel_keyboard()``.  On "confirm" the project row is inserted.
    On "cancel" the wizard is aborted.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from telegram import CallbackQuery, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from apps.bot.keyboards import confirm_cancel_keyboard, paginated_list_keyboard
from core.db import (
    get_project_by_slug,
    insert_project,
    list_sender_emails,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wizard state constants
# ---------------------------------------------------------------------------

ASK_NAME = 0
ASK_SLUG = 1
ASK_SENDER = 2
ASK_OTP_EXPIRY = 3
CONFIRM = 4

# Slug validation — lowercase alphanumeric + hyphens, no leading/trailing hyphens
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_SLUG_MAX_LEN = 50

# OTP expiry limits (seconds)
_OTP_EXPIRY_MIN = 60
_OTP_EXPIRY_MAX = 86_400
_OTP_EXPIRY_DEFAULT = 600

# Defaults for fields not collected in this wizard
_OTP_LENGTH = 6
_OTP_MAX_ATTEMPTS = 5
_RATE_LIMIT_PER_HOUR = 60
_DEFAULT_SUBJECT = "Your {{project_name}} verification code"
_DEFAULT_BODY_TEXT = (
    "Your one-time code is: {{otp_code}}\n\n"
    "This code expires in {{expiry_minutes}} minutes."
)
_DEFAULT_BODY_HTML = (
    "<p>Your one-time code is: <strong>{{otp_code}}</strong></p>"
    "<p>This code expires in {{expiry_minutes}} minutes.</p>"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _safe_edit(query: CallbackQuery, text: str, **kwargs: object) -> None:
    """Edit the message text and suppress any exceptions."""
    try:
        await query.edit_message_text(text, **kwargs)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("_safe_edit: %s", type(exc).__name__)


async def _show_sender_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
    *,
    edit: bool = False,
) -> None:
    """Send or update the paginated sender selection keyboard."""
    assert context.user_data is not None
    senders: list[str] = context.user_data.get("sender_emails", [])
    kb = paginated_list_keyboard(senders, page=page)
    text = (
        "\U0001f4e7 *Select a sender email*\n\n"
        "Tap a sender to assign it to this project:"
    )
    if edit and update.callback_query:
        await _safe_edit(
            update.callback_query,
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
    elif update.message:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )


# ---------------------------------------------------------------------------
# State 0 — ASK_NAME
# ---------------------------------------------------------------------------

async def ask_name_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Entry point: ask for the project display name."""
    if update.message is None:
        return ConversationHandler.END
    assert context.user_data is not None
    context.user_data.clear()
    await update.message.reply_text(
        "\U0001f4c1 *New Project Wizard*\n\n"
        "Step 1/5 — Enter the *project display name* (1–100 characters):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_NAME


async def receive_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate and store project name, then ask for slug."""
    if update.message is None or update.message.text is None:
        return ASK_NAME

    name = update.message.text.strip()
    if not name or len(name) > 100:
        await update.message.reply_text(
            "\u274c Name must be 1–100 characters. Please try again:"
        )
        return ASK_NAME

    assert context.user_data is not None
    context.user_data["name"] = name

    await update.message.reply_text(
        f"Step 2/5 — Enter the *URL slug* for this project.\n\n"
        f"Rules: lowercase letters, digits, and hyphens only; "
        f"max {_SLUG_MAX_LEN} characters; must be unique.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_SLUG


# ---------------------------------------------------------------------------
# State 1 — ASK_SLUG
# ---------------------------------------------------------------------------

async def receive_slug(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate slug (format, length, uniqueness) then show sender list."""
    if update.message is None or update.message.text is None:
        return ASK_SLUG

    slug = update.message.text.strip().lower()

    # Format check
    if not slug or len(slug) > _SLUG_MAX_LEN or not _SLUG_RE.match(slug):
        await update.message.reply_text(
            "\u274c Invalid slug.  Use only lowercase letters, digits, and hyphens "
            f"(max {_SLUG_MAX_LEN} chars, must not start or end with a hyphen). "
            "Please try again:"
        )
        return ASK_SLUG

    # Uniqueness check
    try:
        existing = get_project_by_slug(slug)
    except Exception as exc:
        logger.error("receive_slug: DB error: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Database error while checking slug. Please try again:"
        )
        return ASK_SLUG

    if existing is not None:
        await update.message.reply_text(
            f"\u274c Slug *{slug}* is already taken. Please choose a different slug:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_SLUG

    assert context.user_data is not None
    context.user_data["slug"] = slug

    # Fetch active senders for the next step
    try:
        senders = list_sender_emails(is_active=True)
    except Exception as exc:
        logger.error("receive_slug: failed to list senders: %s", type(exc).__name__)
        await update.message.reply_text(
            "\u274c Could not load senders. Please try again."
        )
        return ConversationHandler.END

    if not senders:
        await update.message.reply_text(
            "\u274c No active senders found.  "
            "Please add a sender first with /addemail."
        )
        return ConversationHandler.END

    # Store sender list in session for lookup after selection
    context.user_data["sender_emails"] = [s.email_address for s in senders]
    context.user_data["sender_map"] = {s.email_address: s.id for s in senders}

    await _show_sender_page(update, context, page=0)
    return ASK_SENDER


# ---------------------------------------------------------------------------
# State 2 — ASK_SENDER (InlineKeyboard callbacks)
# ---------------------------------------------------------------------------

async def handle_sender_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle sender selection or pagination callbacks."""
    query = update.callback_query
    if query is None:
        return ASK_SENDER
    await query.answer()

    data: Optional[str] = query.data

    assert context.user_data is not None

    if data and data.startswith("page:"):
        # Pagination — update the keyboard in place
        try:
            page = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            return ASK_SENDER
        await _show_sender_page(update, context, page=page, edit=True)
        return ASK_SENDER

    if data and data.startswith("item:"):
        email = data.split(":", 1)[1]
        sender_map: dict[str, str] = context.user_data.get("sender_map", {})
        sender_id = sender_map.get(email)
        if not sender_id:
            await query.answer("Sender not found — please try again.", show_alert=True)
            return ASK_SENDER

        context.user_data["sender_email"] = email
        context.user_data["sender_id"] = sender_id

        await _safe_edit(
            query,
            f"\u2705 Sender selected: *{email}*\n\n"
            f"Step 4/5 — Enter the *OTP expiry* in seconds.\n"
            f"Valid range: {_OTP_EXPIRY_MIN}–{_OTP_EXPIRY_MAX}. "
            f"Default: {_OTP_EXPIRY_DEFAULT}.\n\n"
            f"Send a number or type `default` to use {_OTP_EXPIRY_DEFAULT}s:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_OTP_EXPIRY

    return ASK_SENDER


# ---------------------------------------------------------------------------
# State 3 — ASK_OTP_EXPIRY
# ---------------------------------------------------------------------------

async def receive_otp_expiry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate OTP expiry and move to confirmation."""
    if update.message is None or update.message.text is None:
        return ASK_OTP_EXPIRY

    raw = update.message.text.strip()

    if raw.lower() == "default":
        expiry = _OTP_EXPIRY_DEFAULT
    else:
        try:
            expiry = int(raw)
        except ValueError:
            await update.message.reply_text(
                f"\u274c Please enter a whole number between "
                f"{_OTP_EXPIRY_MIN} and {_OTP_EXPIRY_MAX} "
                f"(or `default` for {_OTP_EXPIRY_DEFAULT}s):",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ASK_OTP_EXPIRY

    if not (_OTP_EXPIRY_MIN <= expiry <= _OTP_EXPIRY_MAX):
        await update.message.reply_text(
            f"\u274c OTP expiry must be between {_OTP_EXPIRY_MIN} and "
            f"{_OTP_EXPIRY_MAX} seconds. Please try again:"
        )
        return ASK_OTP_EXPIRY

    assert context.user_data is not None
    context.user_data["otp_expiry_seconds"] = expiry

    # Build and show the confirmation summary
    name = context.user_data.get("name", "")
    slug = context.user_data.get("slug", "")
    sender_email = context.user_data.get("sender_email", "")
    expiry_mins = round(expiry / 60, 1)

    summary = (
        "\U0001f4cb *Project Summary — please confirm:*\n\n"
        f"*Name:* {name}\n"
        f"*Slug:* `{slug}`\n"
        f"*Sender:* {sender_email}\n"
        f"*OTP expiry:* {expiry}s ({expiry_mins} min)\n"
        f"*OTP length:* {_OTP_LENGTH} digits\n"
        f"*Max attempts:* {_OTP_MAX_ATTEMPTS}\n"
        f"*Rate limit:* {_RATE_LIMIT_PER_HOUR}/hour\n\n"
        "Confirm to create the project or cancel to abort."
    )

    await update.message.reply_text(
        summary,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=confirm_cancel_keyboard(),
    )
    return CONFIRM


# ---------------------------------------------------------------------------
# State 4 — CONFIRM
# ---------------------------------------------------------------------------

async def handle_confirm_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle confirmation or cancellation of the new project wizard."""
    query = update.callback_query
    if query is None:
        return CONFIRM
    await query.answer()

    assert context.user_data is not None

    if query.data == "cancel":
        context.user_data.clear()
        await _safe_edit(query, "\u274c Project creation cancelled.")
        return ConversationHandler.END

    if query.data != "confirm":
        return CONFIRM

    name = context.user_data.get("name", "")
    slug = context.user_data.get("slug", "")
    sender_id = context.user_data.get("sender_id")
    otp_expiry = context.user_data.get("otp_expiry_seconds", _OTP_EXPIRY_DEFAULT)

    try:
        insert_project({
            "name": name,
            "slug": slug,
            "sender_email_id": sender_id,
            "otp_length": _OTP_LENGTH,
            "otp_expiry_seconds": otp_expiry,
            "otp_max_attempts": _OTP_MAX_ATTEMPTS,
            "rate_limit_per_hour": _RATE_LIMIT_PER_HOUR,
            "template_subject": _DEFAULT_SUBJECT,
            "template_body_text": _DEFAULT_BODY_TEXT,
            "template_body_html": _DEFAULT_BODY_HTML,
            "is_active": True,
        })
    except Exception as exc:
        logger.error("handle_confirm_callback: DB insert error: %s", type(exc).__name__)
        await _safe_edit(
            query,
            "\u274c Database error while creating project. Please try again."
        )
        return ConversationHandler.END

    context.user_data.clear()
    await _safe_edit(
        query,
        f"\u2705 Project *{slug}* created successfully!\n\n"
        f"Use /setotp {slug} to customise the OTP email template.\n"
        f"Use /genkey {slug} to generate an API key.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the wizard at any stage."""
    assert context.user_data is not None
    context.user_data.clear()
    if update.message:
        await update.message.reply_text("Wizard cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ConversationHandler
# ---------------------------------------------------------------------------

new_project_conversation = ConversationHandler(
    entry_points=[CommandHandler("newproject", ask_name_entry)],
    states={
        ASK_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name),
        ],
        ASK_SLUG: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_slug),
        ],
        ASK_SENDER: [
            CallbackQueryHandler(handle_sender_callback),
        ],
        ASK_OTP_EXPIRY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_otp_expiry),
        ],
        CONFIRM: [
            CallbackQueryHandler(handle_confirm_callback),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    name="new_project",
    persistent=True,
)
