"""
tests/test_rate_limiter.py — Part 04 Redis sliding-window rate limiter tests.

Covers:
  - Sliding window allows requests up to the limit
  - The (limit + 1)-th request is blocked
  - Each tier uses its own isolated Redis key
  - Requests outside the window are evicted and no longer counted
  - All 5 tier helper functions enforce their configured limits
"""
from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Env vars must be set before importing any app module
# ---------------------------------------------------------------------------
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")

from core.rate_limiter import (  # noqa: E402
    _sliding_window,
    check_email_hourly,
    check_ip_15min,
    check_key_hourly,
    check_project_daily,
    check_sender_daily,
)


# ---------------------------------------------------------------------------
# Minimal in-memory Redis mock for sorted-set operations
# ---------------------------------------------------------------------------

class _FakePipeline:
    """Executes pipeline commands against the parent store immediately."""

    def __init__(self, store: "_FakeRedis") -> None:
        self._store = store
        self._cmds: list[tuple] = []

    def zremrangebyscore(self, key: str, min_score: float | str, max_score: float) -> "_FakePipeline":
        self._cmds.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zadd(self, key: str, mapping: dict) -> "_FakePipeline":
        self._cmds.append(("zadd", key, mapping))
        return self

    def zcard(self, key: str) -> "_FakePipeline":
        self._cmds.append(("zcard", key))
        return self

    def expire(self, key: str, seconds: int) -> "_FakePipeline":
        # no-op in the fake — keys never expire during a test run
        self._cmds.append(("expire", key, seconds))
        return self

    def execute(self) -> list:
        results = []
        for cmd in self._cmds:
            op = cmd[0]
            if op == "zremrangebyscore":
                _, key, min_s, max_s = cmd
                zset = self._store._zsets.setdefault(key, {})
                lo = float("-inf") if min_s == "-inf" else float(min_s)
                hi = float(max_s)
                removed = [m for m, s in list(zset.items()) if lo <= s <= hi]
                for m in removed:
                    del zset[m]
                results.append(len(removed))

            elif op == "zadd":
                _, key, mapping = cmd
                zset = self._store._zsets.setdefault(key, {})
                for member, score in mapping.items():
                    zset[member] = score
                results.append(len(mapping))

            elif op == "zcard":
                _, key = cmd
                results.append(len(self._store._zsets.get(key, {})))

            elif op == "expire":
                results.append(1)

        return results

    def __enter__(self) -> "_FakePipeline":
        return self

    def __exit__(self, *_: object) -> None:
        pass


