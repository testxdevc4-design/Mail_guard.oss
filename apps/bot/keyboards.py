"""
apps/bot/keyboards.py — Inline keyboard builders for MailGuard bot.
"""
from __future__ import annotations

from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def confirm_cancel_keyboard() -> InlineKeyboardMarkup:
    """Return a two-button Confirm / Cancel inline keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Confirm", callback_data="confirm"),
            InlineKeyboardButton("\u274c Cancel", callback_data="cancel"),
        ]
    ])


def yes_no_keyboard() -> InlineKeyboardMarkup:
    """Return a two-button Yes / No inline keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Yes", callback_data="yes"),
            InlineKeyboardButton("\u274c No", callback_data="no"),
        ]
    ])


def paginated_list_keyboard(
    items: List[str],
    page: int,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """Return an inline keyboard with paginated item rows and Prev/Next controls.

    Parameters
    ----------
    items:
        Full list of item labels.  Each button's ``callback_data`` is
        ``"item:<label>"``.
    page:
        Zero-based current page index.
    page_size:
        Number of items shown per page (default 5).
    """
    total = len(items)
    start = page * page_size
    end = min(start + page_size, total)
    page_items = items[start:end]

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(item, callback_data=f"item:{item}")]
        for item in page_items
    ]

    nav: List[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("\u25c0 Prev", callback_data=f"page:{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next \u25b6", callback_data=f"page:{page + 1}"))
    if nav:
        rows.append(nav)

    return InlineKeyboardMarkup(rows)
