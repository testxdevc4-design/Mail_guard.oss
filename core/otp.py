"""
OTP generation, hashing, storage, and verification lifecycle for MailGuard OSS.

Security guarantees
-------------------
- Codes generated with ``secrets.randbelow`` — cryptographically secure PRNG
- Hashed with bcrypt (cost 10) — constant-time comparison via ``checkpw``
- Attempt counter incremented **before** hash check — prevents timing oracle
- Record invalidated on first successful verify — prevents replay attacks
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import bcrypt

from core.crypto import hmac_email
from core.db import get_active_otp, insert_otp_record, update_otp_record

UTC = timezone.utc


# ---------------------------------------------------------------------------
# OTP generation and hashing
# ---------------------------------------------------------------------------

def generate_otp(length: int = 6) -> str:
    """Generate a cryptographically secure zero-padded numeric OTP."""
    return str(secrets.randbelow(10 ** length)).zfill(length)


def hash_otp(otp: str) -> str:
    """Return a bcrypt hash of *otp* (cost 10)."""
    return bcrypt.hashpw(otp.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_otp_hash(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt comparison — never use ``==`` on raw values."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_otp(
    project_id: str,
    email: str,
    otp: str,
    purpose: str,
    expiry_secs: int,
    max_attempts: int = 5,
) -> str:
    """Hash and persist an OTP record; return the record UUID."""
    rec = insert_otp_record({
        "project_id": project_id,
        "email_hash": hmac_email(email),
        "otp_hash": hash_otp(otp),
        "purpose": purpose,
        "attempt_count": 0,
        "otp_max_attempts": max_attempts,
        "is_verified": False,
        "is_invalidated": False,
        "expires_at": (
            datetime.now(UTC) + timedelta(seconds=expiry_secs)
        ).isoformat(),
    })
    return rec.id


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_and_consume(
    project_id: str,
    email: str,
    submitted: str,
) -> Dict[str, Any]:
    """Verify *submitted* against the active OTP for *project_id*/*email*.

    Returns a dict with keys:

    - ``verified``: bool
    - ``error``: str  (present when ``verified`` is ``False``)
    - ``attempts_remaining``: int  (present on ``invalid_code`` only)
    - ``otp_id``: str  (present on success)
    - ``token``: str   JWT  (present on success)

    Security guarantee: the attempt counter is incremented **before** the
    hash comparison so that a timing side-channel cannot reveal whether a
    submitted code is correct.
    """
    from core.jwt_utils import issue_jwt  # local import — avoids circular deps

    row = get_active_otp(project_id, hmac_email(email))

    # No active (non-invalidated, non-verified) record found
    if row is None:
        return {"verified": False, "error": "otp_expired"}

    # Explicit expiry check (get_active_otp does not filter by expires_at)
    now = datetime.now(UTC)
    expires = row.expires_at
    # Ensure expires_at is timezone-aware for comparison
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if now > expires:
        return {"verified": False, "error": "otp_expired"}

    max_att = row.otp_max_attempts

    # Already consumed all attempts before this request
    if row.attempt_count >= max_att:
        return {"verified": False, "error": "account_locked"}

    # ── CRITICAL: increment BEFORE hash check — no timing oracle ─────────
    new_count = row.attempt_count + 1
    update_otp_record(row.id, {"attempt_count": new_count})

    if not verify_otp_hash(submitted, row.otp_hash):
        remaining = max(0, max_att - new_count)
        return {
            "verified": False,
            "error": "invalid_code",
            "attempts_remaining": remaining,
        }

    # Correct code — invalidate to prevent replay
    update_otp_record(row.id, {"is_invalidated": True})

    token = issue_jwt(
        subject=row.email_hash,
        extra_claims={"otp_id": row.id, "purpose": row.purpose},
    )
    return {"verified": True, "otp_id": row.id, "token": token}
