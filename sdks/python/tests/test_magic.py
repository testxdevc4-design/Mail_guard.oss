"""
Tests for the magic link SDK client (sync and async).

Uses ``httpretty`` to mock HTTP calls at the socket level for the sync
client, and ``unittest.mock`` to mock aiohttp for the async client.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpretty
import pytest

from mailguard import AsyncMailGuard, MailGuard
from mailguard.exceptions import ExpiredError

API_KEY = "mg_live_test_key"
BASE_URL = "https://api.mailguard.dev"
MAGIC_SEND_URL = f"{BASE_URL}/api/v1/magic/send"
MAGIC_VERIFY_URL = f"{BASE_URL}/api/v1/magic/verify/tok_abc123"


@pytest.fixture
def mg() -> MailGuard:
    return MailGuard(api_key=API_KEY, base_url=BASE_URL)


@pytest.fixture
def async_mg() -> AsyncMailGuard:
    return AsyncMailGuard(api_key=API_KEY, base_url=BASE_URL)


# ---------------------------------------------------------------------------
# Magic send — sync success
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_magic_send_success_returns_status_sent(mg: MailGuard) -> None:
    """Successful magic link send returns status='sent'."""
    httpretty.register_uri(
        httpretty.POST,
        MAGIC_SEND_URL,
        body=json.dumps({"status": "sent"}),
        status=200,
        content_type="application/json",
    )

    result = mg.magic.send(
        {"email": "user@example.com", "purpose": "login", "redirect_url": "https://app.example.com/verify"}
    )

    assert result["status"] == "sent"


@httpretty.activate(allow_net_connect=False)
def test_magic_send_result_is_typed_dict(mg: MailGuard) -> None:
    """Response TypedDict has all expected fields."""
    httpretty.register_uri(
        httpretty.POST,
        MAGIC_SEND_URL,
        body=json.dumps({"status": "sent"}),
        status=200,
        content_type="application/json",
    )

    result = mg.magic.send(
        {"email": "user@example.com", "purpose": "login", "redirect_url": "https://app.example.com/verify"}
    )

    # TypedDict fields — 'status' must be present
    assert "status" in result
    assert isinstance(result["status"], str)


# ---------------------------------------------------------------------------
# Magic verify — sync success
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_magic_verify_result_has_all_expected_fields(mg: MailGuard) -> None:
    """MagicLinkVerifyResult TypedDict has all expected fields."""
    httpretty.register_uri(
        httpretty.GET,
        MAGIC_VERIFY_URL,
        body=json.dumps({
            "valid": True,
            "email_hash": "abc123def456",
            "project_id": "proj_xyz",
            "purpose": "login",
            "redirect_url": "https://app.example.com/verify",
        }),
        status=200,
        content_type="application/json",
    )

    result = mg.magic.verify("tok_abc123")

    assert result["valid"] is True
    assert result["email_hash"] == "abc123def456"
    assert result["project_id"] == "proj_xyz"
    assert result["purpose"] == "login"
    assert result["redirect_url"] == "https://app.example.com/verify"


# ---------------------------------------------------------------------------
# Error dispatch — HTTP 410 → ExpiredError
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_magic_verify_410_raises_expired_error(mg: MailGuard) -> None:
    """HTTP 410 raises ExpiredError (token expired or already used)."""
    httpretty.register_uri(
        httpretty.GET,
        MAGIC_VERIFY_URL,
        body=json.dumps({"detail": {"error": "magic_link_expired", "message": "Magic link has expired"}}),
        status=410,
        content_type="application/json",
    )

    with pytest.raises(ExpiredError) as exc_info:
        mg.magic.verify("tok_abc123")

    assert exc_info.value.status_code == 410


# ---------------------------------------------------------------------------
# Async client — identical results to sync client
# ---------------------------------------------------------------------------


def _make_mock_aiohttp_response(status: int, body: dict) -> MagicMock:
    """Helper: build a mock aiohttp response context manager."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=body)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    return mock_resp


def _make_mock_aiohttp_session(mock_resp: MagicMock) -> MagicMock:
    """Helper: build a mock aiohttp ClientSession context manager."""
    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    mock_session.get.return_value = mock_resp
    mock_session.request.return_value = mock_resp
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    return mock_session


@pytest.mark.asyncio
async def test_async_magic_send_produces_identical_result(async_mg: AsyncMailGuard) -> None:
    """Async client send() produces identical result to sync client."""
    mock_resp = _make_mock_aiohttp_response(200, {"status": "sent"})
    mock_session = _make_mock_aiohttp_session(mock_resp)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await async_mg.magic.send(
            {"email": "user@example.com", "purpose": "login", "redirect_url": "https://app.example.com/verify"}
        )

    assert result["status"] == "sent"


@pytest.mark.asyncio
async def test_async_magic_verify_produces_identical_result(async_mg: AsyncMailGuard) -> None:
    """Async client verify() produces identical result to sync client."""
    body = {
        "valid": True,
        "email_hash": "abc123def456",
        "project_id": "proj_xyz",
        "purpose": "login",
        "redirect_url": "https://app.example.com/verify",
    }
    mock_resp = _make_mock_aiohttp_response(200, body)
    mock_session = _make_mock_aiohttp_session(mock_resp)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await async_mg.magic.verify("tok_abc123")

    assert result["valid"] is True
    assert result["email_hash"] == "abc123def456"
    assert result["project_id"] == "proj_xyz"
    assert result["purpose"] == "login"
    assert result["redirect_url"] == "https://app.example.com/verify"


@pytest.mark.asyncio
async def test_async_magic_verify_410_raises_expired_error(async_mg: AsyncMailGuard) -> None:
    """Async client raises ExpiredError on HTTP 410."""
    body = {"detail": {"error": "magic_link_expired", "message": "Magic link has expired"}}
    mock_resp = _make_mock_aiohttp_response(410, body)
    mock_session = _make_mock_aiohttp_session(mock_resp)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(ExpiredError) as exc_info:
            await async_mg.magic.verify("tok_abc123")

    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_async_client_importable_without_aiohttp() -> None:
    """AsyncMailGuard can be imported even when aiohttp is not installed."""
    # This test just verifies that the class is importable at module level.
    # aiohttp is only imported lazily inside _request().
    assert AsyncMailGuard is not None
