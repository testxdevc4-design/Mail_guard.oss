"""
FastAPI IP-rate-limit middleware for MailGuard OSS.

Wraps the synchronous ``core.rate_limiter`` using ``asyncio.to_thread()``
to avoid blocking the async event loop.

Tier enforced at the middleware layer
--------------------------------------
``ip_15min`` — 100 requests per IP per 15 minutes.

Per-key and per-project tiers are checked inside route handlers once the
API key has been resolved by :func:`apps.api.middleware.auth.require_api_key`.

On excess requests the middleware returns::

    HTTP 429  {"error": "rate_limit_exceeded", "retry_after": 900}
    Retry-After: 900
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional

import redis as sync_redis_lib
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import settings
from core.rate_limiter import check_ip_15min

_RETRY_AFTER = 900  # 15 minutes in seconds

_sync_redis: Optional[sync_redis_lib.Redis] = None  # type: ignore[type-arg]


def _get_sync_redis() -> sync_redis_lib.Redis:  # type: ignore[type-arg]
    """Return the shared synchronous Redis client (lazy initialisation)."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = sync_redis_lib.from_url(  # type: ignore[assignment]
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _sync_redis


class RateLimitMiddleware(BaseHTTPMiddleware):
    """IP-level rate-limit middleware.

    Enforces 100 requests per 15 minutes per client IP address.
    Returns ``HTTP 429`` with a ``retry_after`` field when the limit is
    exceeded.

    If Redis is unavailable the middleware *fails open* — requests are
    allowed through rather than blocking all traffic.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ip = request.client.host if request.client else "unknown"

        try:
            redis = _get_sync_redis()
            allowed = await asyncio.to_thread(check_ip_15min, redis, ip)
        except Exception:
            # Fail open: don't block requests when Redis is unreachable
            allowed = True

        if not allowed:
            return Response(
                content=(
                    '{"error":"rate_limit_exceeded",'
                    f'"retry_after":{_RETRY_AFTER}}}'
                ),
                status_code=429,
                headers={
                    "Retry-After": str(_RETRY_AFTER),
                    "Content-Type": "application/json",
                },
            )

        return await call_next(request)
