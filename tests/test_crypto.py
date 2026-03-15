"""
tests/test_crypto.py — Part 03 crypto tests.

Covers:
  - encrypt/decrypt round-trip for 500+ random strings
  - hmac_email case and whitespace normalization
  - decrypt() raises on tampered ciphertext
  - wrong ENCRYPTION_KEY raises on decrypt
"""
import os
import random
import secrets
import string

import pytest

# Set required env vars before importing crypto module
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")

from core.crypto import decrypt, encrypt, hmac_email  # noqa: E402


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

def _random_string(min_len: int = 1, max_len: int = 512) -> str:
    length = random.randint(min_len, max_len)
    chars = string.printable
    return "".join(random.choices(chars, k=length))


def test_encrypt_decrypt_roundtrip_500() -> None:
    """encrypt(decrypt(x)) == x for 500 random strings."""
    for _ in range(500):
        plaintext = _random_string()
        assert decrypt(encrypt(plaintext)) == plaintext


def test_encrypt_produces_different_ciphertext_each_call() -> None:
    """Each encrypt() call must produce a different token (fresh IV)."""
    plaintext = "hello world"
    tokens = {encrypt(plaintext) for _ in range(10)}
    assert len(tokens) == 10, "All 10 tokens must be distinct (random IV)"


def test_encrypt_decrypt_empty_string() -> None:
    assert decrypt(encrypt("")) == ""


def test_encrypt_decrypt_unicode() -> None:
    for text in ["こんにちは", "مرحبا", "Héllo wörld", "🔐🔑"]:
        assert decrypt(encrypt(text)) == text


def test_encrypt_decrypt_long_string() -> None:
    long_text = secrets.token_hex(10_000)
    assert decrypt(encrypt(long_text)) == long_text


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------

def test_decrypt_raises_on_tampered_ciphertext() -> None:
    """Flipping any byte in the ciphertext must cause decrypt() to raise."""
    token = encrypt("sensitive data")
    iv_b64, ct_b64 = token.split(":", 1)

    # Flip the last character of the ciphertext base64
    corrupted_ct = ct_b64[:-1] + ("A" if ct_b64[-1] != "A" else "B")
    bad_token = iv_b64 + ":" + corrupted_ct

    with pytest.raises(ValueError):
        decrypt(bad_token)


def test_decrypt_raises_on_truncated_token() -> None:
    with pytest.raises(ValueError):
        decrypt("notavalidtoken")


def test_decrypt_raises_on_empty_token() -> None:
    with pytest.raises(ValueError):
        decrypt("")


# ---------------------------------------------------------------------------
# Wrong key raises
# ---------------------------------------------------------------------------

def test_decrypt_raises_on_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decrypting with a different key must raise ValueError."""
    token = encrypt("my secret")

    # Patch settings to return a different key
    import core.config as config_module

    original_key = config_module.settings.ENCRYPTION_KEY
    # Use a key that is different from the original but still valid (64 hex chars)
    wrong_key = "f" * 64 if original_key != "f" * 64 else "e" * 64

    monkeypatch.setattr(config_module.settings, "ENCRYPTION_KEY", wrong_key)

    with pytest.raises(ValueError):
        decrypt(token)


# ---------------------------------------------------------------------------
# hmac_email normalization
# ---------------------------------------------------------------------------

def test_hmac_email_case_insensitive() -> None:
    """hmac_email must be identical regardless of letter case."""
    assert hmac_email("User@Example.com") == hmac_email("user@example.com")
    assert hmac_email("ADMIN@MYSITE.ORG") == hmac_email("admin@mysite.org")


def test_hmac_email_whitespace_stripped() -> None:
    """Leading/trailing whitespace must not affect the hash."""
    assert hmac_email("  user@example.com  ") == hmac_email("user@example.com")
    assert hmac_email("\tuser@example.com\n") == hmac_email("user@example.com")


def test_hmac_email_case_and_whitespace_combined() -> None:
    """Both normalisations must apply together."""
    assert hmac_email("  User@Example.COM  ") == hmac_email("user@example.com")


def test_hmac_email_deterministic() -> None:
    """Same input must always produce the same hash."""
    email = "consistent@test.com"
    assert hmac_email(email) == hmac_email(email)


def test_hmac_email_different_emails_differ() -> None:
    """Different emails must produce different hashes."""
    assert hmac_email("alice@example.com") != hmac_email("bob@example.com")


def test_hmac_email_returns_hex_string() -> None:
    digest = hmac_email("someone@example.com")
    assert isinstance(digest, str)
    # HMAC-SHA256 produces 64 hex chars
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex
