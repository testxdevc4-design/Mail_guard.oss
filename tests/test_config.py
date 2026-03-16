"""
tests/test_config.py — Part 15 Settings validation tests.

Covers every validator in core/config.py:
  - ENCRYPTION_KEY shorter than 64 chars raises ValidationError
  - ENCRYPTION_KEY that is not valid hex raises ValidationError
  - ENCRYPTION_KEY exactly 64 valid hex chars passes
  - JWT_SECRET shorter than 64 chars raises ValidationError
  - REDIS_URL not starting with redis:// or rediss:// raises ValidationError
  - Missing required field raises ValidationError
  - All valid values together produce a working Settings instance
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")

from pydantic import ValidationError  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_ENC_KEY = "a" * 64   # 64 lowercase hex chars (valid)
_VALID_JWT_SECRET = "b" * 64

# Full set of valid env vars for use in patched tests
_VALID_ENV = {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "REDIS_URL": "redis://localhost:6379",
    "ENCRYPTION_KEY": _VALID_ENC_KEY,
    "JWT_SECRET": _VALID_JWT_SECRET,
    "TELEGRAM_BOT_TOKEN": "test:token",
    "TELEGRAM_ADMIN_UID": "1",
    "ENV": "development",
}


def _make_settings_from_env(env_overrides: dict | None = None) -> object:
    """Create Settings by patching the process environment.

    Pydantic-settings reads from env vars; we control exactly what's present
    by passing a clean dict and optional overrides.
    """
    from core.config import Settings
    env = {**_VALID_ENV, **(env_overrides or {})}
    with patch.dict(os.environ, env, clear=True):
        return Settings()


def _make_settings_missing(missing_key: str) -> None:
    """Try to create Settings with one required env var removed."""
    from core.config import Settings
    env = {k: v for k, v in _VALID_ENV.items() if k != missing_key}
    with patch.dict(os.environ, env, clear=True):
        Settings()


# ---------------------------------------------------------------------------
# ENCRYPTION_KEY validator
# ---------------------------------------------------------------------------

class TestEncryptionKeyValidator:
    def test_short_key_raises(self) -> None:
        """ENCRYPTION_KEY shorter than 64 chars must raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"ENCRYPTION_KEY": "a" * 32})

    def test_exactly_63_chars_raises(self) -> None:
        """63-char key is invalid (one short of required 64)."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"ENCRYPTION_KEY": "a" * 63})

    def test_65_chars_raises(self) -> None:
        """65-char key is invalid (one over required 64)."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"ENCRYPTION_KEY": "a" * 65})

    def test_empty_key_raises(self) -> None:
        """Empty ENCRYPTION_KEY must raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"ENCRYPTION_KEY": ""})

    def test_non_hex_key_raises(self) -> None:
        """ENCRYPTION_KEY that is not valid hex must raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"ENCRYPTION_KEY": "g" * 64})

    def test_non_hex_mixed_raises(self) -> None:
        """63 valid hex chars + 1 non-hex char must raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"ENCRYPTION_KEY": "a" * 63 + "z"})

    def test_valid_64_hex_chars_passes(self) -> None:
        """ENCRYPTION_KEY of exactly 64 valid hex chars must succeed."""
        settings = _make_settings_from_env({"ENCRYPTION_KEY": "a" * 64})
        assert settings.ENCRYPTION_KEY == "a" * 64  # type: ignore[attr-defined]

    def test_valid_uppercase_hex_passes(self) -> None:
        """Uppercase hex chars are valid."""
        settings = _make_settings_from_env({"ENCRYPTION_KEY": "A" * 64})
        assert len(settings.ENCRYPTION_KEY) == 64  # type: ignore[attr-defined]

    def test_valid_all_digits_passes(self) -> None:
        """All-numeric 64-char key is valid hex."""
        settings = _make_settings_from_env({"ENCRYPTION_KEY": "1" * 64})
        assert settings.ENCRYPTION_KEY == "1" * 64  # type: ignore[attr-defined]

    def test_validator_directly_short(self) -> None:
        """Call the field_validator directly — short key raises ValueError."""
        from core.config import Settings
        with pytest.raises(ValueError, match="64 hex"):
            Settings.check_enc_key("a" * 32)

    def test_validator_directly_non_hex(self) -> None:
        """Call the field_validator directly — non-hex raises ValueError."""
        from core.config import Settings
        with pytest.raises(ValueError, match="hex"):
            Settings.check_enc_key("g" * 64)

    def test_validator_directly_valid(self) -> None:
        """Call the field_validator directly — valid 64-hex-char key returns value."""
        from core.config import Settings
        result = Settings.check_enc_key("a" * 64)
        assert result == "a" * 64


# ---------------------------------------------------------------------------
# JWT_SECRET validator
# ---------------------------------------------------------------------------

class TestJwtSecretValidator:
    def test_short_secret_raises(self) -> None:
        """JWT_SECRET shorter than 64 chars must raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"JWT_SECRET": "x" * 32})

    def test_exactly_63_chars_raises(self) -> None:
        """63-char JWT_SECRET is one short of the minimum."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"JWT_SECRET": "y" * 63})

    def test_empty_jwt_secret_raises(self) -> None:
        """Empty JWT_SECRET must raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"JWT_SECRET": ""})

    def test_exactly_64_chars_passes(self) -> None:
        """JWT_SECRET of exactly 64 chars must succeed."""
        settings = _make_settings_from_env({"JWT_SECRET": "x" * 64})
        assert len(settings.JWT_SECRET) == 64  # type: ignore[attr-defined]

    def test_longer_than_64_chars_passes(self) -> None:
        """JWT_SECRET longer than 64 chars must also succeed."""
        settings = _make_settings_from_env({"JWT_SECRET": "x" * 128})
        assert len(settings.JWT_SECRET) == 128  # type: ignore[attr-defined]

    def test_validator_directly_short(self) -> None:
        """Call the field_validator directly — short secret raises ValueError."""
        from core.config import Settings
        with pytest.raises(ValueError, match="64"):
            Settings.check_jwt_secret("x" * 32)

    def test_validator_directly_valid(self) -> None:
        """Call the field_validator directly — valid secret returns value."""
        from core.config import Settings
        result = Settings.check_jwt_secret("x" * 64)
        assert result == "x" * 64


