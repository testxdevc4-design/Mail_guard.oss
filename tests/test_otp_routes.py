"""
tests/test_otp_routes.py — Part 07 OTP route tests.

Covers all 9 required HTTP status codes and scenarios:
  1. 200 verified:true with JWT in response       (verify endpoint)
  2. 400 invalid_code with attempts_remaining      (verify endpoint)
  3. 401 missing/invalid Authorization header      (send + verify endpoints)
  4. 403 sandbox_key_in_production                 (send endpoint)
  5. 410 otp_expired for used/expired OTP          (verify endpoint)
  6. 422 validation_error for malformed email       (send endpoint)
  7. 423 account_locked after max attempts          (verify endpoint)
  8. 429 rate_limit_exceeded with retry_after       (send endpoint)
  9. 503 when Supabase is unreachable               (send + verify endpoints)

Also:
  - 200 happy-path for send (masked_email shape)
  - Timing floor: 10 calls to /send, each >= 190 ms
    (route enforces a 200 ms floor; 10 ms tolerance in assertions accounts
    for scheduling jitter on the test runner)
"""
from __future__ import annotations

import os
import time
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

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from apps.api.routes import otp as otp_module  # noqa: E402
from core.models import ApiKey, EmailLog, Project  # noqa: E402

UTC = timezone.utc
NOW = datetime.now(UTC)

_LIVE_KEY = "mg_live_" + "a" * 64
_TEST_KEY = "mg_test_" + "a" * 64
_PROJECT_ID = "proj-0001"
_KEY_ID = "key-0001"


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------

def _make_api_key(is_active: bool = True, is_sandbox: bool = False) -> ApiKey:
    return ApiKey(
        id=_KEY_ID,
        project_id=_PROJECT_ID,
        key_hash="dead" * 16,
        key_prefix="mg_live_test",
        label="test",
        is_sandbox=is_sandbox,
        is_active=is_active,
        last_used_at=None,
        created_at=NOW,
    )