class _FakeRedis:
    """Minimal in-memory Redis emulator for sorted-set sliding-window tests."""

    def __init__(self) -> None:
        self._zsets: dict[str, dict[str, float]] = {}

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self)

    def delete(self, *keys: str) -> None:
        for k in keys:
            self._zsets.pop(k, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def redis() -> _FakeRedis:
    return _FakeRedis()


# ---------------------------------------------------------------------------
# Core sliding window — allow up to limit, block at limit+1
# ---------------------------------------------------------------------------

def test_sliding_window_allows_requests_up_to_limit(redis: _FakeRedis) -> None:
    key = "test:window:basic"
    for i in range(5):
        assert _sliding_window(redis, key, limit=5, window_seconds=60) is True


def test_sliding_window_blocks_at_limit_plus_one(redis: _FakeRedis) -> None:
    key = "test:window:block"
    for _ in range(10):
        _sliding_window(redis, key, limit=10, window_seconds=60)
    # 11th request must be blocked
    assert _sliding_window(redis, key, limit=10, window_seconds=60) is False


def test_sliding_window_exact_limit_is_allowed(redis: _FakeRedis) -> None:
    key = "test:window:exact"
    # First (limit-1) requests must succeed
    for _ in range(2):
        _sliding_window(redis, key, limit=3, window_seconds=60)
    # The Nth request where N == limit must still be allowed (count == limit)
    assert _sliding_window(redis, key, limit=3, window_seconds=60) is True


def test_sliding_window_one_over_limit_is_blocked(redis: _FakeRedis) -> None:
    key = "test:window:over"
    for _ in range(4):
        _sliding_window(redis, key, limit=3, window_seconds=60)
    assert _sliding_window(redis, key, limit=3, window_seconds=60) is False


# ---------------------------------------------------------------------------
# Window expiry — old events are evicted
# ---------------------------------------------------------------------------

def test_sliding_window_evicts_old_events(monkeypatch: pytest.MonkeyPatch, redis: _FakeRedis) -> None:
    """Events from before the window must be evicted and not counted."""
    key = "test:window:evict"
    t_base = 1_000_000.0

    # Simulate 5 requests at t=0 (inside a 60-second window viewed from t=0)
    call_count = 0

    def fake_time() -> float:
        nonlocal call_count
        call_count += 1
        return t_base if call_count <= 5 * 4 else t_base + 61.0  # 4 pipeline ops per call

    monkeypatch.setattr("core.rate_limiter.time.time", fake_time)

    for _ in range(5):
        _sliding_window(redis, key, limit=5, window_seconds=60)

    # Now time is 61 seconds later — all 5 earlier events are outside the window
    result = _sliding_window(redis, key, limit=5, window_seconds=60)
    assert result is True  # fresh window, only 1 event now


# ---------------------------------------------------------------------------
# Tier isolation — different tiers use different Redis keys
# ---------------------------------------------------------------------------

def test_tier_isolation_email_and_ip(redis: _FakeRedis) -> None:
    """Exhausting the email tier must not affect the IP tier."""
    project_id = "proj-001"
    email_hash = "abc123"
    ip = "1.2.3.4"

    # Exhaust email_hourly (limit=10)
    for _ in range(11):
        check_email_hourly(redis, project_id, email_hash)

    # IP tier must still be unaffected
    assert check_ip_15min(redis, ip) is True


def test_tier_isolation_key_and_project(redis: _FakeRedis) -> None:
    """Exhausting the key tier must not affect the project daily tier."""
    key_id = "key-abc"
    project_id = "proj-002"

    for _ in range(1_001):
        check_key_hourly(redis, key_id)

    assert check_project_daily(redis, project_id) is True


def test_tier_isolation_two_different_emails(redis: _FakeRedis) -> None:
    """Rate limit on one email must not affect a different email in same project."""
    project_id = "proj-003"
    hash_a = "aaaa"
    hash_b = "bbbb"

    for _ in range(11):
        check_email_hourly(redis, project_id, hash_a)

    assert check_email_hourly(redis, project_id, hash_b) is True


# ---------------------------------------------------------------------------
# Each tier enforces its own configured limit
# ---------------------------------------------------------------------------

def test_email_hourly_limit(redis: _FakeRedis) -> None:
    for _ in range(10):
        assert check_email_hourly(redis, "p1", "h1") is True
    assert check_email_hourly(redis, "p1", "h1") is False


def test_key_hourly_limit(redis: _FakeRedis) -> None:
    for _ in range(1_000):
        assert check_key_hourly(redis, "k1") is True
    assert check_key_hourly(redis, "k1") is False


def test_ip_15min_limit(redis: _FakeRedis) -> None:
    for _ in range(100):
        assert check_ip_15min(redis, "10.0.0.1") is True
    assert check_ip_15min(redis, "10.0.0.1") is False


def test_project_daily_limit(redis: _FakeRedis) -> None:
    for _ in range(10_000):
        assert check_project_daily(redis, "proj-x") is True
    assert check_project_daily(redis, "proj-x") is False


def test_sender_daily_limit(redis: _FakeRedis) -> None:
    for _ in range(500):
        assert check_sender_daily(redis, "smtp-1") is True
    assert check_sender_daily(redis, "smtp-1") is False


# ---------------------------------------------------------------------------
# Reset after window expires — manual key deletion simulates expiry
# ---------------------------------------------------------------------------

def test_reset_after_window_expires(redis: _FakeRedis) -> None:
    """After the window key is deleted (simulating TTL expiry), the counter resets."""
    project_id = "proj-reset"
    email_hash = "reset_hash"
    key = f"rl:email:{project_id}:{email_hash}"

    # Fill up the email hourly limit
    for _ in range(11):
        check_email_hourly(redis, project_id, email_hash)

    blocked = check_email_hourly(redis, project_id, email_hash)
    assert blocked is False

    # Simulate TTL expiry by deleting the key
    redis.delete(key)

    # Counter should now be reset — requests allowed again
    assert check_email_hourly(redis, project_id, email_hash) is True
