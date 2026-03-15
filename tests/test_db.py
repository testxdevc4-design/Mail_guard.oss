"""
tests/test_db.py — Part 03 database helper tests.

All Supabase interactions are mocked so that these tests run in CI
without a live Supabase instance.  Each test verifies that:
  - the correct table is targeted
  - the correct operation (insert / select / update) is invoked
  - the returned model is properly populated from the Supabase response
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch


# Set required env vars before importing any app modules
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")

import core.db as db_module  # noqa: E402
from core.models import (  # noqa: E402
    ApiKey,
    EmailLog,
    MagicLink,
    OtpRecord,
    Project,
    SenderEmail,
    Webhook,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

NOW = "2024-01-15T10:00:00+00:00"
UUID1 = "00000000-0000-0000-0000-000000000001"
UUID2 = "00000000-0000-0000-0000-000000000002"


def _mock_client() -> MagicMock:
    """Return a fresh MagicMock that mimics the supabase Client interface."""
    client = MagicMock()
    # Make every chained call return the client itself so we can configure
    # the terminal .execute() easily.
    client.table.return_value = client
    client.insert.return_value = client
    client.select.return_value = client
    client.update.return_value = client
    client.eq.return_value = client
    client.maybe_single.return_value = client
    client.order.return_value = client
    client.limit.return_value = client
    return client


def _exec(client: MagicMock, data: Any) -> None:
    """Set the return value of client.execute() to a mock with .data = data."""
    result = MagicMock()
    result.data = data
    client.execute.return_value = result


# ---------------------------------------------------------------------------
# sender_emails
# ---------------------------------------------------------------------------

SENDER_ROW = {
    "id": UUID1,
    "email_address": "sender@example.com",
    "display_name": "Test Sender",
    "provider": "custom",
    "smtp_host": "smtp.example.com",
    "smtp_port": 465,
    "app_password_enc": "enc_password",
    "daily_limit": 500,
    "daily_sent": 10,
    "last_reset_at": NOW,
    "is_active": True,
    "created_at": NOW,
    "updated_at": NOW,
}


class TestSenderEmails:
    def test_insert(self) -> None:
        client = _mock_client()
        _exec(client, [SENDER_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.insert_sender_email({"email_address": "sender@example.com"})
        client.table.assert_called_with("sender_emails")
        client.insert.assert_called_once()
        assert isinstance(result, SenderEmail)
        assert result.email_address == "sender@example.com"

    def test_get_by_id(self) -> None:
        client = _mock_client()
        _exec(client, SENDER_ROW)
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_sender_email(UUID1)
        client.table.assert_called_with("sender_emails")
        client.eq.assert_called_with("id", UUID1)
        assert result is not None
        assert result.id == UUID1

    def test_get_returns_none_when_not_found(self) -> None:
        client = _mock_client()
        _exec(client, None)
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_sender_email("nonexistent")
        assert result is None

    def test_list(self) -> None:
        client = _mock_client()
        _exec(client, [SENDER_ROW, SENDER_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.list_sender_emails()
        assert len(result) == 2
        assert all(isinstance(r, SenderEmail) for r in result)

    def test_update(self) -> None:
        updated = {**SENDER_ROW, "daily_sent": 20}
        client = _mock_client()
        _exec(client, [updated])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.update_sender_email(UUID1, {"daily_sent": 20})
        client.table.assert_called_with("sender_emails")
        client.update.assert_called_once()
        assert result.daily_sent == 20


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

PROJECT_ROW = {
    "id": UUID1,
    "name": "Test Project",
    "slug": "test-project",
    "sender_email_id": UUID2,
    "otp_length": 6,
    "otp_expiry_seconds": 300,
    "otp_max_attempts": 5,
    "rate_limit_per_hour": 10,
    "template_subject": "Your OTP",
    "template_body_text": "Code: {{otp_code}}",
    "template_body_html": "",
    "is_active": True,
    "created_at": NOW,
    "updated_at": NOW,
}


class TestProjects:
    def test_insert(self) -> None:
        client = _mock_client()
        _exec(client, [PROJECT_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.insert_project({"name": "Test Project", "slug": "test-project"})
        client.table.assert_called_with("projects")
        assert isinstance(result, Project)
        assert result.slug == "test-project"

    def test_get_by_id(self) -> None:
        client = _mock_client()
        _exec(client, PROJECT_ROW)
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_project(UUID1)
        assert result is not None
        assert result.id == UUID1

    def test_get_by_slug(self) -> None:
        client = _mock_client()
        _exec(client, PROJECT_ROW)
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_project_by_slug("test-project")
        client.eq.assert_called_with("slug", "test-project")
        assert result is not None

    def test_list(self) -> None:
        client = _mock_client()
        _exec(client, [PROJECT_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.list_projects()
        assert len(result) == 1

    def test_update(self) -> None:
        updated = {**PROJECT_ROW, "name": "Renamed"}
        client = _mock_client()
        _exec(client, [updated])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.update_project(UUID1, {"name": "Renamed"})
        assert result.name == "Renamed"


# ---------------------------------------------------------------------------
# api_keys
# ---------------------------------------------------------------------------

API_KEY_ROW = {
    "id": UUID1,
    "project_id": UUID2,
    "key_hash": "abc123",
    "key_prefix": "mg_live_",
    "label": "prod key",
    "is_sandbox": False,
    "is_active": True,
    "last_used_at": None,
    "created_at": NOW,
}


class TestApiKeys:
    def test_insert(self) -> None:
        client = _mock_client()
        _exec(client, [API_KEY_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.insert_api_key({"project_id": UUID2, "key_hash": "abc123", "key_prefix": "mg_live_"})
        client.table.assert_called_with("api_keys")
        assert isinstance(result, ApiKey)

    def test_get_by_hash(self) -> None:
        client = _mock_client()
        _exec(client, API_KEY_ROW)
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_api_key_by_hash("abc123")
        client.eq.assert_called_with("key_hash", "abc123")
        assert result is not None

    def test_list(self) -> None:
        client = _mock_client()
        _exec(client, [API_KEY_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.list_api_keys(UUID2)
        assert len(result) == 1

    def test_update(self) -> None:
        updated = {**API_KEY_ROW, "is_active": False}
        client = _mock_client()
        _exec(client, [updated])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.update_api_key(UUID1, {"is_active": False})
        assert result.is_active is False


# ---------------------------------------------------------------------------
# otp_records
# ---------------------------------------------------------------------------

OTP_ROW = {
    "id": UUID1,
    "project_id": UUID2,
    "email_hash": "emailhashvalue",
    "otp_hash": "otphashvalue",
    "purpose": "login",
    "attempt_count": 0,
    "otp_max_attempts": 5,
    "is_verified": False,
    "is_invalidated": False,
    "expires_at": NOW,
    "created_at": NOW,
}


class TestOtpRecords:
    def test_insert(self) -> None:
        client = _mock_client()
        _exec(client, [OTP_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.insert_otp_record({"project_id": UUID2, "email_hash": "emailhashvalue", "otp_hash": "otphashvalue", "expires_at": NOW})
        client.table.assert_called_with("otp_records")
        assert isinstance(result, OtpRecord)

    def test_get_by_id(self) -> None:
        client = _mock_client()
        _exec(client, OTP_ROW)
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_otp_record(UUID1)
        assert result is not None
        assert result.email_hash == "emailhashvalue"

    def test_get_active_otp(self) -> None:
        client = _mock_client()
        _exec(client, [OTP_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_active_otp(UUID2, "emailhashvalue")
        assert result is not None

    def test_update(self) -> None:
        updated = {**OTP_ROW, "attempt_count": 1}
        client = _mock_client()
        _exec(client, [updated])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.update_otp_record(UUID1, {"attempt_count": 1})
        assert result.attempt_count == 1


# ---------------------------------------------------------------------------
# magic_links
# ---------------------------------------------------------------------------

MAGIC_ROW = {
    "id": UUID1,
    "project_id": UUID2,
    "email_hash": "emailhash",
    "token_hash": "tokenhash",
    "purpose": "login",
    "redirect_url": "https://example.com/callback",
    "is_used": False,
    "expires_at": NOW,
    "created_at": NOW,
}


class TestMagicLinks:
    def test_insert(self) -> None:
        client = _mock_client()
        _exec(client, [MAGIC_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.insert_magic_link({"project_id": UUID2, "email_hash": "emailhash", "token_hash": "tokenhash", "expires_at": NOW})
        client.table.assert_called_with("magic_links")
        assert isinstance(result, MagicLink)

    def test_get_by_token_hash(self) -> None:
        client = _mock_client()
        _exec(client, MAGIC_ROW)
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_magic_link_by_token_hash("tokenhash")
        client.eq.assert_called_with("token_hash", "tokenhash")
        assert result is not None

    def test_update(self) -> None:
        updated = {**MAGIC_ROW, "is_used": True}
        client = _mock_client()
        _exec(client, [updated])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.update_magic_link(UUID1, {"is_used": True})
        assert result.is_used is True


# ---------------------------------------------------------------------------
# webhooks
# ---------------------------------------------------------------------------

WEBHOOK_ROW = {
    "id": UUID1,
    "project_id": UUID2,
    "url": "https://example.com/webhook",
    "secret_enc": "enc_secret",
    "events": ["otp.sent", "otp.verified"],
    "is_active": True,
    "failure_count": 0,
    "last_triggered_at": None,
    "created_at": NOW,
}


class TestWebhooks:
    def test_insert(self) -> None:
        client = _mock_client()
        _exec(client, [WEBHOOK_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.insert_webhook({"project_id": UUID2, "url": "https://example.com/webhook", "secret_enc": "enc_secret"})
        client.table.assert_called_with("webhooks")
        assert isinstance(result, Webhook)
        assert result.events == ["otp.sent", "otp.verified"]

    def test_get_by_id(self) -> None:
        client = _mock_client()
        _exec(client, WEBHOOK_ROW)
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_webhook(UUID1)
        assert result is not None

    def test_list(self) -> None:
        client = _mock_client()
        _exec(client, [WEBHOOK_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.list_webhooks(UUID2)
        assert len(result) == 1

    def test_update(self) -> None:
        updated = {**WEBHOOK_ROW, "failure_count": 1}
        client = _mock_client()
        _exec(client, [updated])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.update_webhook(UUID1, {"failure_count": 1})
        assert result.failure_count == 1


# ---------------------------------------------------------------------------
# email_logs
# ---------------------------------------------------------------------------

EMAIL_LOG_ROW = {
    "id": UUID1,
    "project_id": UUID2,
    "sender_id": UUID2,
    "recipient_hash": "recipienthash",
    "purpose": "login",
    "type": "otp",
    "status": "sent",
    "error_detail": None,
    "sent_at": NOW,
}


class TestEmailLogs:
    def test_insert(self) -> None:
        client = _mock_client()
        _exec(client, [EMAIL_LOG_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.insert_email_log({
                "project_id": UUID2,
                "sender_id": UUID2,
                "recipient_hash": "recipienthash",
                "purpose": "login",
                "type": "otp",
                "status": "sent",
            })
        client.table.assert_called_with("email_logs")
        assert isinstance(result, EmailLog)
        assert result.status == "sent"

    def test_get_by_id(self) -> None:
        client = _mock_client()
        _exec(client, EMAIL_LOG_ROW)
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.get_email_log(UUID1)
        assert result is not None
        assert result.type == "otp"

    def test_list(self) -> None:
        client = _mock_client()
        _exec(client, [EMAIL_LOG_ROW, EMAIL_LOG_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.list_email_logs(project_id=UUID2)
        assert len(result) == 2

    def test_list_by_status(self) -> None:
        client = _mock_client()
        _exec(client, [EMAIL_LOG_ROW])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.list_email_logs(status="sent")
        assert all(r.status == "sent" for r in result)

    def test_update(self) -> None:
        updated = {**EMAIL_LOG_ROW, "status": "failed", "error_detail": "SMTP timeout"}
        client = _mock_client()
        _exec(client, [updated])
        with patch.object(db_module, "get_client", return_value=client):
            result = db_module.update_email_log(UUID1, {"status": "failed"})
        assert result.status == "failed"
        assert result.error_detail == "SMTP timeout"
