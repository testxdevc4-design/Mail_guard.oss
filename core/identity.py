"""
Identity signature system for MailGuard OSS.

Provides anonymous-user identity verification without authentication:

- Users identify themselves with a ``userId`` stored client-side
  (e.g. localStorage).
- A server-side HMAC-SHA256 *signature* is derived from the userId using the
  ``JWT_SECRET`` as the signing key.
- The signature is stored alongside the userId and sent in request headers
  (``X-User-Id`` / ``X-User-Sig``).
- The backend re-derives the expected signature and compares with
  constant-time equality to prevent forgery.

This prevents identity spoofing: an attacker who knows a victim's userId
cannot compute the correct signature without knowing the server secret.

Usage
-----
::

    from core.identity import generate_user_id, generate_signature, verify_signature

    # On first visit (client-side storage)
    uid = generate_user_id()
    sig = generate_signature(uid)

    # On subsequent requests (server-side verification)
    valid = verify_signature(uid, sig)
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from core.config import settings

# ---------------------------------------------------------------------------
# User-ID generation
# ---------------------------------------------------------------------------

_USER_ID_BYTES: int = 16  # 128 bits → 22-char URL-safe base64 string


def generate_user_id() -> str:
    """Generate a unique, cryptographically secure anonymous user ID.

    Returns
    -------
    str
        A 22-character URL-safe base64-encoded random identifier.
    """
    return secrets.token_urlsafe(_USER_ID_BYTES)


# ---------------------------------------------------------------------------
# Signature generation & verification
# ---------------------------------------------------------------------------

def generate_signature(user_id: str) -> str:
    """Generate an HMAC-SHA256 signature for *user_id*.

    Uses ``settings.JWT_SECRET`` (minimum 64 characters) as the HMAC key so
    that no additional secret configuration is required.

    Parameters
    ----------
    user_id:
        The anonymous user identifier (e.g. from localStorage ``ib_uid``).

    Returns
    -------
    str
        A lowercase 64-character hex HMAC-SHA256 digest.

    Raises
    ------
    TypeError
        If *user_id* is not a :class:`str`.
    """
    if not isinstance(user_id, str):
        raise TypeError(f"user_id must be a str, got {type(user_id).__name__!r}")
    key = settings.JWT_SECRET.encode("utf-8")
    return hmac.new(key, user_id.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(user_id: str, signature: str) -> bool:
    """Verify the HMAC-SHA256 *signature* for *user_id*.

    Uses constant-time comparison (:func:`hmac.compare_digest`) to prevent
    timing-based side-channel attacks.

    Parameters
    ----------
    user_id:
        The user identifier extracted from the ``X-User-Id`` header.
    signature:
        The hex signature extracted from the ``X-User-Sig`` header.

    Returns
    -------
    bool
        ``True`` if the signature is valid; ``False`` otherwise.
        Returns ``False`` (not raises) for any type or value error so that
        callers can treat invalid inputs as authentication failures.
    """
    if not isinstance(user_id, str) or not isinstance(signature, str):
        return False
    try:
        expected = generate_signature(user_id)
    except TypeError:
        return False
    return hmac.compare_digest(expected, signature)
