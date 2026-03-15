"""
Async Redis / ARQ connection pool for MailGuard OSS.

Usage
-----
from core.redis_client import get_redis, close_redis

# anywhere in an async context:
r = await get_redis()
await r.set("key", "value")
await close_redis()
"""
from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis
from arq.connections import RedisSettings

from core.config import settings

_pool: Optional[aioredis.Redis] = None  # type: ignore[type-arg]


async def get_redis() -> aioredis.Redis:  # type: ignore[type-arg]
    """Return the shared async Redis connection (creates it on first call)."""
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _pool


async def close_redis() -> None:
    """Close and release the shared Redis connection pool."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def arq_redis_settings() -> RedisSettings:
    """Return an ARQ ``RedisSettings`` object built from ``REDIS_URL``.

    Pass the return value directly to ``arq.worker.Worker`` or
    ``WorkerSettings.redis_settings``.
    """
    return RedisSettings.from_dsn(settings.REDIS_URL)