# ---------------------------------------------------------------------------
# REDIS_URL validator
# ---------------------------------------------------------------------------

class TestRedisUrlValidator:
    def test_http_url_raises(self) -> None:
        """REDIS_URL starting with http:// must raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"REDIS_URL": "http://localhost:6379"})

    def test_bare_host_raises(self) -> None:
        """REDIS_URL without a protocol must raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"REDIS_URL": "localhost:6379"})

    def test_empty_url_raises(self) -> None:
        """Empty REDIS_URL must raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"REDIS_URL": ""})

    def test_postgresql_url_raises(self) -> None:
        """postgresql:// scheme must be rejected."""
        with pytest.raises((ValidationError, ValueError)):
            _make_settings_from_env({"REDIS_URL": "postgresql://localhost:5432/db"})

    def test_redis_scheme_passes(self) -> None:
        """redis:// scheme must pass validation."""
        settings = _make_settings_from_env({"REDIS_URL": "redis://localhost:6379"})
        assert settings.REDIS_URL == "redis://localhost:6379"  # type: ignore[attr-defined]

    def test_rediss_scheme_passes(self) -> None:
        """rediss:// (TLS) scheme must also pass validation."""
        settings = _make_settings_from_env(
            {"REDIS_URL": "rediss://my-redis.upstash.io:6380"}
        )
        assert settings.REDIS_URL.startswith("rediss://")  # type: ignore[attr-defined]

    def test_redis_with_password_passes(self) -> None:
        """redis://:password@host:port is a valid redis:// URL."""
        url = "redis://:mypassword@redis.example.com:6379"
        settings = _make_settings_from_env({"REDIS_URL": url})
        assert settings.REDIS_URL == url  # type: ignore[attr-defined]

    def test_validator_directly_valid_redis(self) -> None:
        """Call the field_validator directly — valid redis:// passes."""
        from core.config import Settings
        result = Settings.check_redis_url("redis://localhost:6379")
        assert result == "redis://localhost:6379"

    def test_validator_directly_valid_rediss(self) -> None:
        """Call the field_validator directly — valid rediss:// passes."""
        from core.config import Settings
        result = Settings.check_redis_url("rediss://host:6380")
        assert result == "rediss://host:6380"

    def test_validator_directly_invalid(self) -> None:
        """Call the field_validator directly — invalid scheme raises ValueError."""
        from core.config import Settings
        with pytest.raises(ValueError, match="redis"):
            Settings.check_redis_url("http://localhost:6379")


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    def test_missing_supabase_url_raises(self) -> None:
        """Omitting SUPABASE_URL must raise ValidationError."""
        with pytest.raises((ValidationError, Exception)):
            _make_settings_missing("SUPABASE_URL")

    def test_missing_service_role_key_raises(self) -> None:
        """Omitting SUPABASE_SERVICE_ROLE_KEY must raise ValidationError."""
        with pytest.raises((ValidationError, Exception)):
            _make_settings_missing("SUPABASE_SERVICE_ROLE_KEY")

    def test_missing_encryption_key_raises(self) -> None:
        """Omitting ENCRYPTION_KEY must raise ValidationError."""
        with pytest.raises((ValidationError, Exception)):
            _make_settings_missing("ENCRYPTION_KEY")

    def test_missing_jwt_secret_raises(self) -> None:
        """Omitting JWT_SECRET must raise ValidationError."""
        with pytest.raises((ValidationError, Exception)):
            _make_settings_missing("JWT_SECRET")

    def test_missing_telegram_bot_token_raises(self) -> None:
        """Omitting TELEGRAM_BOT_TOKEN must raise ValidationError."""
        with pytest.raises((ValidationError, Exception)):
            _make_settings_missing("TELEGRAM_BOT_TOKEN")


# ---------------------------------------------------------------------------
# All valid values together
# ---------------------------------------------------------------------------

class TestAllValidValuesTogether:
    def test_full_valid_settings(self) -> None:
        """All valid values together must produce a working Settings instance."""
        settings = _make_settings_from_env()
        assert settings.SUPABASE_URL == "https://test.supabase.co"  # type: ignore[attr-defined]
        assert settings.SUPABASE_SERVICE_ROLE_KEY == "service-role-key"  # type: ignore[attr-defined]
        assert settings.REDIS_URL == "redis://localhost:6379"  # type: ignore[attr-defined]
        assert settings.ENCRYPTION_KEY == _VALID_ENC_KEY  # type: ignore[attr-defined]
        assert settings.JWT_SECRET == _VALID_JWT_SECRET  # type: ignore[attr-defined]
        assert settings.JWT_EXPIRY_MINUTES == 10  # type: ignore[attr-defined]
        assert settings.MAGIC_LINK_EXPIRY_MINUTES == 15  # type: ignore[attr-defined]
        assert settings.ENV == "development"  # type: ignore[attr-defined]
        assert settings.PORT == 3000  # type: ignore[attr-defined]
        assert settings.ROTATION_THRESHOLD == 0.80  # type: ignore[attr-defined]

    def test_custom_expiry_minutes(self) -> None:
        """JWT_EXPIRY_MINUTES and MAGIC_LINK_EXPIRY_MINUTES can be customised."""
        settings = _make_settings_from_env(
            {"JWT_EXPIRY_MINUTES": "5", "MAGIC_LINK_EXPIRY_MINUTES": "30"}
        )
        assert settings.JWT_EXPIRY_MINUTES == 5  # type: ignore[attr-defined]
        assert settings.MAGIC_LINK_EXPIRY_MINUTES == 30  # type: ignore[attr-defined]

    def test_custom_port(self) -> None:
        """PORT can be set to a custom value."""
        settings = _make_settings_from_env({"PORT": "8080"})
        assert settings.PORT == 8080  # type: ignore[attr-defined]

    def test_rotation_threshold_custom(self) -> None:
        """ROTATION_THRESHOLD can be customised."""
        settings = _make_settings_from_env({"ROTATION_THRESHOLD": "0.75"})
        assert settings.ROTATION_THRESHOLD == 0.75  # type: ignore[attr-defined]

    def test_production_env_default(self) -> None:
        """Default ENV value is 'production' when ENV is not set."""
        from core.config import Settings
        env = {k: v for k, v in _VALID_ENV.items() if k != "ENV"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()
        assert settings.ENV == "production"

    def test_telegram_admin_uid_integer(self) -> None:
        """TELEGRAM_ADMIN_UID is stored as an int."""
        settings = _make_settings_from_env({"TELEGRAM_ADMIN_UID": "12345"})
        assert settings.TELEGRAM_ADMIN_UID == 12345  # type: ignore[attr-defined]
        assert isinstance(settings.TELEGRAM_ADMIN_UID, int)  # type: ignore[attr-defined]

    def test_internal_api_url_default_empty(self) -> None:
        """INTERNAL_API_URL defaults to empty string."""
        settings = _make_settings_from_env()
        assert settings.INTERNAL_API_URL == ""  # type: ignore[attr-defined]

    def test_allowed_origins_default_empty(self) -> None:
        """ALLOWED_ORIGINS defaults to empty list."""
        settings = _make_settings_from_env()
        assert settings.ALLOWED_ORIGINS == []  # type: ignore[attr-defined]
