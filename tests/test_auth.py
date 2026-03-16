"""
tests/test_auth.py — Part 05 API key authentication tests.

Covers:
  1. No Authorization header → 401
  2. Malformed Authorization header → 401
  3. mg_test_ key in production → 403 sandbox_key_in_production
  4. Valid key → 200 and key_row injected into route
  5. Revoked key (is_active=False) → 401
  6. Unknown key hash → 401
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio

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

from fastapi import Depends, FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from apps.api.middleware.auth import require_api_key  # noqa: E402
from core.models import ApiKey  # noqa: E402

UTC = timezone.utc
NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api_key(is_active: bool = True, is_sandbox: bool = False) -> ApiKey:
    return ApiKey(
        id="key-0001",
        project_id="proj-0001",
        key_hash="deadbeef" * 8,
        key_prefix="mg_live_test",
        label="test key",
        is_sandbox=is_sandbox,
        is_active=is_active,
        last_used_at=None,
        created_at=NOW,
    )


def _make_test_app() -> FastAPI:
    """Build a minimal FastAPI app with a single route protected by require_api_key."""
    test_app = FastAPI()

    @test_app.get("/protected")
    async def protected_route(key_row: ApiKey = Depends(require_api_key)):
        return {"key_id": key_row.id, "project_id": key_row.project_id}

    return test_app


@pytest.fixture()
def test_app():
    return _make_test_app()


@pytest_asyncio.fixture()
async def client(test_app):
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test 1: No Authorization header → 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_auth_header_returns_401(client) -> None:
    r = await client.get("/protected")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Test 2: Malformed Authorization header → 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_auth_header_missing_bearer_prefix_returns_401(
    client,
) -> None:
    """Header present but missing 'Bearer ' prefix must return 401."""
    r = await client.get(
        "/protected", headers={"Authorization": "Token abc123"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_malformed_auth_header_basic_scheme_returns_401(client) -> None:
    r = await client.get(
        "/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Test 3: mg_test_ key in production → 403 sandbox_key_in_production
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sandbox_key_in_production_returns_403(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.api_keys.settings.ENV", "production")
    sandbox_key = "mg_test_" + "a" * 64
    r = await client.get(
        "/protected", headers={"Authorization": f"Bearer {sandbox_key}"}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "sandbox_key_in_production"


# ---------------------------------------------------------------------------
# Test 4: Valid key → 200 and key_row injected into route
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_key_returns_200_and_injects_key_row(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_row = _make_api_key(is_active=True)
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    live_key = "mg_live_" + "a" * 64
    r = await client.get(
        "/protected", headers={"Authorization": f"Bearer {live_key}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["key_id"] == key_row.id
    assert body["project_id"] == key_row.project_id


# ---------------------------------------------------------------------------
# Test 5: Revoked key (is_active=False) → 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_revoked_key_returns_401(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_row = _make_api_key(is_active=False)
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    live_key = "mg_live_" + "b" * 64
    r = await client.get(
        "/protected", headers={"Authorization": f"Bearer {live_key}"}
    )
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "revoked_api_key"


# ---------------------------------------------------------------------------
# Test 6: Unknown key hash → 401
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_key_hash_returns_401(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: None)

    unknown_key = "mg_live_" + "c" * 64
    r = await client.get(
        "/protected", headers={"Authorization": f"Bearer {unknown_key}"}
    )
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "invalid_api_key"
