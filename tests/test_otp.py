"""
tests/test_otp.py — Part 04 OTP lifecycle tests.

Covers all 6 required edge cases:
  1. OTP past expires_at             → error: otp_expired
  2. is_invalidated = True           → error: otp_expired  (get_active_otp returns None)
  3. Wrong code submitted            → error: invalid_code, attempts_remaining: N
  4. attempt_count >= max_attempts   → error: account_locked
  5. Correct code, first attempt     → verified: True, token present
  6. Correct code submitted twice    → second call returns otp_expired
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import bcrypt
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

from core.models import OtpRecord  # noqa: E402
from core.otp import generate_otp, hash_otp, save_otp, verify_and_consume, verify_otp_hash  # noqa: E402

UTC = timezone.utc
NOW = datetime.now(UTC)
UUID1 = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "proj-0001"
EMAIL = "user@example.com"
PURPOSE = "login"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_otp_record(
    otp_code: str,
    *,
    attempt_count: int = 0,
    otp_max_attempts: int = 5,
    expires_at: datetime | None = None,
    is_invalidated: bool = False,
    is_verified: bool = False,
) -> OtpRecord:
    """Build a realistic OtpRecord for a given plaintext *otp_code*."""
    if expires_at is None:
        expires_at = NOW + timedelta(minutes=10)
    return OtpRecord(
        id=UUID1,
        project_id=PROJECT_ID,
        email_hash="deadbeef" * 8,
        otp_hash=hash_otp(otp_code),
        purpose=PURPOSE,
        attempt_count=attempt_count,
        otp_max_attempts=otp_max_attempts,
        is_verified=is_verified,
        is_invalidated=is_invalidated,
        expires_at=expires_at,
        created_at=NOW - timedelta(minutes=1),
    )


# ---------------------------------------------------------------------------
# generate_otp
# ---------------------------------------------------------------------------

def test_generate_otp_default_length() -> None:
    code = generate_otp()
    assert len(code) == 6
    assert code.isdigit()


def test_generate_otp_custom_length() -> None:
    for length in (4, 6, 8):
        code = generate_otp(length)
        assert len(code) == length
        assert code.isdigit()


def test_generate_otp_zero_padded() -> None:
    """Low random values must be zero-padded to the correct length."""
    # Generate many codes to increase probability of a zero-padded one
    codes = [generate_otp(6) for _ in range(200)]
    assert all(len(c) == 6 for c in codes)


# ---------------------------------------------------------------------------
# hash_otp / verify_otp_hash
# ---------------------------------------------------------------------------

def test_hash_otp_produces_bcrypt_hash() -> None:
    otp = "123456"
    hashed = hash_otp(otp)
    assert hashed.startswith("$2b$")


def test_verify_otp_hash_correct() -> None:
    otp = "987654"
    assert verify_otp_hash(otp, hash_otp(otp)) is True


def test_verify_otp_hash_wrong() -> None:
    otp = "111111"
    assert verify_otp_hash("999999", hash_otp(otp)) is False


# ---------------------------------------------------------------------------
# save_otp
# ---------------------------------------------------------------------------

def test_save_otp_inserts_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """save_otp must call insert_otp_record with the hashed OTP."""
    otp_code = "424242"
    captured: dict = {}

    def fake_insert(data: dict) -> OtpRecord:
        captured.update(data)
        rec = _make_otp_record(otp_code)
        return rec

    monkeypatch.setattr("core.otp.insert_otp_record", fake_insert)
    monkeypatch.setattr("core.otp.hmac_email", lambda e: "hashed_" + e)

    record_id = save_otp(PROJECT_ID, EMAIL, otp_code, PURPOSE, expiry_secs=300)

    assert record_id == UUID1
    assert captured["project_id"] == PROJECT_ID
    assert captured["purpose"] == PURPOSE
    assert captured["otp_max_attempts"] == 5
    # Plaintext OTP must NOT be stored; only the bcrypt hash
    assert captured["otp_hash"] != otp_code
    assert bcrypt.checkpw(otp_code.encode(), captured["otp_hash"].encode())


# ---------------------------------------------------------------------------
# Edge case 1: OTP past expires_at → otp_expired
# ---------------------------------------------------------------------------

def test_expired_otp_returns_otp_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    expired_record = _make_otp_record(
        "123456",
        expires_at=NOW - timedelta(minutes=5),  # in the past
    )
    monkeypatch.setattr("core.otp.get_active_otp", lambda *_: expired_record)

    result = verify_and_consume(PROJECT_ID, EMAIL, "123456")

    assert result["verified"] is False
    assert result["error"] == "otp_expired"


# ---------------------------------------------------------------------------
# Edge case 2: is_invalidated=True → otp_expired
# (get_active_otp filters is_invalidated=False, so returns None)
# ---------------------------------------------------------------------------

def test_invalidated_otp_returns_otp_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    # When is_invalidated=True the DB query returns None
    monkeypatch.setattr("core.otp.get_active_otp", lambda *_: None)

    result = verify_and_consume(PROJECT_ID, EMAIL, "123456")

    assert result["verified"] is False
    assert result["error"] == "otp_expired"


# ---------------------------------------------------------------------------
# Edge case 3: Wrong code → invalid_code + attempts_remaining
# ---------------------------------------------------------------------------

def test_wrong_code_returns_invalid_code(monkeypatch: pytest.MonkeyPatch) -> None:
    otp_code = "555555"
    record = _make_otp_record(otp_code, attempt_count=0, otp_max_attempts=5)

    update_calls: list = []
    monkeypatch.setattr("core.otp.get_active_otp", lambda *_: record)
    monkeypatch.setattr(
        "core.otp.update_otp_record",
        lambda rid, data: update_calls.append((rid, data)),
    )

    result = verify_and_consume(PROJECT_ID, EMAIL, "000000")

    assert result["verified"] is False
    assert result["error"] == "invalid_code"
    # After 1 wrong attempt: 5 - 1 = 4 remaining
    assert result["attempts_remaining"] == 4
    # Attempt counter must have been incremented (the first update call)
    assert update_calls[0] == (UUID1, {"attempt_count": 1})


def test_attempts_remaining_decreases_each_wrong_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    otp_code = "777777"
    record = _make_otp_record(otp_code, attempt_count=3, otp_max_attempts=5)

    monkeypatch.setattr("core.otp.get_active_otp", lambda *_: record)
    monkeypatch.setattr("core.otp.update_otp_record", lambda *_: None)

    result = verify_and_consume(PROJECT_ID, EMAIL, "000000")

    assert result["verified"] is False
    assert result["error"] == "invalid_code"
    # 5 max - (3+1) used = 1 remaining
    assert result["attempts_remaining"] == 1


# ---------------------------------------------------------------------------
# Edge case 4: attempt_count >= max → account_locked
# ---------------------------------------------------------------------------

def test_max_attempts_returns_account_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _make_otp_record("123456", attempt_count=5, otp_max_attempts=5)

    update_mock = MagicMock()
    monkeypatch.setattr("core.otp.get_active_otp", lambda *_: record)
    monkeypatch.setattr("core.otp.update_otp_record", update_mock)

    result = verify_and_consume(PROJECT_ID, EMAIL, "123456")

    assert result["verified"] is False
    assert result["error"] == "account_locked"
    # update_otp_record must NOT be called — no further increments on locked
    update_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case 5: Correct code → verified:True + JWT
# ---------------------------------------------------------------------------

def test_correct_code_returns_verified_and_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    otp_code = "314159"
    record = _make_otp_record(otp_code, attempt_count=0, otp_max_attempts=5)

    update_calls: list = []
    monkeypatch.setattr("core.otp.get_active_otp", lambda *_: record)
    monkeypatch.setattr(
        "core.otp.update_otp_record",
        lambda rid, data: update_calls.append((rid, data)),
    )

    result = verify_and_consume(PROJECT_ID, EMAIL, otp_code)

    assert result["verified"] is True
    assert result["otp_id"] == UUID1
    assert "token" in result and result["token"]

    # Two updates must have occurred:
    # 1. increment attempt_count
    # 2. set is_invalidated=True
    assert len(update_calls) == 2
    assert update_calls[0] == (UUID1, {"attempt_count": 1})
    assert update_calls[1] == (UUID1, {"is_invalidated": True})


def test_correct_code_increment_before_hash_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The attempt counter must be incremented before verify_otp_hash is called."""
    otp_code = "271828"
    record = _make_otp_record(otp_code, attempt_count=0)

    call_order: list[str] = []

    def fake_update(rid: str, data: dict) -> None:
        if "attempt_count" in data:
            call_order.append("increment")

    def fake_verify_hash(plain: str, hashed: str) -> bool:
        call_order.append("hash_check")
        return bcrypt.checkpw(plain.encode(), hashed.encode())

    monkeypatch.setattr("core.otp.get_active_otp", lambda *_: record)
    monkeypatch.setattr("core.otp.update_otp_record", fake_update)
    monkeypatch.setattr("core.otp.verify_otp_hash", fake_verify_hash)

    verify_and_consume(PROJECT_ID, EMAIL, otp_code)

    assert call_order[0] == "increment", (
        "attempt counter must be incremented BEFORE hash check"
    )
    assert call_order[1] == "hash_check"


# ---------------------------------------------------------------------------
# Edge case 6: Correct code used twice → second call returns otp_expired
# ---------------------------------------------------------------------------

def test_correct_code_used_twice_second_call_returns_otp_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    otp_code = "161803"
    record = _make_otp_record(otp_code, attempt_count=0)

    call_count = 0

    def fake_get_active(*_: object) -> OtpRecord | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return record
        # Second call: record was invalidated — DB returns None
        return None

    monkeypatch.setattr("core.otp.get_active_otp", fake_get_active)
    monkeypatch.setattr("core.otp.update_otp_record", lambda *_: None)

    first = verify_and_consume(PROJECT_ID, EMAIL, otp_code)
    assert first["verified"] is True

    second = verify_and_consume(PROJECT_ID, EMAIL, otp_code)
    assert second["verified"] is False
    assert second["error"] == "otp_expired"
