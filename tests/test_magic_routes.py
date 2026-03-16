"""
tests/test_magic_routes.py — Part 08 magic-link route tests.

Covers all required test scenarios:
  1. POST /magic/send returns 200 with status 'sent'
  2. GET /magic/verify/{token} with valid token returns HTML 200,
     sets is_used=True in the database
  3. GET /magic/verify/{token} with already-used token returns 410
  4. GET /magic/verify/{token} with expired token returns 410
  5. GET /magic/verify/{token} with tampered token returns 410
  6. redirect_url present in magic_verified.html meta refresh tag
  7. redirect_url absent — no meta refresh tag in HTML
  8. JWT is present and valid in the verify response HTML
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

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
from core.models import ApiKey, EmailLog, MagicLink, Project  # noqa: E402

UTC = timezone.utc
NOW = datetime.now(UTC)

_LIVE_KEY = "mg_live_" + "a" * 64
_PROJECT_ID = "proj-0001"
_KEY_ID = "key-0001"
_LINK_ID = "link-0001"


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


def _make_magic_link(
    is_used: bool = False,
    expires_at: datetime | None = None,
    redirect_url: str = "",
) -> MagicLink:
    if expires_at is None:
        expires_at = NOW + timedelta(minutes=15)
    return MagicLink(
        id=_LINK_ID,
        project_id=_PROJECT_ID,
        email_hash="email_hash_abc",
        token_hash="token_hash_abc",
        purpose="login",
        redirect_url=redirect_url,
        is_used=is_used,
        expires_at=expires_at,
        created_at=NOW,
        used_at=None,
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
    pass


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


def _valid_send_body(redirect_url: str = "") -> dict:
    body: dict = {"email": "user@example.com", "purpose": "login"}
    if redirect_url:
        body["redirect_url"] = redirect_url
    return body


# ---------------------------------------------------------------------------
# Helper: set up all mocks needed for a successful /send request
# ---------------------------------------------------------------------------

def _mock_send_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch all dependencies so POST /send returns 200 instantly."""
    project = _make_project()  # no sender_email_id → skips email enqueue
    key_row = _make_api_key()

    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.magic.get_project", lambda _: project)
    monkeypatch.setattr(
        "apps.api.routes.magic.create_magic_link",
        lambda *a, **kw: ("raw_token_abc", _LINK_ID),
    )


# ===========================================================================
# 1. POST /send — 200 happy path
# ===========================================================================

@pytest.mark.asyncio
async def test_send_magic_link_200_ok(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful magic link send returns 200 with status='sent'."""
    _mock_send_ok(monkeypatch)

    r = await client.post(
        "/api/v1/magic/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json() == {"status": "sent"}


@pytest.mark.asyncio
async def test_send_magic_link_401_no_auth(client: AsyncClient) -> None:
    """Missing Authorization header must return 401."""
    r = await client.post("/api/v1/magic/send", json=_valid_send_body())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_send_magic_link_422_bad_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed email must return 422 validation_error."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    r = await client.post(
        "/api/v1/magic/send",
        json={"email": "not-an-email", "purpose": "login"},
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_error"


@pytest.mark.asyncio
async def test_send_magic_link_503_project_not_found(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing project should return 503."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.magic.get_project", lambda _: None)

    r = await client.post(
        "/api/v1/magic/send",
        json=_valid_send_body(),
        headers=_auth_headers(),
    )
    assert r.status_code == 503


# ===========================================================================
# 2. GET /verify/{token} — valid token → HTML 200, is_used set to True
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_valid_token_returns_html_200(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid token returns HTTP 200 with HTML content."""
    _captured: list[dict] = []

    def _fake_verify(raw_token: str) -> dict:
        return {
            "verified": True,
            "magic_link_id": _LINK_ID,
            "email_hash": "email_hash_abc",
            "redirect_url": "",
            "token": "jwt.token.here",
        }

    monkeypatch.setattr("apps.api.routes.magic.verify_magic_link", _fake_verify)

    r = await client.get("/api/v1/magic/verify/some_valid_token")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "signed in" in r.text.lower()


@pytest.mark.asyncio
async def test_verify_valid_token_sets_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful verify_magic_link call updates is_used=True in DB."""
    from core import magic_links as ml_module

    updated_data: list[dict] = []

    link = _make_magic_link(is_used=False)

    monkeypatch.setattr(
        "core.magic_links.get_magic_link_by_token_hash",
        lambda _: link,
    )
    monkeypatch.setattr(
        "core.magic_links.update_magic_link",
        lambda link_id, data: updated_data.append(data) or link,
    )
    monkeypatch.setattr(
        "core.jwt_utils.issue_jwt",
        lambda subject, extra_claims=None: "mock.jwt.token",
    )

    result = ml_module.verify_magic_link("raw_token_value")

    assert result["verified"] is True
    assert len(updated_data) == 1
    assert updated_data[0]["is_used"] is True
    assert "used_at" in updated_data[0]


# ===========================================================================
# 3. Already-used token → 410
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_already_used_token_returns_410(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Already-used magic link returns HTTP 410."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda _: {"verified": False, "error": "already_used"},
    )

    r = await client.get("/api/v1/magic/verify/used_token")
    assert r.status_code == 410
    assert "text/html" in r.headers["content-type"]


# ===========================================================================
# 4. Expired token → 410
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_expired_token_returns_410(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expired magic link returns HTTP 410."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda _: {"verified": False, "error": "expired"},
    )

    r = await client.get("/api/v1/magic/verify/expired_token")
    assert r.status_code == 410
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_verify_expired_core_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Core verify_magic_link returns error='expired' for past-expiry links."""
    from core import magic_links as ml_module

    expired_link = _make_magic_link(
        is_used=False,
        expires_at=NOW - timedelta(minutes=1),  # in the past
    )

    monkeypatch.setattr(
        "core.magic_links.get_magic_link_by_token_hash",
        lambda _: expired_link,
    )

    result = ml_module.verify_magic_link("raw_token_value")

    assert result["verified"] is False
    assert result["error"] == "expired"


# ===========================================================================
# 5. Tampered / unknown token → 410
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_tampered_token_returns_410(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tampered / unknown token returns HTTP 410."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda _: {"verified": False, "error": "not_found"},
    )

    r = await client.get("/api/v1/magic/verify/tampered_or_unknown_token")
    assert r.status_code == 410
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_verify_tampered_token_core_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Core verify_magic_link returns error='not_found' for unknown token hash."""
    from core import magic_links as ml_module

    monkeypatch.setattr(
        "core.magic_links.get_magic_link_by_token_hash",
        lambda _: None,
    )

    result = ml_module.verify_magic_link("totally_fake_token")

    assert result["verified"] is False
    assert result["error"] == "not_found"


# ===========================================================================
# 6. redirect_url present → meta refresh in HTML
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_redirect_url_present_meta_refresh(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When redirect_url is set, magic_verified.html contains a meta refresh tag."""
    redirect = "https://app.example.com/dashboard"
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda _: {
            "verified": True,
            "magic_link_id": _LINK_ID,
            "email_hash": "email_hash_abc",
            "redirect_url": redirect,
            "token": "jwt.token.here",
        },
    )

    r = await client.get("/api/v1/magic/verify/good_token")
    assert r.status_code == 200
    assert f'content="2; url={redirect}"' in r.text


