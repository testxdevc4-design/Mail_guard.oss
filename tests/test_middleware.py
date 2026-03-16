"""
tests/test_middleware.py — Part 05 middleware tests.

Covers:
  1. CORS blocks requests from origins not in ALLOWED_ORIGINS
  2. Security headers present on all responses including errors
  3. Rate limit middleware returns 429 with retry_after on excess requests
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

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from apps.api.middleware.rate_limit import RateLimitMiddleware, _RETRY_AFTER  # noqa: E402
from apps.api.middleware.security_headers import (  # noqa: E402
    SecurityHeadersMiddleware,
)


# ---------------------------------------------------------------------------
# App factories
# ---------------------------------------------------------------------------

def _make_cors_app(allowed_origins: list) -> FastAPI:
    cors_app = FastAPI()
    cors_app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @cors_app.get("/test")
    async def test_route():
        return {"ok": True}

    return cors_app


def _make_security_app() -> FastAPI:
    sec_app = FastAPI()
    sec_app.add_middleware(SecurityHeadersMiddleware)

    @sec_app.get("/ok")
    async def ok_route():
        return {"ok": True}

    @sec_app.get("/error")
    async def error_route():
        return JSONResponse(status_code=500, content={"error": "internal"})

    return sec_app


def _make_rate_limit_app() -> FastAPI:
    rl_app = FastAPI()
    rl_app.add_middleware(RateLimitMiddleware)

    @rl_app.get("/test")
    async def test_route():
        return {"ok": True}

    return rl_app


# ---------------------------------------------------------------------------
# 1. CORS — blocks origins not in ALLOWED_ORIGINS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cors_blocks_unlisted_origin() -> None:
    app = _make_cors_app(allowed_origins=["https://app.example.com"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # Cross-origin preflight from a disallowed origin
        r = await ac.options(
            "/test",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # The disallowed origin must NOT appear in the CORS response header
        acao = r.headers.get("access-control-allow-origin", "")
        assert "evil.example.com" not in acao


@pytest.mark.asyncio
async def test_cors_allows_listed_origin() -> None:
    allowed = "https://app.example.com"
    app = _make_cors_app(allowed_origins=[allowed])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.options(
            "/test",
            headers={
                "Origin": allowed,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.headers.get("access-control-allow-origin") == allowed


# ---------------------------------------------------------------------------
# 2. Security headers present on all responses including errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_security_headers_on_success_response() -> None:
    app = _make_security_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.get("/ok")
        assert r.status_code == 200
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "SAMEORIGIN"
        assert "strict-transport-security" in r.headers
        assert "x-xss-protection" in r.headers


@pytest.mark.asyncio
async def test_security_headers_on_error_response() -> None:
    app = _make_security_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.get("/error")
        assert r.status_code == 500
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "SAMEORIGIN"
        assert "strict-transport-security" in r.headers
        assert "x-xss-protection" in r.headers


# ---------------------------------------------------------------------------
# 3. Rate limit middleware → 429 with retry_after on excess requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_returns_429_after_excess_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After exceeding the IP rate limit the middleware must return 429."""
    call_count = 0

    def _blocked_after_first(redis, ip):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return call_count == 1  # only the very first call is allowed

    monkeypatch.setattr(
        "apps.api.middleware.rate_limit.check_ip_15min",
        _blocked_after_first,
    )
    monkeypatch.setattr(
        "apps.api.middleware.rate_limit._get_sync_redis",
        lambda: None,
    )

    app = _make_rate_limit_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r1 = await ac.get("/test")
        assert r1.status_code == 200

        r2 = await ac.get("/test")
        assert r2.status_code == 429

        body = r2.json()
        assert "retry_after" in body
        assert body["retry_after"] == _RETRY_AFTER
        assert r2.headers.get("retry-after") == str(_RETRY_AFTER)


@pytest.mark.asyncio
async def test_rate_limit_passes_when_under_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requests under the limit must pass through normally."""
    monkeypatch.setattr(
        "apps.api.middleware.rate_limit.check_ip_15min",
        lambda redis, ip: True,
    )
    monkeypatch.setattr(
        "apps.api.middleware.rate_limit._get_sync_redis",
        lambda: None,
    )

    app = _make_rate_limit_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        for _ in range(5):
            r = await ac.get("/test")
            assert r.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Redis raises an exception the middleware must fail open (allow through)."""

    def _raise_on_connect():
        raise ConnectionError("Redis is down")

    monkeypatch.setattr(
        "apps.api.middleware.rate_limit._get_sync_redis",
        _raise_on_connect,
    )

    app = _make_rate_limit_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        r = await ac.get("/test")
        assert r.status_code == 200
