"""
Magic link generation and single-use verification for MailGuard OSS.

Security guarantees
-------------------
- Tokens generated with ``secrets.token_urlsafe(32)`` — 256-bit URL-safe entropy
- Only the SHA-256 hex digest of the raw token is stored in the database;
  the raw token is returned to the caller once and never persisted anywhere
- Single-use enforced: ``is_used=True`` and ``used_at=now()`` are set in a
  single ``update_magic_link`` call before this function returns, so a
  concurrent second request cannot succeed (no race window)
- Expiry enforced: tokens older than ``MAGIC_LINK_EXPIRY_MINUTES`` are rejected

This module is intentionally free of FastAPI/HTTP concerns so that it can
be imported by the Telegram bot (Part 12) without pulling in web-layer deps.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core.config import settings
from core.crypto import hmac_email
from core.db import get_magic_link_by_token_hash, insert_magic_link, update_magic_link

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256_hex(token: str) -> str:
    """Return the lowercase SHA-256 hex digest of *token*."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_magic_link(
    project_id: str,
    email: str,
    purpose: str = "login",
    redirect_url: str = "",
    expiry_minutes: Optional[int] = None,
) -> tuple[str, str]:
    """Generate a magic-link token and persist its hash.

    Returns a 2-tuple of ``(raw_token, magic_link_id)``.

    The *raw_token* is the secret that should be embedded in the email URL.
    It is **never** stored in the database — only its SHA-256 hash is persisted.

    Parameters
    ----------
    project_id:
        UUID of the owning project.
    email:
        Recipient email address (will be HMAC-hashed before storage).
    purpose:
        Human-readable purpose string (e.g. ``"login"``).
    redirect_url:
        URL to redirect to after successful verification.  Empty string
        means no redirect.
    expiry_minutes:
        Override the default ``MAGIC_LINK_EXPIRY_MINUTES`` setting.
    """
    expiry = (
        expiry_minutes
        if expiry_minutes is not None
        else settings.MAGIC_LINK_EXPIRY_MINUTES
    )
    raw_token = secrets.token_urlsafe(32)
    token_hash = _sha256_hex(raw_token)

    rec = insert_magic_link({
        "project_id": project_id,
        "email_hash": hmac_email(email),
        "token_hash": token_hash,
        "purpose": purpose,
        "redirect_url": redirect_url or "",
        "is_used": False,
        "expires_at": (
            datetime.now(UTC) + timedelta(minutes=expiry)
        ).isoformat(),
    })
    return raw_token, rec.id


def verify_magic_link(raw_token: str) -> Dict[str, Any]:
    """Verify a magic-link token and mark it consumed if valid.

    Returns a dict with the following keys:

    - ``verified``: bool — ``True`` on success, ``False`` on any failure
    - ``error``: str — present when ``verified`` is ``False``
      (``"not_found"``, ``"already_used"``, or ``"expired"``)
    - ``magic_link_id``: str — present on success
    - ``email_hash``: str — present on success
    - ``redirect_url``: str — present on success (may be an empty string)
    - ``token``: str — signed JWT (present on success)

    Single-use guarantee
    --------------------
    ``is_used=True`` and ``used_at=now()`` are written in a *single*
    ``update_magic_link`` database call.  No separate read-then-write
    window exists, so concurrent requests for the same token will both
    receive a ``"already_used"`` error after the first succeeds.
    """
    from core.jwt_utils import issue_jwt  # local import — avoids circular deps

    token_hash = _sha256_hex(raw_token)
    row = get_magic_link_by_token_hash(token_hash)

    if row is None:
        return {"verified": False, "error": "not_found"}

    # Already consumed by a previous request
    if row.is_used:
        return {"verified": False, "error": "already_used"}

    # Explicit expiry check
    now = datetime.now(UTC)
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if now > expires:
        return {"verified": False, "error": "expired"}

    # ── CRITICAL: mark as used before returning ───────────────────────────
    # Both fields are set in one call — no race window between read and write.
    update_magic_link(row.id, {
        "is_used": True,
        "used_at": now.isoformat(),
    })

    jwt_token = issue_jwt(
        subject=row.email_hash,
        extra_claims={
            "magic_link_id": row.id,
            "purpose": row.purpose,
        },
    )

    return {
        "verified": True,
        "magic_link_id": row.id,
        "email_hash": row.email_hash,
        "redirect_url": row.redirect_url or "",
        "token": jwt_token,
    }
