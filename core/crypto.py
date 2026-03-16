"""
Cryptographic utilities for MailGuard OSS.

Provides:
  - encrypt(plaintext) / decrypt(token)  — AES-256-GCM with a random IV
  - hmac_email(email)                    — HMAC-SHA256 of normalised email address
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.config import settings

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_IV_LEN = 12   # 96-bit nonce — recommended for AES-GCM


def _key_bytes() -> bytes:
    """Return the raw 32-byte AES key derived from the hex config value."""
    return bytes.fromhex(settings.ENCRYPTION_KEY)


# ---------------------------------------------------------------------------
# AES-256-GCM encrypt / decrypt
# ---------------------------------------------------------------------------

def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* with AES-256-GCM.

    Returns a base64-encoded string of the form ``<iv>:<ciphertext+tag>``.
    The IV is freshly generated on every call.
    """
    iv = os.urandom(_IV_LEN)
    aesgcm = AESGCM(_key_bytes())
    ciphertext = aesgcm.encrypt(iv, plaintext.encode(), None)
    iv_b64 = base64.urlsafe_b64encode(iv).decode()
    ct_b64 = base64.urlsafe_b64encode(ciphertext).decode()
    return f"{iv_b64}:{ct_b64}"


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`.

    Raises :class:`ValueError` on a malformed token, tampered ciphertext,
    or wrong key (authentication tag mismatch).
    """
    try:
        iv_b64, ct_b64 = token.split(":", 1)
        iv = base64.urlsafe_b64decode(iv_b64)
        ciphertext = base64.urlsafe_b64decode(ct_b64)
    except Exception as exc:
        raise ValueError(f"Malformed encrypted token: {exc}") from exc

    try:
        aesgcm = AESGCM(_key_bytes())
        plaintext_bytes = aesgcm.decrypt(iv, ciphertext, None)
    except Exception as exc:
        raise ValueError(f"Decryption failed (bad key or tampered data): {exc}") from exc

    return plaintext_bytes.decode()


# ---------------------------------------------------------------------------
# HMAC-SHA256 of email address
# ---------------------------------------------------------------------------

def hmac_email(email: str) -> str:
    """Return a hex HMAC-SHA256 of *email*.

    The email is **always** normalised to lowercase and stripped of leading /
    trailing whitespace before hashing, so that
    ``hmac_email('User@Example.com') == hmac_email('user@example.com')``.
    """
    normalised = email.strip().lower()
    key = bytes.fromhex(settings.ENCRYPTION_KEY)
    digest = hmac.new(key, normalised.encode(), hashlib.sha256).hexdigest()
    return digest
