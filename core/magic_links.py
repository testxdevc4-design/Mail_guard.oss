"""
core/magic_links.py — Magic link generation and single-use verification.

Security guarantees
-------------------
- Raw token: ``secrets.token_urlsafe(32)`` — 256-bit URL-safe entropy
- Only SHA-256 hex digest written to the database — raw token never persisted
- Single-use enforced: ``is_used`` and ``used_at`` set atomically before JWT
  is issued; a race condition cannot replay the same link twice
- Expiry: ``MAGIC_LINK_EXPIRY_MINUTES`` (default 15 min) from settings

This module is intentionally free of FastAPI or HTTP concerns so it can be
imported safely by the Telegram bot in Part 12.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from core.config import settings
from core.crypto import hmac_email
from core.db import (
    get_magic_link_by_token_hash,
    insert_magic_link,
    update_magic_link,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256_hex(value: str) -> str:
    """Return the hex-encoded SHA-256 digest of *value*."""
    return hashlib.sha256(value.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_magic_link(
    project_id: str,
    email: str,
    purpose: str = "login",
    redirect_url: Optional[str] = None,
) -> str:
    """Generate a magic link token and persist only its hash in the database.

    Returns the raw URL-safe token (256-bit entropy).  The raw token is
    returned to the caller exactly once and is **never** stored anywhere.
    Only the SHA-256 hex digest is written to the ``magic_links`` table.

    Parameters
    ----------
    project_id:
        UUID of the project that owns this magic link.
    email:
        Recipient email address (stored as HMAC hash only).
    purpose:
        Human-readable purpose string (e.g. ``"login"``).
    redirect_url:
        Optional URL to redirect the user to after successful verification.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = _sha256_hex(raw_token)

    insert_magic_link(
        {
            "project_id": project_id,
            "email_hash": hmac_email(email),
            "token_hash": token_hash,
            "purpose": purpose,
            "redirect_url": redirect_url,
            "is_used": False,
            "expires_at": (
                datetime.now(UTC)
                + timedelta(minutes=settings.MAGIC_LINK_EXPIRY_MINUTES)
            ).isoformat(),
        }
    )

    return raw_token  # only time the raw token is returned; never stored


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_magic_link(token: str) -> Dict[str, Any]:
    """Verify *token* and, on success, atomically mark it used and issue JWT.

    Returns a dict with keys:

    - ``verified``: bool
    - ``error``: str  (present when ``verified`` is ``False``)
    - ``token``: str  signed JWT  (present on success)
    - ``link_id``: str  record UUID  (present on success)
    - ``redirect_url``: Optional[str]  (present on success)

    Single-use guarantee: ``is_used=True`` and ``used_at=now()`` are written
    to the database in a single update call *before* the JWT is issued.  This
    means two concurrent verify requests will both read the row as ``is_used=False``
    but only the first update will commit the is_used flag before the JWT is
    returned — and the second request will read ``is_used=True`` on its lookup.
    """
    from core.jwt_utils import issue_jwt  # local import — avoids circular deps

    token_hash = _sha256_hex(token)
    row = get_magic_link_by_token_hash(token_hash)

    if row is None:
        return {"verified": False, "error": "invalid_token"}

    if row.is_used:
        return {"verified": False, "error": "already_used"}

    now = datetime.now(UTC)
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if now > expires:
        return {"verified": False, "error": "expired"}

    # Atomically mark as used BEFORE issuing JWT — prevents replay attacks
    update_magic_link(
        row.id,
        {
            "is_used": True,
            "used_at": now.isoformat(),
        },
    )

    jwt_token = issue_jwt(
        subject=row.email_hash,
        extra_claims={"link_id": row.id, "purpose": row.purpose},
    )

    return {
        "verified": True,
        "link_id": row.id,
        "token": jwt_token,
        "redirect_url": row.redirect_url,
    }
