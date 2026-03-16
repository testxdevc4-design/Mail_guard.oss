"""
apps/bot/session.py — Supabase-backed session persistence for MailGuard bot.

Session data (conversation states, user data, chat data, bot data) is
persisted to the ``bot_sessions`` Supabase table so that wizard state
survives a bot restart or crash mid-flow.

Required table schema (run once in Supabase SQL Editor)
-------------------------------------------------------
    CREATE TABLE IF NOT EXISTS bot_sessions (
        key        TEXT PRIMARY KEY,
        value      JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
"""
from __future__ import annotations

import logging
from typing import Any, Dict, MutableMapping, Optional, Tuple, Union

from telegram.ext import BasePersistence, PersistenceInput

from core.db import get_client

logger = logging.getLogger(__name__)

_KEY_CONVERSATIONS = "conversations"
_KEY_USER_DATA = "user_data"
_KEY_CHAT_DATA = "chat_data"
_KEY_BOT_DATA = "bot_data"


def _db_load(key: str) -> Any:
    """Load a JSON value from bot_sessions by key.  Returns None on error."""
    try:
        res = (
            get_client()
            .table("bot_sessions")
            .select("value")
            .eq("key", key)
            .maybe_single()
            .execute()
        )
        if res.data:
            return res.data["value"]
    except Exception as exc:
        logger.warning("bot_sessions read failed key=%s: %s", key, type(exc).__name__)
    return None


def _db_save(key: str, value: Any) -> None:
    """Upsert a JSON value into bot_sessions.  Logs failures silently."""
    try:
        get_client().table("bot_sessions").upsert(
            {"key": key, "value": value}
        ).execute()
    except Exception as exc:
        logger.warning("bot_sessions write failed key=%s: %s", key, type(exc).__name__)


def _tuple_key(t: Tuple[Union[int, str], ...]) -> str:
    """Serialise a tuple key to a JSON string for storage."""
    import json as _json
    return _json.dumps(list(t))


def _parse_tuple_key(s: str) -> Tuple[Union[int, str], ...]:
    """Deserialise a JSON string back to a tuple key."""
    import json as _json
    return tuple(_json.loads(s))


class SupabasePersistence(BasePersistence):  # type: ignore[misc]
    """Supabase-backed persistence for python-telegram-bot 20.x.

    Stores conversations, user data, chat data and bot data in the
    ``bot_sessions`` table.  All I/O failures are logged silently so a
    temporary database outage never crashes the bot.
    """

    def __init__(self) -> None:
        super().__init__(
            store_data=PersistenceInput(
                bot_data=True,
                chat_data=True,
                user_data=True,
                callback_data=False,
            )
        )
        self._conversations: Dict[str, Dict[str, Any]] = {}
        self._user_data: Dict[int, Dict[str, Any]] = {}
        self._chat_data: Dict[int, Dict[str, Any]] = {}
        self._bot_data: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    async def get_conversations(  # type: ignore[override]
        self, name: str
    ) -> MutableMapping[Tuple[Union[int, str], ...], object]:
        raw = _db_load(_KEY_CONVERSATIONS)
        if isinstance(raw, dict):
            self._conversations = raw
        conv = self._conversations.get(name, {})
        return {_parse_tuple_key(k): v for k, v in conv.items()}

    async def update_conversation(
        self,
        name: str,
        key: Tuple[Union[int, str], ...],
        new_state: Optional[object],
    ) -> None:
        conv = self._conversations.setdefault(name, {})
        str_key = _tuple_key(key)
        if new_state is None:
            conv.pop(str_key, None)
        else:
            conv[str_key] = new_state
        _db_save(_KEY_CONVERSATIONS, self._conversations)

    # ------------------------------------------------------------------
    # User data
    # ------------------------------------------------------------------

    async def get_user_data(self) -> Dict[int, Dict[str, Any]]:  # type: ignore[override]
        raw = _db_load(_KEY_USER_DATA)
        if isinstance(raw, dict):
            self._user_data = {int(k): v for k, v in raw.items()}
        return dict(self._user_data)

    async def update_user_data(self, user_id: int, data: Dict[str, Any]) -> None:
        self._user_data[user_id] = data
        _db_save(_KEY_USER_DATA, {str(k): v for k, v in self._user_data.items()})

    async def drop_user_data(self, user_id: int) -> None:
        self._user_data.pop(user_id, None)
        _db_save(_KEY_USER_DATA, {str(k): v for k, v in self._user_data.items()})

    async def refresh_user_data(  # type: ignore[override]
        self, user_id: int, user_data: Dict[str, Any]
    ) -> None:
        pass

    # ------------------------------------------------------------------
    # Chat data
    # ------------------------------------------------------------------

    async def get_chat_data(self) -> Dict[int, Dict[str, Any]]:  # type: ignore[override]
        raw = _db_load(_KEY_CHAT_DATA)
        if isinstance(raw, dict):
            self._chat_data = {int(k): v for k, v in raw.items()}
        return dict(self._chat_data)

    async def update_chat_data(self, chat_id: int, data: Dict[str, Any]) -> None:
        self._chat_data[chat_id] = data
        _db_save(_KEY_CHAT_DATA, {str(k): v for k, v in self._chat_data.items()})

    async def drop_chat_data(self, chat_id: int) -> None:
        self._chat_data.pop(chat_id, None)
        _db_save(_KEY_CHAT_DATA, {str(k): v for k, v in self._chat_data.items()})

    async def refresh_chat_data(  # type: ignore[override]
        self, chat_id: int, chat_data: Dict[str, Any]
    ) -> None:
        pass

    # ------------------------------------------------------------------
    # Bot data
    # ------------------------------------------------------------------

    async def get_bot_data(self) -> Dict[str, Any]:
        raw = _db_load(_KEY_BOT_DATA)
        if isinstance(raw, dict):
            self._bot_data = raw
        return dict(self._bot_data)

    async def update_bot_data(self, data: Dict[str, Any]) -> None:
        self._bot_data = data
        _db_save(_KEY_BOT_DATA, data)

    async def refresh_bot_data(self, bot_data: Dict[str, Any]) -> None:  # type: ignore[override]
        pass

    # ------------------------------------------------------------------
    # Callback data (not used — callback_data=False in PersistenceInput)
    # ------------------------------------------------------------------

    async def get_callback_data(self) -> None:  # type: ignore[override]
        return None

    async def update_callback_data(self, data: Any) -> None:  # type: ignore[override]
        pass

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    async def flush(self) -> None:
        pass

