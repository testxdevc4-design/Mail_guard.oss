"""
tests/test_bot_admin_gate.py — Unit tests for apps/bot/middleware/admin_gate.py.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")

from telegram.ext import ApplicationHandlerStop  # noqa: E402

from apps.bot.middleware.admin_gate import admin_gate  # noqa: E402

ADMIN_UID = 1
NON_ADMIN_UID = 9999


def _make_update(user_id: int) -> MagicMock:
    """Build a minimal fake Update with effective_user.id set."""
    user = MagicMock()
    user.id = user_id
    update = MagicMock()
    update.effective_user = user
    return update


def _make_context() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Admin passes through
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_uid_does_not_raise() -> None:
    """The admin UID must not trigger ApplicationHandlerStop."""
    update = _make_update(ADMIN_UID)
    ctx = _make_context()
    # Should return normally (None), not raise
    result = await admin_gate(update, ctx)
    assert result is None


# ---------------------------------------------------------------------------
# Non-admin is silently dropped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_admin_uid_raises_handler_stop() -> None:
    """A non-admin user must cause ApplicationHandlerStop to be raised."""
    update = _make_update(NON_ADMIN_UID)
    ctx = _make_context()
    with pytest.raises(ApplicationHandlerStop):
        await admin_gate(update, ctx)


@pytest.mark.asyncio
async def test_missing_user_raises_handler_stop() -> None:
    """An update with no effective_user must also be dropped."""
    update = MagicMock()
    update.effective_user = None
    ctx = _make_context()
    with pytest.raises(ApplicationHandlerStop):
        await admin_gate(update, ctx)


@pytest.mark.asyncio
async def test_non_admin_receives_no_reply() -> None:
    """The gate must never call any reply method on the update."""
    update = _make_update(NON_ADMIN_UID)
    update.message = AsyncMock()
    ctx = _make_context()
    with pytest.raises(ApplicationHandlerStop):
        await admin_gate(update, ctx)
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_non_admin_uids_are_dropped() -> None:
    """Every non-admin UID must be dropped."""
    for uid in [0, 2, 100, 999999]:
        update = _make_update(uid)
        ctx = _make_context()
        with pytest.raises(ApplicationHandlerStop):
            await admin_gate(update, ctx)
