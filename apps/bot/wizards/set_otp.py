"""
apps/bot/wizards/set_otp.py — /setotp ConversationHandler.

Wizard flow
-----------
State 0 — ASK_SLUG
    Ask which project's OTP template to configure (by slug).

State 1 — ASK_SUBJECT
    Ask for the email subject template string.
    Placeholders available: {{project_name}}, {{otp_code}}, {{purpose}}

State 2 — ASK_BODY
    Ask for the email body (plain-text).  Available placeholders:
    {{otp_code}}, {{expiry_minutes}}, {{project_name}}, {{purpose}},
    {{current_year}}

State 3 — PREVIEW_CONFIRM
    Render the template with sample values via Jinja2 and send the
    rendered preview.  The user MUST confirm before the template is saved.
    If they decline the preview step the wizard returns to ASK_BODY.

Template rendering uses Jinja2's from_string() so no file is needed for
previews.  Sample values used in previews:
    otp_code        = "483920"
    expiry_minutes  = 10
    project_name    = <real project name from DB>
    purpose         = "login"
    current_year    = <current UTC year>
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from jinja2 import Environment, TemplateSyntaxError, Undefined
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

from apps.bot.keyboards import yes_no_keyboard
from core.db import get_project_by_slug, update_project

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wizard state constants
# ---------------------------------------------------------------------------

ASK_SLUG = 0
ASK_SUBJECT = 1
ASK_BODY = 2
PREVIEW_CONFIRM = 3

# Sample values used for template preview
_SAMPLE_OTP = "483920"
_SAMPLE_PURPOSE = "login"
_SAMPLE_EXPIRY_MINUTES = 10

# Jinja2 environment for string rendering (autoescape off for plain-text)
# Jinja2 environment for plain-text email body rendering (autoescape intentionally off —
# rendered output is sent as a Telegram message preview, never injected into HTML context)
_jinja = Environment(autoescape=False, undefined=Undefined)  # noqa: S701


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _safe_edit(query: CallbackQuery, text: str, **kwargs: object) -> None:
    try:
        await query.edit_message_text(text, **kwargs)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("_safe_edit: %s", type(exc).__name__)


def _render_preview(template_str: str, project_name: str) -> Optional[str]:
    """Render *template_str* with sample values.  Returns None on syntax error."""
    try:
        tmpl = _jinja.from_string(template_str)
        return tmpl.render(
            otp_code=_SAMPLE_OTP,
            expiry_minutes=_SAMPLE_EXPIRY_MINUTES,
            project_name=project_name,
            purpose=_SAMPLE_PURPOSE,
            current_year=datetime.now(timezone.utc).year,
        )
    except TemplateSyntaxError as exc:
        logger.warning("_render_preview: template syntax error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# State 0 — ASK_SLUG
# ---------------------------------------------------------------------------

async def ask_slug_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Entry point: ask which project to configure."""
    if update.message is None:
        return ConversationHandler.END
    assert context.user_data is not None
    context.user_data.clear()

    # Allow /setotp <slug> as a shortcut
    args = context.args or []
    if args:
        slug = args[0].strip()
        return await _process_slug(update, context, slug)

    await update.message.reply_text(
        "\U0001f4dd *Set OTP Template*\n\n"
        "Enter the project *slug* to configure:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_SLUG


async def receive_slug(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate the slug and ask for the email subject."""
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
        logger.error("set_otp receive_slug: DB error: %s", type(exc).__name__)
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
            "Step 1/3 — Enter the *email subject* template.\n\n"
            "Available placeholders: "
            "`{{project_name}}`, `{{purpose}}`, `{{otp_code}}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    return ASK_SUBJECT


# ---------------------------------------------------------------------------
# State 1 — ASK_SUBJECT
# ---------------------------------------------------------------------------

async def receive_subject(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Store the subject template and ask for the body."""
    if update.message is None or update.message.text is None:
        return ASK_SUBJECT

    subject = update.message.text.strip()
    if not subject:
        await update.message.reply_text(
            "\u274c Subject cannot be empty. Please try again:"
        )
        return ASK_SUBJECT

    assert context.user_data is not None
    context.user_data["template_subject"] = subject

    await update.message.reply_text(
        "Step 2/3 — Enter the *plain-text email body* template.\n\n"
        "Available placeholders:\n"
        "`{{otp_code}}` — the OTP code\n"
        "`{{expiry_minutes}}` — expiry in minutes\n"
        "`{{project_name}}` — project display name\n"
        "`{{purpose}}` — purpose from the API call\n"
        "`{{current_year}}` — current year",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_BODY


# ---------------------------------------------------------------------------
# State 2 — ASK_BODY
# ---------------------------------------------------------------------------

async def receive_body(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Store the body template, render a preview, and ask for confirmation."""
    if update.message is None or update.message.text is None:
        return ASK_BODY

    body = update.message.text.strip()
    if not body:
        await update.message.reply_text(
            "\u274c Body cannot be empty. Please try again:"
        )
        return ASK_BODY

    assert context.user_data is not None
    context.user_data["template_body_text"] = body

    project_name: str = context.user_data.get("project_name", "Demo")

    # Render the preview — mandatory before saving
    preview = _render_preview(body, project_name)
    if preview is None:
        await update.message.reply_text(
            "\u274c Your template contains a Jinja2 syntax error. "
            "Please fix and re-send the body:"
        )
        return ASK_BODY

    subject_tmpl: str = context.user_data.get("template_subject", "")
    subject_preview = _render_preview(subject_tmpl, project_name) or subject_tmpl

    await update.message.reply_text(
        f"*\U0001f4e7 Template Preview*\n\n"
        f"*Subject:* {subject_preview}\n\n"
        f"*Body:*\n```\n{preview}\n```\n\n"
        "Does this look correct? Confirm to save or No to re-enter the body.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=yes_no_keyboard(),
    )
    return PREVIEW_CONFIRM


# ---------------------------------------------------------------------------
# State 3 — PREVIEW_CONFIRM
# ---------------------------------------------------------------------------

async def handle_preview_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Save or reject the template based on the preview confirmation."""
    query = update.callback_query
    if query is None:
        return PREVIEW_CONFIRM
    await query.answer()

    assert context.user_data is not None

    if query.data == "no":
        # User wants to revise — go back to body entry
        await _safe_edit(
            query,
            "Re-enter the *email body* template:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_BODY

    if query.data != "yes":
        return PREVIEW_CONFIRM

    # Save to database
    project_id: str = context.user_data.get("project_id", "")
    subject: str = context.user_data.get("template_subject", "")
    body: str = context.user_data.get("template_body_text", "")

    try:
        update_project(project_id, {
            "template_subject": subject,
            "template_body_text": body,
        })
    except Exception as exc:
        logger.error(
            "handle_preview_confirm: DB update error: %s", type(exc).__name__
        )
        await _safe_edit(query, "\u274c Database error while saving template.")
        return ConversationHandler.END

    slug: str = context.user_data.get("slug", "")
    context.user_data.clear()

    await _safe_edit(
        query,
        f"\u2705 OTP template saved for project *{slug}*.",
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

set_otp_conversation = ConversationHandler(
    entry_points=[CommandHandler("setotp", ask_slug_entry)],
    states={
        ASK_SLUG: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_slug),
        ],
        ASK_SUBJECT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_subject),
        ],
        ASK_BODY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_body),
        ],
        PREVIEW_CONFIRM: [
            CallbackQueryHandler(handle_preview_confirm),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    name="set_otp",
    persistent=True,
)
