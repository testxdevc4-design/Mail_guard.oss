"""
API key lifecycle management for MailGuard OSS.

Keys use 256-bit entropy (secrets.token_hex(32)) and are prefixed:
  mg_live_<64 hex chars>  — production keys
  mg_test_<64 hex chars>  — sandbox keys

ONLY the SHA-256 hash is stored in the database.  The plaintext key
is returned once at creation and never written to Supabase.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Tuple

from fastapi import HTTPException

from core.config import settings
from core.db import get_api_key_by_hash, insert_api_key, update_api_key
from core.models import ApiKey

_SANDBOX_PREFIX = "mg_test_"
_LIVE_PREFIX = "mg_live_"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_key(plaintext: str) -> str:
    """Return the SHA-256 hex digest of a plaintext API key."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_api_key(
    project_id: str,
    label: str = "",
    is_sandbox: bool = False,
) -> Tuple[str, ApiKey]:
    """Generate a new API key.

    Uses ``secrets.token_hex(32)`` for 256-bit entropy.  The plaintext key
    is returned exactly once; only its SHA-256 hash is persisted.

    Parameters
    ----------
    project_id:
        UUID of the owning project.
    label:
        Human-readable label (e.g. ``"production server"``).
    is_sandbox:
        When ``True`` the key is prefixed with ``mg_test_``.

    Returns
    -------
    (plaintext_key, ApiKey)
        ``plaintext_key`` must be shown to the user and then discarded.
    """
    prefix = _SANDBOX_PREFIX if is_sandbox else _LIVE_PREFIX
    raw = secrets.token_hex(32)   # 256-bit entropy — never uuid4()
    plaintext = f"{prefix}{raw}"
    key_hash = _hash_key(plaintext)
    key_prefix = plaintext[:12]   # first 12 chars as a display hint

    row = insert_api_key(
        {
            "project_id": project_id,
            "key_hash": key_hash,
            "key_prefix": key_prefix,
            "label": label,
            "is_sandbox": is_sandbox,
            "is_active": True,
        }
    )
    return plaintext, row


def validate_api_key(plaintext: str) -> ApiKey:
    """Validate a plaintext API key and return its database row.

    Security checks are performed in this exact order:

    1. **Sandbox block** — if ``ENV=production`` and the key starts with
       ``mg_test_``, raise ``HTTPException(403)`` *before* any DB lookup.
    2. **Hash lookup** — SHA-256 hash of *plaintext* must match a row in
       ``api_keys``.
    3. **Active check** — ``is_active`` must be ``True``.

    Raises
    ------
    HTTPException(403)
        Key has ``mg_test_`` prefix and ``ENV=production``.
    HTTPException(401)
        Key not found in the database or is revoked.
    """
    # 1. Sandbox block — must be first, before any DB lookup
    if settings.ENV == "production" and plaintext.startswith(_SANDBOX_PREFIX):
        raise HTTPException(
            status_code=403,
            detail={"error": "sandbox_key_in_production"},
        )

    # 2. Hash lookup
    key_hash = _hash_key(plaintext)
    row = get_api_key_by_hash(key_hash)

    if row is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_api_key"},
        )

    # 3. Active check
    if not row.is_active:
        raise HTTPException(
            status_code=401,
            detail={"error": "revoked_api_key"},
        )

    return row


def revoke_api_key(key_id: str) -> ApiKey:
    """Revoke an API key by setting ``is_active=False``.

    Parameters
    ----------
    key_id:
        UUID of the ``api_keys`` row.
    """
    return update_api_key(key_id, {"is_active": False})
