"""
tests/test_magic_routes.py — Part 08 magic link route tests.

Covers all required test cases:
  1. POST /magic/send returns 200 with status 'sent'
  2. GET /magic/verify/{token} with valid token returns HTML 200
     and sets is_used=True in database (via verify_magic_link call)
  3. GET /magic/verify/{token} with already-used token returns 410
  4. GET /magic/verify/{token} with expired token returns 410
  5. GET /magic/verify/{token} with tampered token returns 410
  6. redirect_url present → meta refresh tag present in HTML
  7. redirect_url absent → no meta refresh tag in HTML
  8. JWT is present in the verify response HTML
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock

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

from apps.api.routes import magic as magic_module  # noqa: E402
from core.jwt_utils import issue_jwt, verify_jwt  # noqa: E402
from core.models import ApiKey, EmailLog, Project  # noqa: E402

UTC = timezone.utc
NOW = datetime.now(UTC)

_LIVE_KEY = "mg_live_" + "a" * 64
_PROJECT_ID = "proj-0001"
_KEY_ID = "key-0001"

_SAMPLE_TOKEN = "a" * 43  # 43 URL-safe base64 chars ≈ 32 raw bytes
_SAMPLE_JWT = issue_jwt(subject="hash_abc", extra_claims={"link_id": "link-001", "purpose": "login"})


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
    return Project(
        id=_PROJECT_ID,
        name="Test Project",
        slug="test-project",
        sender_email_id=sender_email_id,
        otp_length=6,
        otp_expiry_seconds=300,
        otp_max_attempts=5,
        rate_limit_per_hour=100,
        template_subject="Your link",
        template_body_text="Link: {{ magic_link_url }}",
        template_body_html="<a href='{{ magic_link_url }}'>Sign in</a>",
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
        type="magic_link",
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
    """Minimal FastAPI app containing only the magic router."""
    app = FastAPI()
    app.include_router(magic_module.router)
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


def _valid_send_body(redirect_url: str | None = None) -> dict:
    body: dict = {"email": "user@example.com", "purpose": "login"}
    if redirect_url is not None:
        body["redirect_url"] = redirect_url
    return body


def _mock_send_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch all dependencies so POST /send returns 200 instantly."""
    project = _make_project()  # no sender_email_id → skips email enqueue
    key_row = _make_api_key()

    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.magic.get_project", lambda _: project)
    monkeypatch.setattr(
        "apps.api.routes.magic.create_magic_link",
        lambda *a, **kw: _SAMPLE_TOKEN,
    )


# ===========================================================================
# 1. POST /magic/send — 200 happy path
# ===========================================================================

