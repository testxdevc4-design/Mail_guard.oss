"""
Tests for the OTP SDK client.

Uses ``httpretty`` to mock HTTP calls at the socket level — works with
urllib.request without any additional dependencies.
"""

import json
import socket
import urllib.error
from unittest.mock import patch

import httpretty
import pytest

from mailguard import MailGuard
from mailguard.exceptions import (
    ExpiredError,
    InvalidCodeError,
    InvalidKeyError,
    LockedError,
    MailGuardError,
    RateLimitError,
)

API_KEY = "mg_live_test_key"
BASE_URL = "https://api.mailguard.dev"
OTP_SEND_URL = f"{BASE_URL}/api/v1/otp/send"
OTP_VERIFY_URL = f"{BASE_URL}/api/v1/otp/verify"


@pytest.fixture
def mg() -> MailGuard:
    return MailGuard(api_key=API_KEY, base_url=BASE_URL)


# ---------------------------------------------------------------------------
# OTP send — success
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_otp_send_success_returns_typed_dict(mg: MailGuard) -> None:
    """Successful send returns a TypedDict with correct snake_case fields."""
    httpretty.register_uri(
        httpretty.POST,
        OTP_SEND_URL,
        body=json.dumps({"status": "sent", "expires_in": 300, "masked_email": "u***@example.com"}),
        status=200,
        content_type="application/json",
    )
    result = mg.otp.send({"email": "user@example.com"})

    assert result["status"] == "sent"
    assert result["expires_in"] == 300
    assert result["masked_email"] == "u***@example.com"


@httpretty.activate(allow_net_connect=False)
def test_otp_send_sets_bearer_auth_header(mg: MailGuard) -> None:
    """Every OTP send request carries an Authorization: Bearer header."""
    httpretty.register_uri(
        httpretty.POST,
        OTP_SEND_URL,
        body=json.dumps({"status": "sent", "expires_in": 300, "masked_email": "u***@example.com"}),
        status=200,
        content_type="application/json",
    )
    mg.otp.send({"email": "user@example.com"})

    last_request = httpretty.last_request()
    assert last_request.headers.get("Authorization") == f"Bearer {API_KEY}"


@httpretty.activate(allow_net_connect=False)
def test_otp_send_sets_user_agent(mg: MailGuard) -> None:
    """Every request sets User-Agent: mailguard-sdk-python/1.0.0."""
    httpretty.register_uri(
        httpretty.POST,
        OTP_SEND_URL,
        body=json.dumps({"status": "sent", "expires_in": 300, "masked_email": "u***@example.com"}),
        status=200,
        content_type="application/json",
    )
    mg.otp.send({"email": "user@example.com"})

    last_request = httpretty.last_request()
    assert last_request.headers.get("User-Agent") == "mailguard-sdk-python/1.0.0"


# ---------------------------------------------------------------------------
# OTP verify — success
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_otp_verify_success_returns_verified_true(mg: MailGuard) -> None:
    """Successful verify returns verified=True with a token and expires_at."""
    httpretty.register_uri(
        httpretty.POST,
        OTP_VERIFY_URL,
        body=json.dumps({
            "verified": True,
            "token": "eyJhbGciOiJIUzI1NiJ9.test",
            "expires_at": "2026-01-01T00:10:00Z",
        }),
        status=200,
        content_type="application/json",
    )
    result = mg.otp.verify({"email": "user@example.com", "code": "123456"})

    assert result["verified"] is True
    assert result["token"] == "eyJhbGciOiJIUzI1NiJ9.test"
    assert result["expires_at"] == "2026-01-01T00:10:00Z"


# ---------------------------------------------------------------------------
# Error dispatch — HTTP 429 → RateLimitError
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_otp_send_429_raises_rate_limit_error(mg: MailGuard) -> None:
    """HTTP 429 raises RateLimitError with the correct retry_after value."""
    httpretty.register_uri(
        httpretty.POST,
        OTP_SEND_URL,
        body=json.dumps({"detail": {"error": "rate_limited", "message": "Too many requests", "retry_after": 42}}),
        status=429,
        content_type="application/json",
    )
    with pytest.raises(RateLimitError) as exc_info:
        mg.otp.send({"email": "user@example.com"})

    err = exc_info.value
    assert err.retry_after == 42
    assert err.status_code == 429
    assert "Too many requests" in str(err)


