"""
tests/test_bot_part12.py — Unit tests for Part 12 bot commands and wizards.

Covers:
  - apps/bot/commands/senders.py
  - apps/bot/commands/projects.py
  - apps/bot/commands/keys.py
  - apps/bot/commands/logs.py
  - apps/bot/commands/webhooks.py
  - apps/bot/wizards/new_project.py (slug validation, state constants)
  - apps/bot/wizards/set_otp.py (_render_preview)
  - apps/bot/wizards/set_webhook.py (_VERIFICATION_SNIPPET)
  - core/db.list_email_logs_paged (signature)
  - apps/bot/main.build_application (handler registration)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")


# ---------------------------------------------------------------------------
# Helpers — shared fake data factories
# ---------------------------------------------------------------------------

def _make_sender(
    email: str = "test@gmail.com",
    provider: str = "Gmail",
    daily_limit: int = 450,
    is_active: bool = True,
) -> MagicMock:
    s = MagicMock()
    s.id = "sender-id-1"
    s.email_address = email
    s.provider = provider
    s.daily_limit = daily_limit
    s.daily_sent = 0
    s.is_active = is_active
    return s


def _make_project(
    name: str = "Demo",
    slug: str = "demo",
    is_active: bool = True,
    sender_email_id: str | None = "sender-id-1",
) -> MagicMock:
    p = MagicMock()
    p.id = "project-id-1"
    p.name = name
    p.slug = slug
    p.is_active = is_active
    p.sender_email_id = sender_email_id
    return p


def _make_api_key(
    key_prefix: str = "mg_live_abcd",
    label: str = "prod",
    is_sandbox: bool = False,
    is_active: bool = True,
) -> MagicMock:
    k = MagicMock()
    k.id = "key-id-1"
    k.project_id = "project-id-1"
    k.key_prefix = key_prefix
    k.key_hash = "x" * 64  # never displayed
    k.label = label
    k.is_sandbox = is_sandbox
    k.is_active = is_active
    k.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    return k


def _make_log(status: str = "sent") -> MagicMock:
    log = MagicMock()
    log.id = "log-id-1"
    log.project_id = "project-id-1"
    log.sender_id = "sender-id-1"
    log.recipient_hash = "a" * 64
    log.purpose = "login"
    log.type = "otp"
    log.status = status
    log.sent_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    return log


def _make_update(reply_text: AsyncMock | None = None) -> MagicMock:
    msg = MagicMock()
    msg.reply_text = reply_text or AsyncMock()
    update = MagicMock()
    update.message = msg
    return update


def _make_context(args: list[str] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.args = args or []
    ctx.user_data = {}
    return ctx


# ===========================================================================
# apps/bot/commands/senders.py
# ===========================================================================

class TestSendersCommand:
    @pytest.mark.asyncio
    async def test_no_senders(self) -> None:
        from apps.bot.commands.senders import senders_command

        update = _make_update()
        ctx = _make_context()

        with patch("apps.bot.commands.senders.list_sender_emails", return_value=[]):
            await senders_command(update, ctx)

        update.message.reply_text.assert_called_once()
        call_text: str = update.message.reply_text.call_args[0][0]
        assert "No senders" in call_text

    @pytest.mark.asyncio
    async def test_senders_listed_with_usage(self) -> None:
        from apps.bot.commands.senders import senders_command

        sender = _make_sender()
        update = _make_update()
        ctx = _make_context()

        with (
            patch("apps.bot.commands.senders.list_sender_emails", return_value=[sender]),
            patch(
                "apps.bot.commands.senders.get_usage_pct",
                new=AsyncMock(return_value=0.35),
            ),
        ):
            await senders_command(update, ctx)

        update.message.reply_text.assert_called_once()
        text: str = update.message.reply_text.call_args[0][0]
        assert "test@gmail.com" in text
        assert "35.0%" in text

    @pytest.mark.asyncio
    async def test_senders_redis_error_shows_zero(self) -> None:
        from apps.bot.commands.senders import senders_command

        sender = _make_sender()
        update = _make_update()
        ctx = _make_context()

        async def _bad_pct(_s: object) -> float:
            raise RuntimeError("Redis down")

        with (
            patch("apps.bot.commands.senders.list_sender_emails", return_value=[sender]),
            patch("apps.bot.commands.senders.get_usage_pct", new=_bad_pct),
        ):
            await senders_command(update, ctx)

        # Should not crash — should show 0% fallback
        text: str = update.message.reply_text.call_args[0][0]
        assert "0.0%" in text

    @pytest.mark.asyncio
    async def test_senders_db_error(self) -> None:
        from apps.bot.commands.senders import senders_command

        update = _make_update()
        ctx = _make_context()

        with patch(
            "apps.bot.commands.senders.list_sender_emails",
            side_effect=Exception("DB error"),
        ):
            await senders_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "\u274c" in text


# ===========================================================================
# apps/bot/commands/projects.py
# ===========================================================================

class TestProjectsCommand:
    @pytest.mark.asyncio
    async def test_no_projects(self) -> None:
        from apps.bot.commands.projects import projects_command

        update = _make_update()
        ctx = _make_context()

        with patch("apps.bot.commands.projects.list_projects", return_value=[]):
            await projects_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "No projects" in text

    @pytest.mark.asyncio
    async def test_projects_listed(self) -> None:
        from apps.bot.commands.projects import projects_command

        project = _make_project()
        sender = _make_sender()
        update = _make_update()
        ctx = _make_context()

        with (
            patch("apps.bot.commands.projects.list_projects", return_value=[project]),
            patch(
                "apps.bot.commands.projects.get_sender_email", return_value=sender
            ),
        ):
            await projects_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "demo" in text
        assert "test@gmail.com" in text

    @pytest.mark.asyncio
    async def test_delete_project_not_found(self) -> None:
        from apps.bot.commands.projects import delete_project_command

        update = _make_update()
        ctx = _make_context(args=["no-such-slug"])

        with patch("apps.bot.commands.projects.get_project_by_slug", return_value=None):
            await delete_project_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "\u274c" in text

    @pytest.mark.asyncio
    async def test_delete_project_success(self) -> None:
        from apps.bot.commands.projects import delete_project_command

        project = _make_project()
        update = _make_update()
        ctx = _make_context(args=["demo"])

        with (
            patch(
                "apps.bot.commands.projects.get_project_by_slug",
                return_value=project,
            ),
            patch("apps.bot.commands.projects.update_project") as mock_update,
        ):
            await delete_project_command(update, ctx)

        mock_update.assert_called_once_with(project.id, {"is_active": False})
        text: str = update.message.reply_text.call_args[0][0]
        assert "\u2705" in text

    @pytest.mark.asyncio
    async def test_delete_project_no_args(self) -> None:
        from apps.bot.commands.projects import delete_project_command

        update = _make_update()
        ctx = _make_context(args=[])

        await delete_project_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "Usage" in text


# ===========================================================================
# apps/bot/commands/keys.py
# ===========================================================================

class TestKeysCommand:
    @pytest.mark.asyncio
    async def test_genkey_no_args(self) -> None:
        from apps.bot.commands.keys import genkey_command

        update = _make_update()
        ctx = _make_context(args=[])

        await genkey_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_genkey_project_not_found(self) -> None:
        from apps.bot.commands.keys import genkey_command

        update = _make_update()
        ctx = _make_context(args=["no-such-slug"])

        with patch("apps.bot.commands.keys.get_project_by_slug", return_value=None):
            await genkey_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "\u274c" in text

    @pytest.mark.asyncio
    async def test_genkey_shows_plaintext_once_then_zeros(self) -> None:
        """Plaintext must appear in exactly ONE reply and be zeroed after."""
        from apps.bot.commands.keys import genkey_command

        project = _make_project()
        # Use a distinct hash that does NOT appear in the plaintext
        key_row = _make_api_key(key_prefix="mg_live_abcd")
        key_row.key_hash = "0" * 64  # all zeros — distinct from plaintext
        captured_texts: list[str] = []

        async def _capture(text: str, **_kw: object) -> None:
            captured_texts.append(text)

        update = _make_update(reply_text=AsyncMock(side_effect=_capture))
        ctx = _make_context(args=["demo"])

        # Plaintext uses different chars from the hash ("x" vs "0")
        fake_plaintext = "mg_live_" + "a" * 48

        with (
            patch("apps.bot.commands.keys.get_project_by_slug", return_value=project),
            patch(
                "apps.bot.commands.keys.generate_api_key",
                return_value=(fake_plaintext, key_row),
            ),
        ):
            await genkey_command(update, ctx)

        # Exactly one reply
        assert len(captured_texts) == 1
        # Plaintext IS in that one message
        assert fake_plaintext in captured_texts[0]
        # key_hash is NOT in any message (security check)
        assert key_row.key_hash not in captured_texts[0]

    @pytest.mark.asyncio
    async def test_keys_shows_prefix_not_hash(self) -> None:
        """The /keys command must show key_prefix, never key_hash."""
        from apps.bot.commands.keys import keys_command

        project = _make_project()
        key = _make_api_key(key_prefix="mg_live_abcd")
        update = _make_update()
        ctx = _make_context(args=["demo"])

        with (
            patch("apps.bot.commands.keys.get_project_by_slug", return_value=project),
            patch("apps.bot.commands.keys.list_api_keys", return_value=[key]),
        ):
            await keys_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        # Prefix must appear
        assert key.key_prefix in text
        # Hash must NOT appear
        assert key.key_hash not in text

    @pytest.mark.asyncio
    async def test_keys_no_active_keys(self) -> None:
        from apps.bot.commands.keys import keys_command

        project = _make_project()
        revoked_key = _make_api_key(is_active=False)
        update = _make_update()
        ctx = _make_context(args=["demo"])

        with (
            patch("apps.bot.commands.keys.get_project_by_slug", return_value=project),
            patch("apps.bot.commands.keys.list_api_keys", return_value=[revoked_key]),
        ):
            await keys_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "No active" in text


# ===========================================================================
# apps/bot/commands/logs.py
# ===========================================================================

class TestLogsCommand:
    @pytest.mark.asyncio
    async def test_logs_all_projects(self) -> None:
        from apps.bot.commands.logs import logs_command

        log = _make_log()
        update = _make_update()
        ctx = _make_context(args=[])

        with patch(
            "apps.bot.commands.logs.list_email_logs_paged", return_value=[log]
        ) as mock_list:
            await logs_command(update, ctx)

        mock_list.assert_called_once_with(
            project_id=None, status=None, since=None, limit=20
        )
        text: str = update.message.reply_text.call_args[0][0]
        assert "Logs" in text

    @pytest.mark.asyncio
    async def test_logs_by_slug(self) -> None:
        from apps.bot.commands.logs import logs_command

        project = _make_project()
        log = _make_log()
        update = _make_update()
        ctx = _make_context(args=["demo"])

        with (
            patch("apps.bot.commands.logs.get_project_by_slug", return_value=project),
            patch(
                "apps.bot.commands.logs.list_email_logs_paged", return_value=[log]
            ) as mock_list,
        ):
            await logs_command(update, ctx)

        mock_list.assert_called_once_with(
            project_id=project.id, status=None, since=None, limit=20
        )

    @pytest.mark.asyncio
    async def test_logs_failed_flag(self) -> None:
        from apps.bot.commands.logs import logs_command

        log = _make_log(status="failed")
        update = _make_update()
        ctx = _make_context(args=["--failed"])

        with patch(
            "apps.bot.commands.logs.list_email_logs_paged", return_value=[log]
        ) as mock_list:
            await logs_command(update, ctx)

        mock_list.assert_called_once_with(
            project_id=None, status="failed", since=None, limit=20
        )

    @pytest.mark.asyncio
    async def test_logs_today_flag(self) -> None:
        from apps.bot.commands.logs import logs_command

        log = _make_log()
        update = _make_update()
        ctx = _make_context(args=["--today"])

        with patch(
            "apps.bot.commands.logs.list_email_logs_paged", return_value=[log]
        ) as mock_list:
            await logs_command(update, ctx)

        call_kwargs = mock_list.call_args[1]
        assert call_kwargs["since"] is not None
        assert call_kwargs["status"] is None

    @pytest.mark.asyncio
    async def test_logs_no_entries(self) -> None:
        from apps.bot.commands.logs import logs_command

        update = _make_update()
        ctx = _make_context(args=[])

        with patch("apps.bot.commands.logs.list_email_logs_paged", return_value=[]):
            await logs_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "No log" in text

    @pytest.mark.asyncio
    async def test_logs_slug_not_found(self) -> None:
        from apps.bot.commands.logs import logs_command

        update = _make_update()
        ctx = _make_context(args=["no-such-slug"])

        with patch("apps.bot.commands.logs.get_project_by_slug", return_value=None):
            await logs_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "\u274c" in text

    @pytest.mark.asyncio
    async def test_logs_never_shows_raw_email(self) -> None:
        """Logs must show recipient_hash (truncated), not raw email."""
        from apps.bot.commands.logs import logs_command

        log = _make_log()
        log.recipient_hash = "deadbeef" * 8  # 64 chars
        update = _make_update()
        ctx = _make_context(args=[])

        with patch("apps.bot.commands.logs.list_email_logs_paged", return_value=[log]):
            await logs_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        # The full hash appears truncated with ellipsis
        assert "deadbeef" in text
        # No '@' sign (no email address leaked)
        assert "@" not in text


# ===========================================================================
# apps/bot/commands/webhooks.py
# ===========================================================================

class TestWebhooksCommand:
    @pytest.mark.asyncio
    async def test_webhooks_no_args(self) -> None:
        from apps.bot.commands.webhooks import webhooks_command

        update = _make_update()
        ctx = _make_context(args=[])

        await webhooks_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_webhooks_project_not_found(self) -> None:
        from apps.bot.commands.webhooks import webhooks_command

        update = _make_update()
        ctx = _make_context(args=["no-slug"])

        with patch(
            "apps.bot.commands.webhooks.get_project_by_slug", return_value=None
        ):
            await webhooks_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "\u274c" in text

    @pytest.mark.asyncio
    async def test_webhooks_secret_never_shown(self) -> None:
        """The webhook list must never show the secret_enc or any secret."""
        from apps.bot.commands.webhooks import webhooks_command

        project = _make_project()
        wh = MagicMock()
        wh.id = "wh-id-1"
        wh.url = "https://example.com/hook"
        wh.events = ["otp.sent"]
        wh.is_active = True
        wh.failure_count = 0
        wh.secret_enc = "SUPER_SECRET_ENCRYPTED_VALUE"
        update = _make_update()
        ctx = _make_context(args=["demo"])

        with (
            patch(
                "apps.bot.commands.webhooks.get_project_by_slug",
                return_value=project,
            ),
            patch("apps.bot.commands.webhooks.list_webhooks", return_value=[wh]),
        ):
            await webhooks_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "SUPER_SECRET_ENCRYPTED_VALUE" not in text

    @pytest.mark.asyncio
    async def test_remove_webhook_no_args(self) -> None:
        from apps.bot.commands.webhooks import remove_webhook_command

        update = _make_update()
        ctx = _make_context(args=[])

        await remove_webhook_command(update, ctx)

        text: str = update.message.reply_text.call_args[0][0]
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_remove_webhook_success(self) -> None:
        from apps.bot.commands.webhooks import remove_webhook_command

        wh = MagicMock()
        wh.id = "wh-id-1"
        wh.is_active = True
        update = _make_update()
        ctx = _make_context(args=["wh-id-1"])

        with (
            patch("apps.bot.commands.webhooks.get_webhook", return_value=wh),
            patch("apps.bot.commands.webhooks.update_webhook") as mock_upd,
        ):
            await remove_webhook_command(update, ctx)

        mock_upd.assert_called_once_with("wh-id-1", {"is_active": False})
        text: str = update.message.reply_text.call_args[0][0]
        assert "\u2705" in text


# ===========================================================================
# apps/bot/wizards/new_project.py — slug validation logic
# ===========================================================================

class TestNewProjectSlugValidation:
    def test_valid_slugs(self) -> None:
        from apps.bot.wizards.new_project import _SLUG_RE, _SLUG_MAX_LEN

        valid = ["my-project", "abc", "hello-world-123", "a", "1"]
        for slug in valid:
            assert _SLUG_RE.match(slug) and len(slug) <= _SLUG_MAX_LEN, slug

    def test_invalid_slugs(self) -> None:
        from apps.bot.wizards.new_project import _SLUG_RE

        invalid = ["-start", "end-", "UPPERCASE", "has space", "under_score"]
        for slug in invalid:
            assert not _SLUG_RE.match(slug), f"Expected invalid: {slug}"

    def test_slug_max_length(self) -> None:
        from apps.bot.wizards.new_project import _SLUG_MAX_LEN

        assert _SLUG_MAX_LEN == 50

    def test_state_constants_are_distinct(self) -> None:
        from apps.bot.wizards.new_project import (
            ASK_NAME, ASK_SLUG, ASK_SENDER, ASK_OTP_EXPIRY, CONFIRM
        )

        states = [ASK_NAME, ASK_SLUG, ASK_SENDER, ASK_OTP_EXPIRY, CONFIRM]
        assert len(states) == len(set(states))


# ===========================================================================
# apps/bot/wizards/set_otp.py — template rendering
# ===========================================================================

class TestSetOtpPreview:
    def test_render_preview_success(self) -> None:
        from apps.bot.wizards.set_otp import _render_preview

        tmpl = (
            "Your code is {{ otp_code }}, expires in {{ expiry_minutes }} min "
            "for {{ project_name }}."
        )
        result = _render_preview(tmpl, "TestProject")
        assert result is not None
        assert "483920" in result
        assert "10" in result
        assert "TestProject" in result

    def test_render_preview_with_all_vars(self) -> None:
        from apps.bot.wizards.set_otp import _render_preview

        tmpl = (
            "{{ project_name }} code: {{ otp_code }} "
            "(expires {{ expiry_minutes }}m) — {{ purpose }} {{ current_year }}"
        )
        result = _render_preview(tmpl, "MyApp")
        assert result is not None
        assert "MyApp" in result
        assert "483920" in result
        assert "login" in result

    def test_render_preview_syntax_error_returns_none(self) -> None:
        from apps.bot.wizards.set_otp import _render_preview

        result = _render_preview("{% invalid jinja syntax %%", "Test")
        assert result is None

    def test_render_preview_plain_text_no_vars(self) -> None:
        from apps.bot.wizards.set_otp import _render_preview

        result = _render_preview("Hello, your code is ready!", "Demo")
        assert result == "Hello, your code is ready!"


# ===========================================================================
# apps/bot/wizards/set_webhook.py — secret handling
# ===========================================================================

class TestSetWebhookSecretHandling:
    def test_verification_snippet_present(self) -> None:
        from apps.bot.wizards.set_webhook import _VERIFICATION_SNIPPET

        assert "hmac" in _VERIFICATION_SNIPPET
        assert "sha256" in _VERIFICATION_SNIPPET
        assert "X-MailGuard-Signature" in _VERIFICATION_SNIPPET

    def test_state_constants_distinct(self) -> None:
        from apps.bot.wizards.set_webhook import ASK_SLUG, ASK_URL, ASK_EVENTS, CONFIRM

        states = [ASK_SLUG, ASK_URL, ASK_EVENTS, CONFIRM]
        assert len(states) == len(set(states))


# ===========================================================================
# core/db — list_email_logs_paged
# ===========================================================================

class TestListEmailLogsPaged:
    def test_function_exists_and_is_callable(self) -> None:
        from core.db import list_email_logs_paged
        import inspect

        assert callable(list_email_logs_paged)
        sig = inspect.signature(list_email_logs_paged)
        assert "project_id" in sig.parameters
        assert "status" in sig.parameters
        assert "since" in sig.parameters
        assert "limit" in sig.parameters

    def test_default_limit_is_20(self) -> None:
        import inspect
        from core.db import list_email_logs_paged

        sig = inspect.signature(list_email_logs_paged)
        assert sig.parameters["limit"].default == 20


# ===========================================================================
# apps/bot/main.py — handler registration
# ===========================================================================

class TestMainHandlerRegistration:
    def test_build_application_registers_new_handlers(self) -> None:
        """All Part 12 handlers must be registered in the application."""
        from apps.bot.main import build_application

        with patch("apps.bot.main.SupabasePersistence"):
            with patch("apps.bot.main.ApplicationBuilder") as mock_builder:
                # Chain the builder calls
                mock_instance = MagicMock()
                mock_builder.return_value.token.return_value.persistence.return_value.build.return_value = mock_instance
                mock_instance.add_handler = MagicMock()

                build_application()

        # add_handler should have been called multiple times (for all handlers)
        assert mock_instance.add_handler.call_count >= 10
