"""
apps/bot/wizards/set_webhook.py — /setwebhook ConversationHandler.

Wizard flow
-----------
State 0 — ASK_SLUG
    Ask which project to register a webhook for (by slug).

State 1 — ASK_URL
    Ask for the target HTTPS URL (must start with http:// or https://).

State 2 — ASK_EVENTS
    Ask for the comma-separated list of event names to subscribe to
    (e.g. ``otp.sent, magic_link.verified``).

State 3 — CONFIRM
    Generate a 256-bit webhook secret with ``secrets.token_hex(32)``.
    Show it ONCE in a Telegram message with the HMAC-SHA256 verification
    code snippet so the developer can immediately implement signature
    verification.  Then store the secret as AES-256-GCM encrypted value
    (``secret_enc``) in the database — it must be reversible at delivery
    time for signing.  The plaintext is explicitly set to None after the
    message is sent.

Security contract
-----------------
- The plaintext secret is shown in exactly ONE message and then zeroed.
- The database stores ONLY the AES-encrypted form (never plaintext).
- The secret is never logged.
- Signing uses HMAC-SHA256 via ``core.webhooks.sign_payload()``.

Verification snippet sent to developer
---------------------------------------
    import hashlib, hmac, json

    payload_bytes = json.dumps(payload, sort_keys=True,
                                separators=(",", ":")).encode()
    expected = hmac.new(
        secret.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    assert hmac.compare_digest(
        f"sha256={expected}",
        request.headers["X-MailGuard-Signature"],
    )
"""
from __future__ import annotations

import logging
import secrets

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

from apps.bot.keyboards import confirm_cancel_keyboard
from core.crypto import encrypt
from core.db import get_project_by_slug, insert_webhook

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wizard state constants
# ---------------------------------------------------------------------------

ASK_SLUG = 0
ASK_URL = 1
ASK_EVENTS = 2
CONFIRM = 3

