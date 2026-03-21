"""
SHA-256 key hashing utilities for MailGuard OSS.

Implements the element ownership key-security system:

- Raw keys are **never stored**.  Only their SHA-256 digest is persisted.
- Verification uses constant-time comparison to prevent timing attacks.
- New keys are generated with ``secrets.token_urlsafe`` (URL-safe base64,
  cryptographically strong random bytes).

Usage
-----
::

    from core.key_hash import generate_key, hash_key, verify_key

    # On element creation
    raw_key  = generate_key()         # share with owner
    key_hash = hash_key(raw_key)      # persist to DB

    # On edit / delete
    ok = verify_key(submitted_key, stored_hash)
"""
from __future__ import annotations

import hashlib
import hmac
import secrets


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

_DEFAULT_KEY_BYTES: int = 32  # 256 bits → 43-char URL-safe base64 string


def generate_key(nbytes: int = _DEFAULT_KEY_BYTES) -> str:
    """Generate a cryptographically secure random ownership key.

    Parameters
    ----------
    nbytes:
        Number of random bytes to generate (default ``32``, i.e. 256 bits).
        The returned string will be longer due to base64 encoding.

    Returns
    -------
    str
        A URL-safe base64-encoded random string with no padding characters.
    """
    return secrets.token_urlsafe(nbytes)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of *raw_key*.

    The key is encoded as UTF-8 before hashing.  The digest is returned as a
    lowercase 64-character hex string suitable for direct DB storage.

    Parameters
    ----------
    raw_key:
        The plaintext ownership key supplied by the element owner.

    Returns
    -------
    str
        Lowercase 64-character hex string (SHA-256 digest).

    Raises
    ------
    TypeError
        If *raw_key* is not a :class:`str`.
    """
    if not isinstance(raw_key, str):
        raise TypeError(f"raw_key must be a str, got {type(raw_key).__name__!r}")
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_key(raw_key: str, stored_hash: str) -> bool:
    """Verify that *raw_key* matches *stored_hash* using constant-time comparison.

    Computes ``sha256(raw_key)`` and compares it to *stored_hash* using
    :func:`hmac.compare_digest` to prevent timing-based side-channel attacks.

    Parameters
    ----------
    raw_key:
        The plaintext key submitted by the user for edit / delete.
    stored_hash:
        The SHA-256 hex digest previously stored in the database.

    Returns
    -------
    bool
        ``True`` if and only if the computed digest matches *stored_hash*.
    """
    if not isinstance(raw_key, str) or not isinstance(stored_hash, str):
        return False
    computed = hash_key(raw_key)
    return hmac.compare_digest(computed, stored_hash)
