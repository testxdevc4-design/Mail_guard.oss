"""
tests/test_jwt.py — Part 04 JWT utility tests.

Covers:
  - issue_jwt produces a valid, decodable HS256 token
  - verify_jwt returns the correct payload
  - Expired tokens raise ValueError
  - Tampered signature raises ValueError
  - Revoked jti raises ValueError
  - Every issued token has a unique jti
"""
from __future__ import annotations

import os
import time
from datetime import timezone
from unittest.mock import MagicMock

import pytest
from jose import jwt as jose_jwt

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

from core.jwt_utils import issue_jwt, revoke_jwt, verify_jwt  # noqa: E402

UTC = timezone.utc
SUBJECT = "deadbeef" * 8  # 64-char email hash placeholder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis(revoked_jti: str | None = None) -> MagicMock:
    """Return a mock Redis client optionally pre-loaded with a revoked jti."""
    r = MagicMock()
    r.get.side_effect = lambda key: (
        "1" if revoked_jti and key == f"jti_blacklist:{revoked_jti}" else None
    )
    return r


# ---------------------------------------------------------------------------
# issue_jwt
# ---------------------------------------------------------------------------

def test_issue_jwt_returns_string() -> None:
    token = issue_jwt(subject=SUBJECT)
    assert isinstance(token, str)
    assert len(token) > 20


def test_issue_jwt_payload_contains_required_claims() -> None:
    token = issue_jwt(subject=SUBJECT)
    payload = jose_jwt.decode(
        token, os.environ["JWT_SECRET"], algorithms=["HS256"]
    )
    assert payload["sub"] == SUBJECT
    assert "jti" in payload and len(payload["jti"]) == 32  # hex(16) = 32 chars
    assert "iat" in payload
    assert "exp" in payload


def test_issue_jwt_expiry_is_correct() -> None:
    token = issue_jwt(subject=SUBJECT)
    payload = jose_jwt.decode(
        token, os.environ["JWT_SECRET"], algorithms=["HS256"]
    )
    expiry_minutes = 10  # default JWT_EXPIRY_MINUTES
    exp_delta = payload["exp"] - payload["iat"]
    # Allow ±2 seconds tolerance for clock skew in tests
    assert expiry_minutes * 60 - 2 <= exp_delta <= expiry_minutes * 60 + 2


def test_issue_jwt_jti_is_unique() -> None:
    """Every issued token must have a distinct jti."""
    jtis = set()
    for _ in range(50):
        token = issue_jwt(subject=SUBJECT)
        payload = jose_jwt.decode(
            token, os.environ["JWT_SECRET"], algorithms=["HS256"]
        )
        jtis.add(payload["jti"])
    assert len(jtis) == 50


def test_issue_jwt_extra_claims_are_included() -> None:
    token = issue_jwt(subject=SUBJECT, extra_claims={"purpose": "login", "foo": "bar"})
    payload = jose_jwt.decode(
        token, os.environ["JWT_SECRET"], algorithms=["HS256"]
    )
    assert payload["purpose"] == "login"
    assert payload["foo"] == "bar"


# ---------------------------------------------------------------------------
# verify_jwt
# ---------------------------------------------------------------------------

def test_verify_jwt_returns_payload() -> None:
    token = issue_jwt(subject=SUBJECT, extra_claims={"purpose": "test"})
    payload = verify_jwt(token)
    assert payload["sub"] == SUBJECT
    assert payload["purpose"] == "test"


def test_verify_jwt_without_redis_skips_revocation_check() -> None:
    """When no redis_client is provided, verify_jwt must not raise."""
    token = issue_jwt(subject=SUBJECT)
    payload = verify_jwt(token, redis_client=None)
    assert payload["sub"] == SUBJECT


def test_verify_jwt_with_redis_checks_revocation() -> None:
    """verify_jwt must call redis.get(jti_blacklist:{jti}) when client provided."""
    token = issue_jwt(subject=SUBJECT)
    payload_raw = jose_jwt.decode(
        token, os.environ["JWT_SECRET"], algorithms=["HS256"]
    )
    jti = payload_raw["jti"]

    redis_mock = _make_redis(revoked_jti=None)
    verify_jwt(token, redis_client=redis_mock)
    redis_mock.get.assert_called_once_with(f"jti_blacklist:{jti}")