_VERIFICATION_SNIPPET = """\
```python
import hashlib, hmac, json

payload_bytes = json.dumps(
    payload, sort_keys=True, separators=(",", ":")
).encode()
expected = hmac.new(
    secret.encode(), payload_bytes, hashlib.sha256
).hexdigest()
assert hmac.compare_digest(
    f"sha256={expected}",
    request.headers["X-MailGuard-Signature"],
)
```"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _safe_edit(query: CallbackQuery, text: str, **kwargs: object) -> None:
    try:
        await query.edit_message_text(text, **kwargs)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("_safe_edit: %s", type(exc).__name__)


# ---------------------------------------------------------------------------
# State 0 — ASK_SLUG
# ---------------------------------------------------------------------------

async def ask_slug_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Entry point: ask which project to attach the webhook to."""
    if update.message is None:
        return ConversationHandler.END
    assert context.user_data is not None
    context.user_data.clear()

    # Allow /setwebhook <slug> as a shortcut
    args = context.args or []
    if args:
        slug = args[0].strip()
        return await _process_slug(update, context, slug)

    await update.message.reply_text(
        "\U0001f310 *Register Webhook*\n\n"
        "Enter the project *slug* to attach the webhook to:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_SLUG


async def receive_slug(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate the slug and ask for the webhook URL."""
    if update.message is None or update.message.text is None:
        return ASK_SLUG
    slug = update.message.text.strip()
    return await _process_slug(update, context, slug)


async def _process_slug(
    update: Update, context: ContextTypes.DEFAULT_TYPE, slug: str
) -> int:
    try:
        project = get_project_by_slug(slug)
    except Exception as exc:
        logger.error("set_webhook receive_slug: DB error: %s", type(exc).__name__)
        if update.message:
            await update.message.reply_text(
                "\u274c Database error. Please try again:"
            )
        return ASK_SLUG

    if project is None:
        if update.message:
            await update.message.reply_text(
                f"\u274c Project *{slug}* not found. Please try again:",
                parse_mode=ParseMode.MARKDOWN,
            )
        return ASK_SLUG

    assert context.user_data is not None
    context.user_data["project_id"] = project.id
    context.user_data["project_name"] = project.name
    context.user_data["slug"] = slug

    if update.message:
        await update.message.reply_text(
            f"*Project:* {project.name} (`{slug}`)\n\n"
            "Step 1/2 — Enter the *webhook endpoint URL*\n"
            "(must start with https://):",
            parse_mode=ParseMode.MARKDOWN,
        )
    return ASK_URL


# ---------------------------------------------------------------------------
# State 1 — ASK_URL
# ---------------------------------------------------------------------------

async def receive_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate the webhook URL and ask for events."""
    if update.message is None or update.message.text is None:
        return ASK_URL

    url = update.message.text.strip()

    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            "\u274c URL must start with https:// (or http:// for testing). "
            "Please try again:"
        )
        return ASK_URL

    assert context.user_data is not None
    context.user_data["url"] = url

    await update.message.reply_text(
        "Step 2/2 — Enter the *events* to subscribe to as a comma-separated list.\n\n"
        "Available events:\n"
        "`otp.sent` `otp.verified` `otp.failed`\n"
        "`magic_link.sent` `magic_link.verified`\n\n"
        "Example: `otp.sent, otp.verified`",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_EVENTS


# ---------------------------------------------------------------------------
# State 2 — ASK_EVENTS
# ---------------------------------------------------------------------------

async def receive_events(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate events list and show confirmation with the one-time secret."""
    if update.message is None or update.message.text is None:
        return ASK_EVENTS

    raw = update.message.text.strip()
    events = [e.strip() for e in raw.split(",") if e.strip()]

    if not events:
        await update.message.reply_text(
            "\u274c Please enter at least one event name. Example: `otp.sent`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_EVENTS

    assert context.user_data is not None
    context.user_data["events"] = events

    url: str = context.user_data.get("url", "")
    slug: str = context.user_data.get("slug", "")
    events_display = ", ".join(events)

    summary = (
        f"*Webhook Summary*\n\n"
        f"*Project:* `{slug}`\n"
        f"*URL:* `{url}`\n"
        f"*Events:* {events_display}\n\n"
        "A unique signing secret will be generated on confirmation.\n"
        "Confirm to register or cancel to abort."
    )

    await update.message.reply_text(
        summary,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=confirm_cancel_keyboard(),
    )
    return CONFIRM


# ---------------------------------------------------------------------------
# State 3 — CONFIRM
# ---------------------------------------------------------------------------

async def handle_confirm_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Generate the webhook secret, register the webhook, and show the secret once."""
    query = update.callback_query
    if query is None:
        return CONFIRM
    await query.answer()

    assert context.user_data is not None

    if query.data == "cancel":
        context.user_data.clear()
        await _safe_edit(query, "\u274c Webhook registration cancelled.")
        return ConversationHandler.END

    if query.data != "confirm":
        return CONFIRM

    project_id: str = context.user_data.get("project_id", "")
    url: str = context.user_data.get("url", "")
    events: list[str] = context.user_data.get("events", [])

    # Generate 256-bit secret — shown once, then zeroed
    raw_secret: str | None = secrets.token_hex(32)

    # Encrypt for storage (AES-256-GCM — must be reversible for HMAC signing at delivery)
    secret_enc = encrypt(raw_secret)

    # Insert webhook row
    try:
        webhook = insert_webhook({
            "project_id": project_id,
            "url": url,
            "secret_enc": secret_enc,
            "events": events,
            "is_active": True,
            "failure_count": 0,
        })
    except Exception as exc:
        logger.error(
            "handle_confirm_callback: DB insert error: %s", type(exc).__name__
        )
        # Zero the secret even on error — never log it
        raw_secret = None
        await _safe_edit(
            query,
            "\u274c Database error while registering webhook. Please try again."
        )
        return ConversationHandler.END

    # Send the secret in ONE message — zero it immediately after
    if update.effective_message:
        await update.effective_message.reply_text(
            f"\u2705 *Webhook registered!*\n\n"
            f"*ID:* `{webhook.id}`\n"
            f"*URL:* `{url}`\n\n"
            f"\U0001f512 *Signing Secret — shown ONCE, save it now:*\n\n"
            f"`{raw_secret}`\n\n"
            f"*Verification code for your server:*\n{_VERIFICATION_SNIPPET}\n\n"
            f"_This secret cannot be retrieved again._",
            parse_mode=ParseMode.MARKDOWN,
        )
    raw_secret = None  # explicit discard — never log, never store again

    context.user_data.clear()
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

set_webhook_conversation = ConversationHandler(
    entry_points=[CommandHandler("setwebhook", ask_slug_entry)],
    states={
        ASK_SLUG: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_slug),
        ],
        ASK_URL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url),
        ],
        ASK_EVENTS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_events),
        ],
        CONFIRM: [
            CallbackQueryHandler(handle_confirm_callback),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    name="set_webhook",
    persistent=True,
)