@pytest.mark.asyncio
async def test_send_magic_link_200_ok(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful magic link send returns 200 with status 'sent'."""
    _mock_send_ok(monkeypatch)

    r = await client.post(
        "/api/v1/magic/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sent"


# ===========================================================================
# 2. GET /magic/verify/{token} — valid token → HTML 200
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_magic_link_200_valid_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid token returns 200 HTML with magic_verified content."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda t: {
            "verified": True,
            "link_id": "link-001",
            "token": _SAMPLE_JWT,
            "redirect_url": None,
        },
    )

    r = await client.get(f"/api/v1/magic/verify/{_SAMPLE_TOKEN}")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    content = r.text
    # Verified page content
    assert "signed in" in content.lower() or "verified" in content.lower()
    # JWT embedded in meta tag
    assert _SAMPLE_JWT in content


# ===========================================================================
# 2b. Verify sets is_used=True in database (verify_magic_link called)
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_magic_link_calls_verify_function(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Route calls verify_magic_link which marks the token as used."""
    called_with: list = []

    def _mock_verify(token: str):  # type: ignore[no-untyped-def]
        called_with.append(token)
        return {
            "verified": True,
            "link_id": "link-001",
            "token": _SAMPLE_JWT,
            "redirect_url": None,
        }

    monkeypatch.setattr("apps.api.routes.magic.verify_magic_link", _mock_verify)

    await client.get(f"/api/v1/magic/verify/{_SAMPLE_TOKEN}")

    # verify_magic_link was called with the token from the URL
    assert len(called_with) == 1
    assert called_with[0] == _SAMPLE_TOKEN


# ===========================================================================
# 3. GET /magic/verify/{token} — already-used token → 410
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_magic_link_410_already_used(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Already-used token returns 410 with magic_expired HTML."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda t: {"verified": False, "error": "already_used"},
    )

    r = await client.get(f"/api/v1/magic/verify/{_SAMPLE_TOKEN}")

    assert r.status_code == 410
    assert "text/html" in r.headers["content-type"]
    content = r.text
    assert "expired" in content.lower() or "already used" in content.lower()


# ===========================================================================
# 4. GET /magic/verify/{token} — expired token → 410
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_magic_link_410_expired(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expired token returns 410 with magic_expired HTML."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda t: {"verified": False, "error": "expired"},
    )

    r = await client.get(f"/api/v1/magic/verify/{_SAMPLE_TOKEN}")

    assert r.status_code == 410
    assert "text/html" in r.headers["content-type"]
    content = r.text
    assert "expired" in content.lower() or "no longer valid" in content.lower()


# ===========================================================================
# 5. GET /magic/verify/{token} — tampered token → 410
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_magic_link_410_tampered(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tampered/unknown token returns 410 with magic_expired HTML."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda t: {"verified": False, "error": "invalid_token"},
    )

    r = await client.get("/api/v1/magic/verify/totally-invalid-tampered-token")

    assert r.status_code == 410
    assert "text/html" in r.headers["content-type"]


# ===========================================================================
# 6. redirect_url present → meta refresh tag in HTML
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_magic_link_redirect_url_present(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When redirect_url is set, magic_verified.html includes meta refresh."""
    redirect_target = "https://app.example.com/dashboard"
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda t: {
            "verified": True,
            "link_id": "link-001",
            "token": _SAMPLE_JWT,
            "redirect_url": redirect_target,
        },
    )

    r = await client.get(f"/api/v1/magic/verify/{_SAMPLE_TOKEN}")

    assert r.status_code == 200
    content = r.text
    # Meta refresh tag must be present with the redirect_url
    assert "http-equiv" in content
    assert "refresh" in content
    assert redirect_target in content


# ===========================================================================
# 7. redirect_url absent → no meta refresh tag in HTML
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_magic_link_redirect_url_absent(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When redirect_url is None, magic_verified.html has no meta refresh."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda t: {
            "verified": True,
            "link_id": "link-001",
            "token": _SAMPLE_JWT,
            "redirect_url": None,
        },
    )

    r = await client.get(f"/api/v1/magic/verify/{_SAMPLE_TOKEN}")

    assert r.status_code == 200
    content = r.text
    # No meta refresh when redirect_url is absent
    assert 'http-equiv="refresh"' not in content
    assert "http-equiv='refresh'" not in content


# ===========================================================================
# 8. JWT is present and valid in the verify response
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_magic_link_jwt_present_and_valid(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """JWT is embedded in the HTML and is a valid HS256 token."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda t: {
            "verified": True,
            "link_id": "link-001",
            "token": _SAMPLE_JWT,
            "redirect_url": None,
        },
    )

    r = await client.get(f"/api/v1/magic/verify/{_SAMPLE_TOKEN}")

    assert r.status_code == 200
    content = r.text
    # JWT is embedded in the page
    assert _SAMPLE_JWT in content
    # JWT can be decoded and verified
    payload = verify_jwt(_SAMPLE_JWT)
    assert payload["sub"] == "hash_abc"
    assert payload["purpose"] == "login"
    assert "link_id" in payload


# ===========================================================================
# 9. POST /magic/send — 401 when no auth header
# ===========================================================================

@pytest.mark.asyncio
async def test_send_magic_link_401_no_auth(client: AsyncClient) -> None:
    """Missing Authorization header must return 401."""
    r = await client.post("/api/v1/magic/send", json=_valid_send_body())
    assert r.status_code == 401


# ===========================================================================
# 10. POST /magic/send — 422 for invalid email
# ===========================================================================

