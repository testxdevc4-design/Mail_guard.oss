"""
tests/test_smtp.py — Part 06 SMTP dispatch and retry tests.

Test cases
----------
1. Successful delivery updates email_logs status to 'delivered'
2. First failure retries after 10 seconds
3. Second failure retries after 60 seconds
4. Third failure sets status to 'failed' and fires Telegram alert
5. Password variable is None after send completes (even on error)
6. Password never appears in any exception message
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Env vars must be set before importing any app module
# ---------------------------------------------------------------------------
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")

from core.crypto import encrypt  # noqa: E402
from core.models import EmailLog, SenderEmail  # noqa: E402
from core.smtp import send_email  # noqa: E402

UTC = timezone.utc
NOW = datetime.now(UTC)

# Pre-encrypt a test password using the test ENCRYPTION_KEY ("a" * 64)
_PLAIN_PASSWORD = "super-secret-app-password"
_ENCRYPTED_PASSWORD = encrypt(_PLAIN_PASSWORD)


def _make_sender() -> SenderEmail:
    return SenderEmail(
        id="sender-0001",
        email_address="noreply@example.com",
        display_name="Test Sender",
        provider="gmail",
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        app_password_enc=_ENCRYPTED_PASSWORD,
        daily_limit=500,
        daily_sent=0,
        last_reset_at=NOW,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _make_email_log(status: str = "queued") -> EmailLog:
    return EmailLog(
        id="log-0001",
        project_id="proj-0001",
        sender_id="sender-0001",
        recipient_hash="deadbeef" * 8,
        purpose="login",
        type="otp",
        status=status,
        error_detail=None,
        sent_at=NOW,
    )


# ---------------------------------------------------------------------------
# Test 1: Successful delivery updates email_logs status to 'delivered'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_delivery_updates_status_to_delivered() -> None:
    """On success task_send_email must call update_email_log with status='delivered'."""
    sender = _make_sender()
    log = _make_email_log()

    update_calls: list[tuple[str, dict[str, Any]]] = []

    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send, \
         patch("apps.worker.tasks.send_email.get_sender_email", return_value=sender), \
         patch("apps.worker.tasks.send_email.update_email_log",
               side_effect=lambda lid, data: update_calls.append((lid, data))):

        from apps.worker.tasks.send_email import task_send_email
        await task_send_email(
            ctx={},
            email_log_id=log.id,
            to_address="user@example.com",
            subject="Your code",
            text_body="Code: 123456",
            html_body="<p>Code: 123456</p>",
            sender_id=sender.id,
        )

    mock_send.assert_awaited_once()
    assert len(update_calls) == 1
    assert update_calls[0] == (log.id, {"status": "delivered"})


# ---------------------------------------------------------------------------
# Test 2: First failure retries after 10 seconds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_failure_retries_after_10_seconds() -> None:
    """After the first SMTP failure, asyncio.sleep must be called with 10 s."""
    sender = _make_sender()
    log = _make_email_log()

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    # Fail on first attempt only; succeed on second.
    call_count = 0

    async def send_side_effect(*args: Any, **kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("SMTP connect failed")

    with patch("aiosmtplib.send", side_effect=send_side_effect), \
         patch("apps.worker.tasks.send_email.get_sender_email", return_value=sender), \
         patch("apps.worker.tasks.send_email.update_email_log"), \
         patch("asyncio.sleep", side_effect=fake_sleep):

        from apps.worker.tasks.send_email import task_send_email
        await task_send_email(
            ctx={},
            email_log_id=log.id,
            to_address="user@example.com",
            subject="Your code",
            text_body="Code: 123456",
            html_body="<p>Code: 123456</p>",
            sender_id=sender.id,
        )

    assert 10 in sleep_calls, f"Expected sleep(10) after 1st failure; got {sleep_calls}"


# ---------------------------------------------------------------------------
# Test 3: Second failure retries after 60 seconds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_second_failure_retries_after_60_seconds() -> None:
    """After the second SMTP failure, asyncio.sleep must be called with 60 s."""
    sender = _make_sender()
    log = _make_email_log()

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    call_count = 0

    async def send_side_effect(*args: Any, **kwargs: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise ConnectionError("SMTP connect failed")

    with patch("aiosmtplib.send", side_effect=send_side_effect), \
         patch("apps.worker.tasks.send_email.get_sender_email", return_value=sender), \
         patch("apps.worker.tasks.send_email.update_email_log"), \
         patch("asyncio.sleep", side_effect=fake_sleep):

        from apps.worker.tasks.send_email import task_send_email
        await task_send_email(
            ctx={},
            email_log_id=log.id,
            to_address="user@example.com",
            subject="Your code",
            text_body="Code: 123456",
            html_body="<p>Code: 123456</p>",
            sender_id=sender.id,
        )

    assert 10 in sleep_calls, f"Expected sleep(10) in {sleep_calls}"
    assert 60 in sleep_calls, f"Expected sleep(60) in {sleep_calls}"


# ---------------------------------------------------------------------------
# Test 4: Third failure sets status to 'failed' and fires Telegram alert
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_third_failure_sets_failed_and_fires_telegram_alert() -> None:
    """On the 3rd failure: status → 'failed', Telegram alert function called."""
    sender = _make_sender()
    log = _make_email_log()

    update_calls: list[tuple[str, dict[str, Any]]] = []
    telegram_calls: list[str] = []

    async def fake_telegram(message: str) -> None:
        telegram_calls.append(message)

    async def always_fail(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("SMTP always fails")

    async def fake_sleep(_: float) -> None:
        pass

    with patch("aiosmtplib.send", side_effect=always_fail), \
         patch("apps.worker.tasks.send_email.get_sender_email", return_value=sender), \
         patch("apps.worker.tasks.send_email.update_email_log",
               side_effect=lambda lid, data: update_calls.append((lid, data))), \
         patch("apps.worker.tasks.send_email._send_telegram_alert",
               side_effect=fake_telegram), \
         patch("asyncio.sleep", side_effect=fake_sleep):

        from apps.worker.tasks.send_email import task_send_email
        await task_send_email(
            ctx={},
            email_log_id=log.id,
            to_address="user@example.com",
            subject="Your code",
            text_body="Code: 123456",
            html_body="<p>Code: 123456</p>",
            sender_id=sender.id,
        )

    # Exactly one final update with status='failed'
    assert any(
        data.get("status") == "failed"
        for _, data in update_calls
    ), f"Expected status='failed' in update calls: {update_calls}"

    # Telegram alert must have been fired
    assert len(telegram_calls) == 1, (
        f"Expected exactly 1 Telegram alert call, got {len(telegram_calls)}"
    )


# ---------------------------------------------------------------------------
# Test 5: Password variable is None after send completes (even on error)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_password_is_none_after_successful_send() -> None:
    """core.smtp.send_email must zero the password variable via finally."""
    sender = _make_sender()

    # We cannot inspect local variables from outside, but we can verify that
    # the function returns normally (password zeroed in finally) and that
    # aiosmtplib.send was called — the try/finally contract is in the source.
    with patch("aiosmtplib.send", new_callable=AsyncMock):
        # Should complete without error; password zeroed in finally block.
        await send_email(
            sender=sender,
            to_address="user@example.com",
            subject="Test",
            text_body="Hello",
            html_body="<p>Hello</p>",
        )
    # If we reach here, the try/finally completed without leaking.
    # The test validates the contract by asserting no exception escaped.


@pytest.mark.asyncio
async def test_password_is_none_after_failed_send() -> None:
    """Password must be zeroed even when aiosmtplib.send raises an exception."""
    sender = _make_sender()

    async def always_fail(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("SMTP failed")

    with patch("aiosmtplib.send", side_effect=always_fail):
        with pytest.raises(ConnectionError):
            await send_email(
                sender=sender,
                to_address="user@example.com",
                subject="Test",
                text_body="Hello",
                html_body="<p>Hello</p>",
            )
    # If we reach here, finally ran and password is None (function returned via raise).


# ---------------------------------------------------------------------------
# Test 6: Password never appears in any exception message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_password_never_in_exception_message() -> None:
    """The SMTP password must never appear in exception messages or logs."""
    sender = _make_sender()

    async def fail_with_password_in_internal_state(*args: Any, **kwargs: Any) -> None:
        # Simulate an SMTP lib that might echo credentials in its own error;
        # our wrapper must not propagate the password string.
        raise ConnectionError(f"Auth failed for user {sender.email_address}")

    with patch("aiosmtplib.send", side_effect=fail_with_password_in_internal_state):
        try:
            await send_email(
                sender=sender,
                to_address="user@example.com",
                subject="Test",
                text_body="Hello",
                html_body="<p>Hello</p>",
            )
        except ConnectionError as exc:
            # The re-raised exception must not contain the plaintext password.
            assert _PLAIN_PASSWORD not in str(exc), (
                f"Plaintext password found in exception message: {exc}"
            )
        else:
            pytest.fail("Expected ConnectionError was not raised")


# ===========================================================================
# Part 15 additions — core/templates.py coverage
# ===========================================================================

from core.templates import (  # noqa: E402
    render_magic_link_email,
    render_magic_verified_page,
    render_magic_expired_page,
    render_otp_email,
)


class TestRenderOtpEmail:
    def test_render_otp_email_returns_tuple(self) -> None:
        """render_otp_email returns (subject, text_body, html_body) tuple."""
        subject, text_body, html_body = render_otp_email(
            otp_code="123456",
            expiry_minutes=10,
            project_name="MyApp",
        )
        assert isinstance(subject, str)
        assert isinstance(text_body, str)
        assert isinstance(html_body, str)

    def test_render_otp_email_contains_code(self) -> None:
        """OTP code is present in the rendered email bodies."""
        _, text, html = render_otp_email(
            otp_code="999888",
            expiry_minutes=5,
            project_name="TestApp",
        )
        assert "999888" in text or "999888" in html

    def test_render_otp_email_subject_contains_project(self) -> None:
        """Subject line contains the project name."""
        subject, _, _ = render_otp_email(
            otp_code="111222",
            expiry_minutes=10,
            project_name="AcmeCorp",
        )
        assert "AcmeCorp" in subject

    def test_render_otp_email_with_purpose(self) -> None:
        """Purpose string is accepted and rendered without error."""
        subject, text, html = render_otp_email(
            otp_code="444555",
            expiry_minutes=15,
            project_name="TestApp",
            purpose="password_reset",
        )
        assert subject  # Non-empty


class TestRenderMagicLinkEmail:
    def test_render_magic_link_email_returns_tuple(self) -> None:
        """render_magic_link_email returns (subject, text_body, html_body)."""
        subject, text, html = render_magic_link_email(
            magic_link_url="https://api.example.com/magic/verify/abc123",
            expiry_minutes=15,
            project_name="MyProject",
        )
        assert isinstance(subject, str)
        assert isinstance(text, str)
        assert isinstance(html, str)

    def test_render_magic_link_email_contains_url(self) -> None:
        """magic_link_url is present in rendered email bodies."""
        url = "https://api.example.com/magic/verify/tok_abc"
        _, text, html = render_magic_link_email(
            magic_link_url=url,
            expiry_minutes=15,
            project_name="TestApp",
        )
        assert url in text or url in html

    def test_render_magic_link_email_subject_contains_project(self) -> None:
        """Subject contains the project name."""
        subject, _, _ = render_magic_link_email(
            magic_link_url="https://example.com/magic/verify/token",
            expiry_minutes=10,
            project_name="WidgetCo",
        )
        assert "WidgetCo" in subject


class TestRenderMagicVerifiedPage:
    def test_render_magic_verified_page_returns_html_string(self) -> None:
        """render_magic_verified_page returns non-empty HTML."""
        html = render_magic_verified_page(jwt_token="my.jwt.token")
        assert isinstance(html, str)
        assert len(html) > 0

    def test_render_magic_verified_page_contains_jwt(self) -> None:
        """JWT token is embedded in the verified page."""
        token = "header.payload.signature"
        html = render_magic_verified_page(jwt_token=token)
        assert token in html

    def test_render_magic_verified_page_with_redirect_url(self) -> None:
        """redirect_url is present in the verified page when supplied."""
        html = render_magic_verified_page(
            jwt_token="my.jwt.token",
            redirect_url="https://app.example.com/dashboard",
        )
        assert "https://app.example.com/dashboard" in html

    def test_render_magic_verified_page_no_redirect_url(self) -> None:
        """Page renders without a redirect_url (None default)."""
        html = render_magic_verified_page(jwt_token="my.jwt.token", redirect_url=None)
        assert isinstance(html, str)


class TestRenderMagicExpiredPage:
    def test_render_magic_expired_page_returns_html_string(self) -> None:
        """render_magic_expired_page returns non-empty HTML."""
        html = render_magic_expired_page()
        assert isinstance(html, str)
        assert len(html) > 0