# ===========================================================================
# 7. redirect_url absent → no meta refresh in HTML
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_no_redirect_url_no_meta_refresh(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When redirect_url is empty, magic_verified.html has no meta refresh tag."""
    monkeypatch.setattr(
        "apps.api.routes.magic.verify_magic_link",
        lambda _: {
            "verified": True,
            "magic_link_id": _LINK_ID,
            "email_hash": "email_hash_abc",
            "redirect_url": "",
            "token": "jwt.token.here",
        },
    )

    r = await client.get("/api/v1/magic/verify/good_token_no_redirect")
    assert r.status_code == 200
    assert "http-equiv" not in r.text.lower()


# ===========================================================================
# 8. JWT is present and valid in the verify response HTML context
# ===========================================================================

@pytest.mark.asyncio
async def test_verify_jwt_is_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """verify_magic_link issues a real JWT via issue_jwt."""
    from core import magic_links as ml_module
    from core.jwt_utils import verify_jwt

    link = _make_magic_link(is_used=False)

    monkeypatch.setattr(
        "core.magic_links.get_magic_link_by_token_hash",
        lambda _: link,
    )
    monkeypatch.setattr(
        "core.magic_links.update_magic_link",
        lambda link_id, data: link,
    )

    result = ml_module.verify_magic_link("real_token_for_jwt_test")

    assert result["verified"] is True
    jwt_token = result["token"]
    assert jwt_token

    # Decode and verify the JWT (no Redis needed for this check)
    payload = verify_jwt(jwt_token)
    assert payload["sub"] == link.email_hash
    assert payload["magic_link_id"] == _LINK_ID
    assert payload["purpose"] == "login"


# ===========================================================================
# 9. Core create_magic_link: raw token never stored, hash is stored
# ===========================================================================

def test_create_magic_link_stores_hash_not_raw_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The raw token must NOT appear in the inserted DB record; only its hash."""
    import hashlib
    from core import magic_links as ml_module

    stored_data: list[dict] = []
    link = _make_magic_link()

    monkeypatch.setattr(
        "core.magic_links.insert_magic_link",
        lambda data: stored_data.append(data) or link,
    )
    monkeypatch.setattr(
        "core.crypto.hmac_email",
        lambda e: "hmac_of_email",
    )

    raw_token, link_id = ml_module.create_magic_link(
        project_id=_PROJECT_ID,
        email="user@example.com",
    )

    assert len(stored_data) == 1
    row = stored_data[0]

    # Raw token must NOT be stored anywhere in the DB record
    assert raw_token not in str(row.values())

    # Only the SHA-256 hash should be stored
    expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    assert row["token_hash"] == expected_hash