@pytest.mark.asyncio
async def test_send_magic_link_422_invalid_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed email returns 422 validation_error."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    r = await client.post(
        "/api/v1/magic/send",
        json={"email": "not-an-email"},
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_error"


# ===========================================================================
# Part 15 additions — coverage for core/magic_links.py and route error paths
# ===========================================================================

# ---------------------------------------------------------------------------
# core/magic_links.py — create_magic_link and verify_magic_link
# ---------------------------------------------------------------------------

def test_create_magic_link_returns_raw_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_magic_link returns a URL-safe token and calls insert_magic_link."""
    from core.magic_links import create_magic_link

    inserted: list = []

    def _mock_insert(data: dict) -> None:
        inserted.append(data)

    monkeypatch.setattr("core.magic_links.insert_magic_link", _mock_insert)

    token = create_magic_link(
        project_id="proj-1",
        email="user@example.com",
        purpose="login",
    )

    assert isinstance(token, str)
    assert len(token) > 0
    assert len(inserted) == 1
    row = inserted[0]
    assert row["project_id"] == "proj-1"
    assert row["purpose"] == "login"
    assert row["is_used"] is False
    # Raw token must NOT be stored
    assert token not in str(row)


def test_create_magic_link_with_redirect_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """redirect_url is forwarded to insert_magic_link payload."""
    from core.magic_links import create_magic_link

    inserted: list = []
    monkeypatch.setattr("core.magic_links.insert_magic_link", lambda d: inserted.append(d))

    create_magic_link(
        project_id="proj-2",
        email="test@example.com",
        redirect_url="https://app.example.com/dashboard",
    )

    assert inserted[0]["redirect_url"] == "https://app.example.com/dashboard"


def test_create_magic_link_token_hash_sha256(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the SHA-256 hex digest of the token is stored, not the raw token."""
    import hashlib
    from core.magic_links import create_magic_link

    inserted: list = []
    monkeypatch.setattr("core.magic_links.insert_magic_link", lambda d: inserted.append(d))

    raw_token = None

    real_token_urlsafe = __import__("secrets").token_urlsafe

    def _capture_token(n: int) -> str:
        nonlocal raw_token
        raw_token = real_token_urlsafe(n)
        return raw_token

    monkeypatch.setattr("core.magic_links.secrets.token_urlsafe", _capture_token)

    create_magic_link("proj-3", "x@y.com")

    expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    assert inserted[0]["token_hash"] == expected_hash


def test_verify_magic_link_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_magic_link returns invalid_token when hash not found in DB."""
    from core.magic_links import verify_magic_link

    monkeypatch.setattr("core.magic_links.get_magic_link_by_token_hash", lambda _: None)

    result = verify_magic_link("nonexistenttoken")
    assert result["verified"] is False
    assert result["error"] == "invalid_token"


def test_verify_magic_link_already_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_magic_link returns already_used when is_used is True."""
    from datetime import datetime, timedelta, timezone
    from core.magic_links import verify_magic_link
    from core.models import MagicLink

    UTC = timezone.utc
    NOW = datetime.now(UTC)
    used_row = MagicLink(
        id="ml-001",
        project_id="proj-1",
        email_hash="ehash",
        token_hash="thash",
        purpose="login",
        redirect_url=None,
        is_used=True,
        expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
    )
    monkeypatch.setattr("core.magic_links.get_magic_link_by_token_hash", lambda _: used_row)

    result = verify_magic_link("sometoken")
    assert result["verified"] is False
    assert result["error"] == "already_used"