# ---------------------------------------------------------------------------
# Error dispatch — HTTP 400 → InvalidCodeError
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_otp_verify_400_raises_invalid_code_error(mg: MailGuard) -> None:
    """HTTP 400 raises InvalidCodeError with the correct attempts_remaining."""
    httpretty.register_uri(
        httpretty.POST,
        OTP_VERIFY_URL,
        body=json.dumps({"detail": {"error": "invalid_code", "message": "Invalid OTP", "attempts_remaining": 2}}),
        status=400,
        content_type="application/json",
    )
    with pytest.raises(InvalidCodeError) as exc_info:
        mg.otp.verify({"email": "user@example.com", "code": "000000"})

    err = exc_info.value
    assert err.attempts_remaining == 2
    assert err.status_code == 400


# ---------------------------------------------------------------------------
# Error dispatch — HTTP 410 → ExpiredError
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_otp_verify_410_raises_expired_error(mg: MailGuard) -> None:
    """HTTP 410 raises ExpiredError."""
    httpretty.register_uri(
        httpretty.POST,
        OTP_VERIFY_URL,
        body=json.dumps({"detail": {"error": "otp_expired", "message": "OTP has expired"}}),
        status=410,
        content_type="application/json",
    )
    with pytest.raises(ExpiredError) as exc_info:
        mg.otp.verify({"email": "user@example.com", "code": "123456"})

    assert exc_info.value.status_code == 410


# ---------------------------------------------------------------------------
# Error dispatch — HTTP 423 → LockedError
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_otp_verify_423_raises_locked_error(mg: MailGuard) -> None:
    """HTTP 423 raises LockedError."""
    httpretty.register_uri(
        httpretty.POST,
        OTP_VERIFY_URL,
        body=json.dumps({"detail": {"error": "account_locked", "message": "Account is locked"}}),
        status=423,
        content_type="application/json",
    )
    with pytest.raises(LockedError) as exc_info:
        mg.otp.verify({"email": "user@example.com", "code": "123456"})

    assert exc_info.value.status_code == 423


# ---------------------------------------------------------------------------
# Error dispatch — HTTP 401 → InvalidKeyError
# ---------------------------------------------------------------------------


@httpretty.activate(allow_net_connect=False)
def test_otp_send_401_raises_invalid_key_error(mg: MailGuard) -> None:
    """HTTP 401 raises InvalidKeyError."""
    httpretty.register_uri(
        httpretty.POST,
        OTP_SEND_URL,
        body=json.dumps({"detail": {"error": "invalid_api_key", "message": "Invalid API key"}}),
        status=401,
        content_type="application/json",
    )
    with pytest.raises(InvalidKeyError) as exc_info:
        mg.otp.send({"email": "user@example.com"})

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Timeout → MailGuardError with timeout message
# ---------------------------------------------------------------------------


def test_otp_send_timeout_raises_mailguard_error(mg: MailGuard) -> None:
    """A connection timeout raises MailGuardError with a readable timeout message."""
    timeout_error = urllib.error.URLError(socket.timeout("timed out"))

    with patch("urllib.request.urlopen", side_effect=timeout_error):
        with pytest.raises(MailGuardError) as exc_info:
            mg.otp.send({"email": "user@example.com"})

    err = exc_info.value
    assert "timed out" in str(err).lower()
    assert err.status_code == 0


# ---------------------------------------------------------------------------
# Network failure → MailGuardError
# ---------------------------------------------------------------------------


def test_otp_send_network_failure_raises_mailguard_error(mg: MailGuard) -> None:
    """A network failure raises MailGuardError."""
    network_error = urllib.error.URLError("Name or service not known")

    with patch("urllib.request.urlopen", side_effect=network_error):
        with pytest.raises(MailGuardError) as exc_info:
            mg.otp.send({"email": "user@example.com"})

    assert exc_info.value.status_code == 0


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_all_errors_are_mailguard_error_subclasses() -> None:
    """All typed exceptions inherit from MailGuardError."""
    assert issubclass(RateLimitError, MailGuardError)
    assert issubclass(InvalidCodeError, MailGuardError)
    assert issubclass(ExpiredError, MailGuardError)
    assert issubclass(LockedError, MailGuardError)
    assert issubclass(InvalidKeyError, MailGuardError)


def test_mailguard_error_str_is_readable() -> None:
    """str(error) produces a human-readable message for all error types."""
    assert "Too many requests" in str(RateLimitError("Too many requests", 60))
    assert "Invalid code" in str(InvalidCodeError("Invalid code", 2))
    assert "Expired" in str(ExpiredError("Expired"))
    assert "Locked" in str(LockedError("Locked"))
    assert "Invalid key" in str(InvalidKeyError("Invalid key"))