def _make_project(sender_email_id: str | None = None) -> Project:
    """Return a minimal Project fixture.

    ``sender_email_id=None`` skips the email-enqueue path so tests that
    don't care about email delivery stay simple.
    """
    return Project(
        id=_PROJECT_ID,
        name="Test Project",
        slug="test-project",
        sender_email_id=sender_email_id,
        otp_length=6,
        otp_expiry_seconds=300,
        otp_max_attempts=5,
        rate_limit_per_hour=100,
        template_subject="Your code",
        template_body_text="Code: {{ otp_code }}",
        template_body_html="<b>Code: {{ otp_code }}</b>",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _make_email_log() -> EmailLog:
    return EmailLog(
        id="log-0001",
        project_id=_PROJECT_ID,
        sender_id="sender-001",
        recipient_hash="abc123",
        purpose="login",
        type="otp",
        status="queued",
        error_detail=None,
        sent_at=NOW,
    )


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------

async def _async_noop(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """Async no-op used to mock _enqueue_email in tests."""


# ---------------------------------------------------------------------------
# App factory and fixtures
# ---------------------------------------------------------------------------

def _make_test_app() -> FastAPI:
    """Minimal FastAPI app containing only the OTP router."""
    app = FastAPI()
    app.include_router(otp_module.router)
    return app


@pytest.fixture()
def test_app() -> FastAPI:
    return _make_test_app()


@pytest_asyncio.fixture()
async def client(test_app: FastAPI):  # type: ignore[no-untyped-def]
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


def _auth_headers(key: str = _LIVE_KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _valid_send_body() -> dict:
    return {"email": "user@example.com", "purpose": "login"}


def _valid_verify_body(code: str = "123456") -> dict:
    return {"email": "user@example.com", "code": code}


# ---------------------------------------------------------------------------
# Helper: set up all mocks needed for a successful /send request
# ---------------------------------------------------------------------------

def _mock_send_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch all dependencies so POST /send returns 200 instantly."""
    project = _make_project()  # no sender_email_id → skips email enqueue
    key_row = _make_api_key()

    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.otp._get_sync_redis", lambda: object())
    monkeypatch.setattr("apps.api.routes.otp.check_key_hourly", lambda *_: True)
    monkeypatch.setattr("apps.api.routes.otp.check_email_hourly", lambda *_: True)
    monkeypatch.setattr("apps.api.routes.otp.get_project", lambda _: project)
    monkeypatch.setattr("apps.api.routes.otp.save_otp", lambda *a, **kw: "otp-001")


# ===========================================================================
# 1. POST /send — 200 happy path
# ===========================================================================

@pytest.mark.asyncio
async def test_send_otp_200_ok(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful OTP send returns 200 with sent:True and masked_email."""
    _mock_send_ok(monkeypatch)

    r = await client.post(
        "/api/v1/otp/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is True
    assert body["masked_email"] == "u***@example.com"


@pytest.mark.asyncio
async def test_send_otp_200_masked_email_shape(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """masked_email must keep only the first local-part character."""
    _mock_send_ok(monkeypatch)
    # Override email to something longer
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    r = await client.post(
        "/api/v1/otp/send",
        json={"email": "alice@mail.example.com", "purpose": "signup"},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["masked_email"] == "a***@mail.example.com"


# ===========================================================================
# 2. POST /verify — 200 verified + JWT
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_otp_200_verified(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Correct OTP returns 200 with verified:True and a JWT token."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr(
        "apps.api.routes.otp.verify_and_consume",
        lambda *_: {"verified": True, "token": "jwt.token.here", "otp_id": "otp-001"},
    )

    r = await client.post(
        "/api/v1/otp/verify",
        json=_valid_verify_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verified"] is True
    assert "token" in body and body["token"]
    assert "otp_id" in body and body["otp_id"]


# ===========================================================================
# 3. 401 — missing / invalid Authorization header
# ===========================================================================

@pytest.mark.asyncio
async def test_send_otp_401_no_auth_header(client: AsyncClient) -> None:
    """Missing Authorization header must return 401."""
    r = await client.post("/api/v1/otp/send", json=_valid_send_body())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_verify_otp_401_no_auth_header(client: AsyncClient) -> None:
    """Missing Authorization header on /verify must return 401."""
    r = await client.post("/api/v1/otp/verify", json=_valid_verify_body())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_send_otp_401_invalid_api_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown API key must return 401 invalid_api_key."""
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: None)

    r = await client.post(
        "/api/v1/otp/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "invalid_api_key"


# ===========================================================================
# 4. 403 — sandbox key in production
# ===========================================================================

@pytest.mark.asyncio
async def test_send_otp_403_sandbox_key_in_production(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mg_test_ key in production must return 403 sandbox_key_in_production."""
    monkeypatch.setattr("core.api_keys.settings.ENV", "production")

    r = await client.post(
        "/api/v1/otp/send",
        json=_valid_send_body(),
        headers=_auth_headers(key=_TEST_KEY),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "sandbox_key_in_production"


# ===========================================================================
# 5. 410 — otp_expired
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_otp_410_otp_expired(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expired or already-used OTP must return 410 otp_expired."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr(
        "apps.api.routes.otp.verify_and_consume",
        lambda *_: {"verified": False, "error": "otp_expired"},
    )

    r = await client.post(
        "/api/v1/otp/verify",
        json=_valid_verify_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 410
    assert r.json()["detail"]["error"] == "otp_expired"


# ===========================================================================
# 6. 422 — validation_error for malformed email
# ===========================================================================

@pytest.mark.asyncio
async def test_send_otp_422_invalid_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed email address must return 422 validation_error."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    r = await client.post(
        "/api/v1/otp/send",
        json={"email": "not-an-email", "purpose": "login"},
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_error"


@pytest.mark.asyncio
async def test_send_otp_422_empty_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty email string must return 422 validation_error."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    r = await client.post(
        "/api/v1/otp/send",
        json={"email": "", "purpose": "login"},
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_error"


# ===========================================================================
# 7. 400 — invalid_code with attempts_remaining
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_otp_400_invalid_code(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wrong OTP code must return 400 invalid_code with attempts_remaining."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr(
        "apps.api.routes.otp.verify_and_consume",
        lambda *_: {"verified": False, "error": "invalid_code", "attempts_remaining": 4},
    )

    r = await client.post(
        "/api/v1/otp/verify",
        json=_valid_verify_body(code="000000"),
        headers=_auth_headers(),
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["error"] == "invalid_code"
    assert "attempts_remaining" in body["detail"]
    assert body["detail"]["attempts_remaining"] == 4


# ===========================================================================
# 8. 423 — account_locked
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_otp_423_account_locked(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All attempts exhausted must return 423 account_locked."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr(
        "apps.api.routes.otp.verify_and_consume",
        lambda *_: {"verified": False, "error": "account_locked"},
    )

    r = await client.post(
        "/api/v1/otp/verify",
        json=_valid_verify_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 423
    assert r.json()["detail"]["error"] == "account_locked"


# ===========================================================================
# 9. 429 — rate_limit_exceeded with retry_after
# ===========================================================================

@pytest.mark.asyncio
async def test_send_otp_429_key_rate_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-key hourly rate limit exceeded must return 429 rate_limit_exceeded."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.otp._get_sync_redis", lambda: object())
    monkeypatch.setattr("apps.api.routes.otp.check_key_hourly", lambda *_: False)

    r = await client.post(
        "/api/v1/otp/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 429
    body = r.json()
    assert body["detail"]["error"] == "rate_limit_exceeded"
    assert "retry_after" in body["detail"]


@pytest.mark.asyncio
async def test_send_otp_429_email_rate_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-email hourly rate limit exceeded must return 429 rate_limit_exceeded."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.otp._get_sync_redis", lambda: object())
    monkeypatch.setattr("apps.api.routes.otp.check_key_hourly", lambda *_: True)
    monkeypatch.setattr("apps.api.routes.otp.check_email_hourly", lambda *_: False)

    r = await client.post(
        "/api/v1/otp/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 429
    body = r.json()
    assert body["detail"]["error"] == "rate_limit_exceeded"
    assert "retry_after" in body["detail"]


# ===========================================================================
# 10. 503 — Supabase unreachable
# ===========================================================================

@pytest.mark.asyncio
async def test_send_otp_503_db_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB connection failure on /send must return 503 service_unavailable."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.otp._get_sync_redis", lambda: object())
    monkeypatch.setattr("apps.api.routes.otp.check_key_hourly", lambda *_: True)
    monkeypatch.setattr("apps.api.routes.otp.check_email_hourly", lambda *_: True)

    def _db_down(*_):  # type: ignore[no-untyped-def]
        raise ConnectionError("Supabase unreachable")

    monkeypatch.setattr("apps.api.routes.otp.get_project", _db_down)

    r = await client.post(
        "/api/v1/otp/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "service_unavailable"


@pytest.mark.asyncio
async def test_verify_otp_503_db_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB connection failure on /verify must return 503 service_unavailable."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    def _db_down(*_):  # type: ignore[no-untyped-def]
        raise ConnectionError("Supabase unreachable")

    monkeypatch.setattr("apps.api.routes.otp.verify_and_consume", _db_down)

    r = await client.post(
        "/api/v1/otp/verify",
        json=_valid_verify_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "service_unavailable"


# ===========================================================================
# 11. Anti-enumeration timing floor
# ===========================================================================

@pytest.mark.asyncio
async def test_anti_enumeration_timing_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every POST /send response must take >= 190 ms regardless of path taken.

    The route enforces a 200 ms anti-enumeration floor; 190 ms is the assertion
    threshold to provide a 10 ms tolerance for scheduler jitter on the CI runner.

    Calls the endpoint 10 times with a nonexistent email address and asserts
    that every measured response time satisfies the floor.
    """
    project = _make_project()  # no sender → no email enqueue
    key_row = _make_api_key()

    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.otp._get_sync_redis", lambda: object())
    monkeypatch.setattr("apps.api.routes.otp.check_key_hourly", lambda *_: True)
    monkeypatch.setattr("apps.api.routes.otp.check_email_hourly", lambda *_: True)
    monkeypatch.setattr("apps.api.routes.otp.get_project", lambda _: project)
    monkeypatch.setattr("apps.api.routes.otp.save_otp", lambda *a, **kw: "otp-001")

    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        for i in range(10):
            start = time.monotonic()
            r = await ac.post(
                "/api/v1/otp/send",
                json={"email": f"nobody{i}@example.com", "purpose": "login"},
                headers=_auth_headers(),
            )
            elapsed = time.monotonic() - start
            assert r.status_code == 200
            assert elapsed >= 0.190, (
                f"Iteration {i}: response faster than 190 ms floor "
                f"({elapsed * 1000:.1f} ms)"
            )


@pytest.mark.asyncio
async def test_anti_enumeration_timing_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 200 ms timing floor must apply even when rate limiting fires early."""
    key_row = _make_api_key()

    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.otp._get_sync_redis", lambda: object())
    monkeypatch.setattr("apps.api.routes.otp.check_key_hourly", lambda *_: False)

    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        start = time.monotonic()
        r = await ac.post(
            "/api/v1/otp/send",
            json=_valid_send_body(),
            headers=_auth_headers(),
        )
        elapsed = time.monotonic() - start

    assert r.status_code == 429
    assert elapsed >= 0.190, (
        f"Rate-limit response faster than 190 ms floor ({elapsed * 1000:.1f} ms)"
    )


@pytest.mark.asyncio
async def test_anti_enumeration_timing_on_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 200 ms timing floor must apply even for 422 validation errors."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        start = time.monotonic()
        r = await ac.post(
            "/api/v1/otp/send",
            json={"email": "bad-email", "purpose": "login"},
            headers=_auth_headers(),
        )
        elapsed = time.monotonic() - start

    assert r.status_code == 422
    assert elapsed >= 0.190, (
        f"Validation-error response faster than 190 ms floor ({elapsed * 1000:.1f} ms)"
    )