def test_verify_magic_link_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_magic_link returns expired when token is past its expiry."""
    from datetime import datetime, timedelta, timezone
    from core.magic_links import verify_magic_link
    from core.models import MagicLink

    UTC = timezone.utc
    NOW = datetime.now(UTC)
    expired_row = MagicLink(
        id="ml-002",
        project_id="proj-1",
        email_hash="ehash",
        token_hash="thash",
        purpose="login",
        redirect_url=None,
        is_used=False,
        expires_at=NOW - timedelta(minutes=5),
        created_at=NOW - timedelta(minutes=20),
    )
    monkeypatch.setattr(
        "core.magic_links.get_magic_link_by_token_hash", lambda _: expired_row
    )

    result = verify_magic_link("expiredtoken")
    assert result["verified"] is False
    assert result["error"] == "expired"


def test_verify_magic_link_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_magic_link returns verified=True with JWT on a valid link."""
    from datetime import datetime, timedelta, timezone
    from core.magic_links import verify_magic_link
    from core.models import MagicLink

    UTC = timezone.utc
    NOW = datetime.now(UTC)
    valid_row = MagicLink(
        id="ml-003",
        project_id="proj-1",
        email_hash="ehash",
        token_hash="thash",
        purpose="login",
        redirect_url="https://example.com",
        is_used=False,
        expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
    )
    monkeypatch.setattr(
        "core.magic_links.get_magic_link_by_token_hash", lambda _: valid_row
    )
    monkeypatch.setattr("core.magic_links.update_magic_link", lambda *a, **kw: None)

    result = verify_magic_link("validtoken")
    assert result["verified"] is True
    assert "token" in result
    assert result["link_id"] == "ml-003"
    assert result["redirect_url"] == "https://example.com"


def test_verify_magic_link_naive_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_magic_link handles naive (tz-unaware) expires_at datetimes."""
    from datetime import datetime, timedelta, timezone
    from core.magic_links import verify_magic_link
    from core.models import MagicLink

    UTC = timezone.utc
    NOW = datetime.now(UTC)
    # expires_at without tzinfo — should be treated as UTC and still be valid
    naive_expiry = datetime.utcnow() + timedelta(minutes=10)
    valid_row = MagicLink(
        id="ml-004",
        project_id="proj-1",
        email_hash="ehash",
        token_hash="thash",
        purpose="login",
        redirect_url=None,
        is_used=False,
        expires_at=naive_expiry,
        created_at=NOW,
    )
    monkeypatch.setattr(
        "core.magic_links.get_magic_link_by_token_hash", lambda _: valid_row
    )
    monkeypatch.setattr("core.magic_links.update_magic_link", lambda *a, **kw: None)

    result = verify_magic_link("naivetoken")
    assert result["verified"] is True


# ---------------------------------------------------------------------------
# Route error paths — 503 when project fetch fails or create_magic_link fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_magic_link_503_project_fetch_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """503 when get_project raises an exception."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr(
        "apps.api.routes.magic.get_project", lambda _: (_ for _ in ()).throw(RuntimeError("db down"))
    )

    r = await client.post(
        "/api/v1/magic/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "service_unavailable"


@pytest.mark.asyncio
async def test_send_magic_link_503_project_is_none(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """503 when get_project returns None (project not found)."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.magic.get_project", lambda _: None)

    r = await client.post(
        "/api/v1/magic/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_send_magic_link_503_create_link_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """503 when create_magic_link raises an exception."""
    key_row = _make_api_key()
    project = _make_project()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.magic.get_project", lambda _: project)
    monkeypatch.setattr(
        "apps.api.routes.magic.create_magic_link",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db error")),
    )

    r = await client.post(
        "/api/v1/magic/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_send_magic_link_200_with_sender_email_id(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """200 success path when project has a sender_email_id (email enqueue path)."""
    key_row = _make_api_key()
    project = _make_project(sender_email_id="sender-001")
    email_log = _make_email_log()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.magic.get_project", lambda _: project)
    monkeypatch.setattr(
        "apps.api.routes.magic.create_magic_link",
        lambda *a, **kw: "raw_token_abc",
    )
    monkeypatch.setattr(
        "apps.api.routes.magic.insert_email_log", lambda _: email_log
    )
    monkeypatch.setattr(
        "apps.api.routes.magic._enqueue_email",
        AsyncMock(return_value=None),
    )

    r = await client.post(
        "/api/v1/magic/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "sent"


@pytest.mark.asyncio
async def test_verify_magic_link_410_on_exception(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """410 is returned when verify_magic_link raises an unexpected exception."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda _: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    r = await client.get(f"/api/v1/magic/verify/{_SAMPLE_TOKEN}")
    assert r.status_code == 410
