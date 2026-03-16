"""
tests/test_bot_keyboards.py — Unit tests for apps/bot/keyboards.py.
"""
from __future__ import annotations

import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")

from apps.bot.keyboards import (  # noqa: E402
    confirm_cancel_keyboard,
    paginated_list_keyboard,
    yes_no_keyboard,
)


# ---------------------------------------------------------------------------
# confirm_cancel_keyboard
# ---------------------------------------------------------------------------

def test_confirm_cancel_keyboard_has_two_buttons() -> None:
    kb = confirm_cancel_keyboard()
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 2


def test_confirm_cancel_keyboard_callback_data() -> None:
    kb = confirm_cancel_keyboard()
    data = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert "confirm" in data
    assert "cancel" in data


# ---------------------------------------------------------------------------
# yes_no_keyboard
# ---------------------------------------------------------------------------

def test_yes_no_keyboard_has_two_buttons() -> None:
    kb = yes_no_keyboard()
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 2


def test_yes_no_keyboard_callback_data() -> None:
    kb = yes_no_keyboard()
    data = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert "yes" in data
    assert "no" in data


# ---------------------------------------------------------------------------
# paginated_list_keyboard
# ---------------------------------------------------------------------------

def test_paginated_list_single_page() -> None:
    items = ["a", "b", "c"]
    kb = paginated_list_keyboard(items, page=0)
    data = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert "item:a" in data
    assert "item:b" in data
    assert "item:c" in data
    # No nav buttons on single page
    nav_data = [d for d in data if d and d.startswith("page:")]
    assert nav_data == []


def test_paginated_list_first_page_has_next() -> None:
    items = [str(i) for i in range(10)]
    kb = paginated_list_keyboard(items, page=0, page_size=5)
    data = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert "page:1" in data
    assert "page:-1" not in data


def test_paginated_list_last_page_has_prev() -> None:
    items = [str(i) for i in range(10)]
    kb = paginated_list_keyboard(items, page=1, page_size=5)
    data = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert "page:0" in data
    assert "page:2" not in data


def test_paginated_list_middle_page_has_both_nav() -> None:
    items = [str(i) for i in range(15)]
    kb = paginated_list_keyboard(items, page=1, page_size=5)
    data = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert "page:0" in data
    assert "page:2" in data


def test_paginated_list_shows_only_current_page_items() -> None:
    items = ["x", "y", "z", "w", "v", "u"]
    kb = paginated_list_keyboard(items, page=1, page_size=5)
    # Page 1 shows only the 6th item: "u"
    data = {btn.callback_data for row in kb.inline_keyboard for btn in row}
    assert "item:u" in data
    assert "item:x" not in data


def test_paginated_list_empty_items() -> None:
    kb = paginated_list_keyboard([], page=0)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert buttons == []


def test_paginated_list_default_page_size_is_five() -> None:
    items = [str(i) for i in range(10)]
    kb = paginated_list_keyboard(items, page=0)
    item_buttons = [
        btn
        for row in kb.inline_keyboard
        for btn in row
        if btn.callback_data and btn.callback_data.startswith("item:")
    ]
    assert len(item_buttons) == 5