# ---------------------------------------------------------------------------
# Expired token
# ---------------------------------------------------------------------------

def test_verify_jwt_raises_on_expired_token() -> None:
    """An expired token must raise ValueError."""
    import core.config as cfg_module

    # Build a token whose exp is already in the past
    now = int(time.time())
    payload = {
        "sub": SUBJECT,
        "jti": "test_expired_jti",
        "iat": now - 120,
        "exp": now - 60,  # expired 60 seconds ago
    }
    expired_token = jose_jwt.encode(
        payload, cfg_module.settings.JWT_SECRET, algorithm="HS256"
    )

    with pytest.raises(ValueError, match="Invalid JWT"):
        verify_jwt(expired_token)


# ---------------------------------------------------------------------------
# Tampered signature
# ---------------------------------------------------------------------------

def test_verify_jwt_raises_on_tampered_token() -> None:
    """Flipping any character in the signature must raise ValueError."""
    token = issue_jwt(subject=SUBJECT)
    # The JWT has 3 parts separated by '.'; corrupt the last part (signature)
    header, payload_b64, sig = token.rsplit(".", 2)
    bad_sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    bad_token = f"{header}.{payload_b64}.{bad_sig}"

    with pytest.raises(ValueError, match="Invalid JWT"):
        verify_jwt(bad_token)


def test_verify_jwt_raises_on_wrong_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token signed with a different secret must raise ValueError."""
    token = issue_jwt(subject=SUBJECT)

    import core.config as cfg_module

    original_secret = cfg_module.settings.JWT_SECRET
    wrong_secret = "c" * 64 if original_secret != "c" * 64 else "d" * 64
    monkeypatch.setattr(cfg_module.settings, "JWT_SECRET", wrong_secret)

    with pytest.raises(ValueError, match="Invalid JWT"):
        verify_jwt(token)


# ---------------------------------------------------------------------------
# Revoked jti
# ---------------------------------------------------------------------------

def test_verify_jwt_raises_on_revoked_jti() -> None:
    """verify_jwt must raise ValueError when the token's jti is blacklisted."""
    token = issue_jwt(subject=SUBJECT)
    payload_raw = jose_jwt.decode(
        token, os.environ["JWT_SECRET"], algorithms=["HS256"]
    )
    jti = payload_raw["jti"]

    redis_mock = _make_redis(revoked_jti=jti)

    with pytest.raises(ValueError, match="revoked"):
        verify_jwt(token, redis_client=redis_mock)


def test_revoke_jwt_stores_jti_in_redis() -> None:
    """revoke_jwt must store jti_blacklist:{jti} with a positive TTL."""
    token = issue_jwt(subject=SUBJECT)
    payload_raw = jose_jwt.decode(
        token, os.environ["JWT_SECRET"], algorithms=["HS256"]
    )
    jti = payload_raw["jti"]

    redis_mock = MagicMock()
    revoke_jwt(token, redis_mock)

    redis_mock.set.assert_called_once()
    args, kwargs = redis_mock.set.call_args
    assert args[0] == f"jti_blacklist:{jti}"
    assert args[1] == "1"
    assert "ex" in kwargs and kwargs["ex"] >= 1


def test_revoke_then_verify_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full round-trip: issue → revoke → verify must raise on revoked token."""
    token = issue_jwt(subject=SUBJECT)

    # Use a simple in-memory store for the blacklist
    blacklist: dict[str, str] = {}

    class FakeRedis:
        def get(self, key: str) -> str | None:
            return blacklist.get(key)

        def set(self, key: str, value: str, ex: int = 0) -> None:
            blacklist[key] = value

    redis = FakeRedis()
    revoke_jwt(token, redis)

    with pytest.raises(ValueError, match="revoked"):
        verify_jwt(token, redis_client=redis)
