"""
Redis sliding-window rate limiter for MailGuard OSS.

All 5 tiers are implemented.  Each check uses an atomic Redis pipeline
(``zremrangebyscore`` → ``zadd`` → ``zcard`` → ``expire``) so the count can
never be skewed by concurrent requests.

Tier reference
--------------
+--------------------+----------------------------------+-------+---------+
| Name               | Redis key pattern                | Limit | Window  |
+--------------------+----------------------------------+-------+---------+
| email_hourly       | rl:email:{project_id}:{hash}     |    10 | 1 hour  |
| key_hourly         | rl:key:{key_id}                  | 1,000 | 1 hour  |
| ip_15min           | rl:ip:{ip}                       |   100 | 15 min  |
| project_daily      | rl:proj:{project_id}:daily       |10,000 | 24 hrs  |
| sender_daily       | rl:smtp:{sender_id}:daily        |   500 | 24 hrs  |
+--------------------+----------------------------------+-------+---------+
"""
from __future__ import annotations

import time
from typing import Any


# ---------------------------------------------------------------------------
# Core sliding-window primitive
# ---------------------------------------------------------------------------

def _sliding_window(
    redis: Any,
    key: str,
    limit: int,
    window_seconds: int,
) -> bool:
    """Return ``True`` if the request is within the rate limit.

    Uses an atomic Redis pipeline:

    1. ``zremrangebyscore`` — evict events that have fallen outside the window
    2. ``zadd``             — record this event (score = current timestamp)
    3. ``zcard``            — count events remaining in the window
    4. ``expire``           — refresh TTL so idle keys eventually self-clean
    """
    now = time.time()
    window_start = now - window_seconds

    with redis.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        results = pipe.execute()

    count: int = results[2]
    return count <= limit


# ---------------------------------------------------------------------------
# Tier-specific helpers
# ---------------------------------------------------------------------------

def check_email_hourly(redis: Any, project_id: str, email_hash: str) -> bool:
    """Allow at most 10 OTP send requests per email+project per hour."""
    key = f"rl:email:{project_id}:{email_hash}"
    return _sliding_window(redis, key, limit=10, window_seconds=3_600)


def check_key_hourly(redis: Any, key_id: str) -> bool:
    """Allow at most 1,000 requests per API key per hour."""
    key = f"rl:key:{key_id}"
    return _sliding_window(redis, key, limit=1_000, window_seconds=3_600)


def check_ip_15min(redis: Any, ip_address: str) -> bool:
    """Allow at most 100 requests per IP address per 15 minutes."""
    key = f"rl:ip:{ip_address}"
    return _sliding_window(redis, key, limit=100, window_seconds=900)


def check_project_daily(redis: Any, project_id: str) -> bool:
    """Allow at most 10,000 OTPs per project per 24 hours."""
    key = f"rl:proj:{project_id}:daily"
    return _sliding_window(redis, key, limit=10_000, window_seconds=86_400)


def check_sender_daily(redis: Any, sender_id: str) -> bool:
    """Allow at most 500 emails per SMTP sender per 24 hours."""
    key = f"rl:smtp:{sender_id}:daily"
    return _sliding_window(redis, key, limit=500, window_seconds=86_400)
