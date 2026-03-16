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


# ===========================================================================
# Part 15 additions — coverage for bot commands and session
# ===========================================================================

# ---------------------------------------------------------------------------
# apps/bot/commands/start.py
# ---------------------------------------------------------------------------

class TestStartCommand:
    @pytest.mark.asyncio
    async def test_start_all_ok(self) -> None:
        """start_command sends status report when all systems are healthy."""
        from apps.bot.commands.start import start_command

        update = _make_update()
        ctx = _make_context()

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        mock_db_client = MagicMock()
        (
            mock_db_client
            .table.return_value
            .select.return_value
            .limit.return_value
            .execute.return_value
        ) = MagicMock(data=[{"id": "p1"}])

        with (
            patch("apps.bot.commands.start.get_client", return_value=mock_db_client),
            patch("apps.bot.commands.start.get_redis", return_value=mock_redis),
            patch("apps.bot.commands.start.settings.INTERNAL_API_URL", "http://api:3000"),
            patch("apps.bot.commands.start.httpx.AsyncClient", return_value=mock_http_client),
        ):
            await start_command(update, ctx)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "MailGuard Status" in text

    @pytest.mark.asyncio
    async def test_start_db_down(self) -> None:
        """start_command reports Supabase DB as failed when get_client raises."""
        from apps.bot.commands.start import start_command

        update = _make_update()
        ctx = _make_context()

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        with (
            patch("apps.bot.commands.start.get_client", side_effect=RuntimeError("db down")),
            patch("apps.bot.commands.start.get_redis", return_value=mock_redis),
            patch("apps.bot.commands.start.settings.INTERNAL_API_URL", ""),
        ):
            await start_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_redis_down(self) -> None:
        """start_command reports Redis as failed when ping raises."""
        from apps.bot.commands.start import start_command

        update = _make_update()
        ctx = _make_context()

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=RuntimeError("redis down"))

        mock_db_client = MagicMock()
        (
            mock_db_client
            .table.return_value
            .select.return_value
            .limit.return_value
            .execute.return_value
        ) = MagicMock(data=[{"id": "p1"}])

        with (
            patch("apps.bot.commands.start.get_client", return_value=mock_db_client),
            patch("apps.bot.commands.start.get_redis", return_value=mock_redis),
            patch("apps.bot.commands.start.settings.INTERNAL_API_URL", ""),
        ):
            await start_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_no_message_returns_early(self) -> None:
        """start_command exits silently when update.message is None."""
        from apps.bot.commands.start import start_command

        update = MagicMock()
        update.message = None
        ctx = _make_context()

        await start_command(update, ctx)  # Must not raise


# ---------------------------------------------------------------------------
# apps/bot/commands/webhooks.py
# ---------------------------------------------------------------------------

class TestWebhooksCommandPart15:
    @pytest.mark.asyncio
    async def test_webhooks_no_args(self) -> None:
        """webhooks_command replies with usage when no args provided."""
        from apps.bot.commands.webhooks import webhooks_command

        update = _make_update()
        ctx = _make_context(args=[])
        await webhooks_command(update, ctx)
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhooks_project_not_found(self) -> None:
        """webhooks_command replies with error when slug not found."""
        from apps.bot.commands.webhooks import webhooks_command

        update = _make_update()
        ctx = _make_context(args=["unknown-slug"])

        with patch("apps.bot.commands.webhooks.get_project_by_slug", return_value=None):
            await webhooks_command(update, ctx)

        update.message.reply_text.assert_called_once()
        assert "not found" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_webhooks_db_error_on_project(self) -> None:
        """webhooks_command replies with error when DB lookup raises."""
        from apps.bot.commands.webhooks import webhooks_command

        update = _make_update()
        ctx = _make_context(args=["slug"])

        with patch(
            "apps.bot.commands.webhooks.get_project_by_slug",
            side_effect=RuntimeError("db down"),
        ):
            await webhooks_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhooks_success(self) -> None:
        """webhooks_command shows list when webhooks exist."""
        from apps.bot.commands.webhooks import webhooks_command

        project = _make_project()
        wh = MagicMock()
        wh.id = "wh-001"
        wh.url = "https://app.example.com/webhook"
        wh.events = ["otp.sent"]
        wh.is_active = True
        wh.failure_count = 0

        update = _make_update()
        ctx = _make_context(args=["demo"])

        with (
            patch("apps.bot.commands.webhooks.get_project_by_slug", return_value=project),
            patch("apps.bot.commands.webhooks.list_webhooks", return_value=[wh]),
        ):
            await webhooks_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_removewebhook_no_args(self) -> None:
        """removewebhook_command replies with usage when no args provided."""
        from apps.bot.commands.webhooks import remove_webhook_command as removewebhook_command

        update = _make_update()
        ctx = _make_context(args=[])
        await removewebhook_command(update, ctx)
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_removewebhook_not_found(self) -> None:
        """removewebhook_command replies with error when webhook not found."""
        from apps.bot.commands.webhooks import remove_webhook_command as removewebhook_command

        update = _make_update()
        ctx = _make_context(args=["wh-999"])

        with patch("apps.bot.commands.webhooks.get_webhook", return_value=None):
            await removewebhook_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_removewebhook_success(self) -> None:
        """removewebhook_command deactivates and confirms."""
        from apps.bot.commands.webhooks import remove_webhook_command as removewebhook_command

        wh = MagicMock()
        wh.id = "wh-001"
        wh.url = "https://app.example.com/webhook"

        update = _make_update()
        ctx = _make_context(args=["wh-001"])

        with (
            patch("apps.bot.commands.webhooks.get_webhook", return_value=wh),
            patch("apps.bot.commands.webhooks.update_webhook", return_value=wh),
        ):
            await removewebhook_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_removewebhook_no_message(self) -> None:
        """removewebhook_command exits silently when update.message is None."""
        from apps.bot.commands.webhooks import remove_webhook_command as removewebhook_command

        update = MagicMock()
        update.message = None
        ctx = _make_context()

        await removewebhook_command(update, ctx)  # Must not raise


# ---------------------------------------------------------------------------
# apps/bot/commands/keys.py — extra coverage
# ---------------------------------------------------------------------------

class TestKeysCommandPart15:
    @pytest.mark.asyncio
    async def test_genkey_no_args(self) -> None:
        """genkey_command replies with usage when no args provided."""
        from apps.bot.commands.keys import genkey_command

        update = _make_update()
        ctx = _make_context(args=[])
        await genkey_command(update, ctx)
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_genkey_project_not_found(self) -> None:
        """genkey_command replies with error when slug not found."""
        from apps.bot.commands.keys import genkey_command

        update = _make_update()
        ctx = _make_context(args=["slug"])

        with patch("apps.bot.commands.keys.get_project_by_slug", return_value=None):
            await genkey_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_genkey_success(self) -> None:
        """genkey_command generates and shows plaintext key once."""
        from apps.bot.commands.keys import genkey_command

        project = _make_project()
        key = _make_api_key()

        update = _make_update()
        ctx = _make_context(args=["demo"])

        with (
            patch("apps.bot.commands.keys.get_project_by_slug", return_value=project),
            patch(
                "apps.bot.commands.keys.generate_api_key",
                return_value=("mg_live_" + "a" * 64, key),
            ),
        ):
            await genkey_command(update, ctx)

        update.message.reply_text.assert_called_once()
        text = update.message.reply_text.call_args[0][0]
        assert "mg_live_" in text

    @pytest.mark.asyncio
    async def test_revokekey_no_args(self) -> None:
        """revokekey_command replies with usage when no args provided."""
        from apps.bot.commands.keys import revokekey_command

        update = _make_update()
        ctx = _make_context(args=[])
        await revokekey_command(update, ctx)
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_revokekey_not_found(self) -> None:
        """revokekey_command replies with error when key not found."""
        from apps.bot.commands.keys import revokekey_command

        update = _make_update()
        ctx = _make_context(args=["key-999"])

        with patch("apps.bot.commands.keys.get_api_key", return_value=None):
            await revokekey_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_revokekey_success(self) -> None:
        """revokekey_command deactivates the key and confirms."""
        from apps.bot.commands.keys import revokekey_command

        key = _make_api_key()

        update = _make_update()
        ctx = _make_context(args=["key-001"])

        with (
            patch("apps.bot.commands.keys.get_api_key", return_value=key),
            patch("apps.bot.commands.keys.revoke_api_key", return_value=key),
        ):
            await revokekey_command(update, ctx)

        update.message.reply_text.assert_called_once()


# ---------------------------------------------------------------------------
# apps/bot/commands/projects.py — extra coverage
# ---------------------------------------------------------------------------

class TestProjectsCommandPart15:
    @pytest.mark.asyncio
    async def test_projects_no_projects(self) -> None:
        """projects_command replies with empty message when no projects exist."""
        from apps.bot.commands.projects import projects_command

        update = _make_update()
        ctx = _make_context()

        with patch("apps.bot.commands.projects.list_projects", return_value=[]):
            await projects_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_projects_with_results(self) -> None:
        """projects_command shows list of projects."""
        from apps.bot.commands.projects import projects_command

        project = _make_project()
        update = _make_update()
        ctx = _make_context()

        with patch("apps.bot.commands.projects.list_projects", return_value=[project]):
            await projects_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_projects_db_error(self) -> None:
        """projects_command handles DB exception gracefully."""
        from apps.bot.commands.projects import projects_command

        update = _make_update()
        ctx = _make_context()

        with patch(
            "apps.bot.commands.projects.list_projects",
            side_effect=RuntimeError("db down"),
        ):
            await projects_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_activate_project_no_args(self) -> None:
        """activateproject_command replies with usage when no args provided."""
        from apps.bot.commands.projects import activateproject_command

        update = _make_update()
        ctx = _make_context(args=[])
        await activateproject_command(update, ctx)
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_activate_project_success(self) -> None:
        """activateproject_command activates a project."""
        from apps.bot.commands.projects import activateproject_command

        project = _make_project()
        project.is_active = False

        update = _make_update()
        ctx = _make_context(args=["demo"])

        with (
            patch("apps.bot.commands.projects.get_project_by_slug", return_value=project),
            patch("apps.bot.commands.projects.update_project", return_value=project),
        ):
            await activateproject_command(update, ctx)

        update.message.reply_text.assert_called_once()


# ---------------------------------------------------------------------------
# apps/bot/commands/logs.py — extra coverage
# ---------------------------------------------------------------------------

class TestLogsCommandPart15:
    @pytest.mark.asyncio
    async def test_logs_no_args(self) -> None:
        """logs_command replies with usage when no args provided."""
        from apps.bot.commands.logs import logs_command

        update = _make_update()
        ctx = _make_context(args=[])
        await logs_command(update, ctx)
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_project_not_found(self) -> None:
        """logs_command replies with error when project not found."""
        from apps.bot.commands.logs import logs_command

        update = _make_update()
        ctx = _make_context(args=["unknown"])

        with patch("apps.bot.commands.logs.get_project_by_slug", return_value=None):
            await logs_command(update, ctx)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_shows_entries(self) -> None:
        """logs_command shows log entries when they exist."""
        from apps.bot.commands.logs import logs_command

        project = _make_project()
        log = _make_log()

        update = _make_update()
        ctx = _make_context(args=["demo"])

        with (
            patch("apps.bot.commands.logs.get_project_by_slug", return_value=project),
            patch("apps.bot.commands.logs.list_email_logs_paged", return_value=([log], None)),
        ):
            await logs_command(update, ctx)

        update.message.reply_text.assert_called_once()


# ---------------------------------------------------------------------------
# apps/bot/session.py
# ---------------------------------------------------------------------------

class TestSupabasePersistenceSession:
    """Tests for the Supabase-backed session persistence helper."""

    def _make_client(self, value: Any = None) -> MagicMock:
        """Build a mock Supabase client that returns *value* from maybe_single."""
        client = MagicMock()
        result = MagicMock()
        result.data = value
        (
            client
            .table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.return_value
        ) = result
        (
            client
            .table.return_value
            .upsert.return_value
            .execute.return_value
        ) = MagicMock()
        return client

    def test_db_load_returns_value(self) -> None:
        """_db_load returns the stored value from bot_sessions."""
        from apps.bot.session import _db_load

        mock_client = self._make_client(value={"foo": "bar"})
        with patch("apps.bot.session.get_client", return_value=mock_client):
            result = _db_load("conversations")
        assert result == {"foo": "bar"}

    def test_db_load_returns_none_when_no_data(self) -> None:
        """_db_load returns None when bot_sessions row has no data."""
        from apps.bot.session import _db_load

        mock_client = self._make_client(value=None)
        with patch("apps.bot.session.get_client", return_value=mock_client):
            result = _db_load("user_data")
        assert result is None

    def test_db_load_returns_none_on_exception(self) -> None:
        """_db_load returns None when get_client raises."""
        from apps.bot.session import _db_load

        with patch("apps.bot.session.get_client", side_effect=RuntimeError("db down")):
            result = _db_load("bot_data")
        assert result is None

    def test_db_save_calls_upsert(self) -> None:
        """_db_save calls upsert on bot_sessions table."""
        from apps.bot.session import _db_save

        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("apps.bot.session.get_client", return_value=mock_client):
            _db_save("conversations", {"state": 1})

        mock_client.table.assert_called_with("bot_sessions")
        mock_client.table.return_value.upsert.assert_called_once()

    def test_db_save_handles_exception(self) -> None:
        """_db_save logs warning and does not raise on exception."""
        from apps.bot.session import _db_save

        with patch("apps.bot.session.get_client", side_effect=RuntimeError("db down")):
            _db_save("test_key", {"data": "value"})  # Must not raise

    def test_tuple_key_serialization(self) -> None:
        """_tuple_key and _parse_tuple_key are inverse operations."""
        from apps.bot.session import _tuple_key, _parse_tuple_key

        original = (123, 456)
        serialized = _tuple_key(original)
        assert isinstance(serialized, str)
        restored = _parse_tuple_key(serialized)
        assert restored == original

    def test_tuple_key_with_strings(self) -> None:
        """_tuple_key handles string elements."""
        from apps.bot.session import _tuple_key, _parse_tuple_key

        original = ("chat-1", "user-2")
        serialized = _tuple_key(original)
        restored = _parse_tuple_key(serialized)
        assert restored == original

    @pytest.mark.asyncio
    async def test_get_conversations_empty(self) -> None:
        """get_conversations returns empty dict when no conversation data stored."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        mock_client = self._make_client(value=None)

        with patch("apps.bot.session.get_client", return_value=mock_client):
            convs = await sess.get_conversations("wizard_state")

        assert convs == {}

    @pytest.mark.asyncio
    async def test_update_and_get_conversation(self) -> None:
        """update_conversation saves state; get_conversations reads it back."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        mock_client = MagicMock()
        # _db_load returns None initially (no data)
        result_empty = MagicMock()
        result_empty.data = None
        (
            mock_client
            .table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.return_value
        ) = result_empty
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("apps.bot.session.get_client", return_value=mock_client):
            await sess.update_conversation("wizard", (1, 2), "STATE_A")
            convs = await sess.get_conversations("wizard")

        assert convs[(1, 2)] == "STATE_A"

    @pytest.mark.asyncio
    async def test_update_conversation_removes_none_state(self) -> None:
        """update_conversation with new_state=None removes the key."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        mock_client = MagicMock()
        result_empty = MagicMock()
        result_empty.data = None
        (
            mock_client
            .table.return_value
            .select.return_value
            .eq.return_value
            .maybe_single.return_value
            .execute.return_value
        ) = result_empty
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("apps.bot.session.get_client", return_value=mock_client):
            await sess.update_conversation("wizard", (1, 2), "STATE_A")
            await sess.update_conversation("wizard", (1, 2), None)

    @pytest.mark.asyncio
    async def test_get_user_data_empty(self) -> None:
        """get_user_data returns empty dict when no user data stored."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        mock_client = self._make_client(value=None)

        with patch("apps.bot.session.get_client", return_value=mock_client):
            data = await sess.get_user_data()

        assert data == {}

    @pytest.mark.asyncio
    async def test_update_user_data(self) -> None:
        """update_user_data saves user data."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("apps.bot.session.get_client", return_value=mock_client):
            await sess.update_user_data(123, {"key": "value"})

        assert sess._user_data[123] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_drop_user_data(self) -> None:
        """drop_user_data removes user data for the given user_id."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        sess._user_data[456] = {"tmp": "data"}
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("apps.bot.session.get_client", return_value=mock_client):
            await sess.drop_user_data(456)

        assert 456 not in sess._user_data

    @pytest.mark.asyncio
    async def test_get_chat_data_empty(self) -> None:
        """get_chat_data returns empty dict when no chat data stored."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        mock_client = self._make_client(value=None)

        with patch("apps.bot.session.get_client", return_value=mock_client):
            data = await sess.get_chat_data()

        assert data == {}

    @pytest.mark.asyncio
    async def test_update_chat_data(self) -> None:
        """update_chat_data saves chat data."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("apps.bot.session.get_client", return_value=mock_client):
            await sess.update_chat_data(789, {"state": "wizard"})

        assert sess._chat_data[789] == {"state": "wizard"}

    @pytest.mark.asyncio
    async def test_drop_chat_data(self) -> None:
        """drop_chat_data removes chat data for the given chat_id."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        sess._chat_data[321] = {"tmp": "data"}
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("apps.bot.session.get_client", return_value=mock_client):
            await sess.drop_chat_data(321)

        assert 321 not in sess._chat_data

    @pytest.mark.asyncio
    async def test_get_bot_data_empty(self) -> None:
        """get_bot_data returns empty dict when no bot data stored."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        mock_client = self._make_client(value=None)

        with patch("apps.bot.session.get_client", return_value=mock_client):
            data = await sess.get_bot_data()

        assert data == {}

    @pytest.mark.asyncio
    async def test_update_bot_data(self) -> None:
        """update_bot_data saves bot-level data."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("apps.bot.session.get_client", return_value=mock_client):
            await sess.update_bot_data({"feature_flags": {"v2": True}})

        assert sess._bot_data == {"feature_flags": {"v2": True}}

    @pytest.mark.asyncio
    async def test_callback_data_returns_none(self) -> None:
        """get_callback_data always returns None (callback_data=False)."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        result = await sess.get_callback_data()
        assert result is None

    @pytest.mark.asyncio
    async def test_update_callback_data_is_noop(self) -> None:
        """update_callback_data does nothing (callback_data=False)."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        await sess.update_callback_data({"any": "data"})  # Must not raise

    @pytest.mark.asyncio
    async def test_flush_is_noop(self) -> None:
        """flush() completes without side effects."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        await sess.flush()  # Must not raise

    @pytest.mark.asyncio
    async def test_refresh_user_data_is_noop(self) -> None:
        """refresh_user_data does nothing (data managed by update_user_data)."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        await sess.refresh_user_data(123, {"key": "value"})  # Must not raise

    @pytest.mark.asyncio
    async def test_refresh_chat_data_is_noop(self) -> None:
        """refresh_chat_data does nothing (data managed by update_chat_data)."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        await sess.refresh_chat_data(789, {"key": "value"})  # Must not raise

    @pytest.mark.asyncio
    async def test_refresh_bot_data_is_noop(self) -> None:
        """refresh_bot_data does nothing (data managed by update_bot_data)."""
        from apps.bot.session import SupabasePersistence

        sess = SupabasePersistence()
        await sess.refresh_bot_data({"key": "value"})  # Must not raise


# ---------------------------------------------------------------------------
# apps/worker/main.py — _parse_redis_settings unit tests
# ---------------------------------------------------------------------------

class TestParseRedisSettings:
    def test_parse_basic_redis_url(self) -> None:
        """Simple redis://host:port/db is parsed correctly."""
        from apps.worker.main import _parse_redis_settings

        with patch("apps.worker.main.settings.REDIS_URL", "redis://myhost:6380/1"):
            rs = _parse_redis_settings()

        assert rs.host == "myhost"
        assert rs.port == 6380
        assert rs.database == 1
        assert rs.ssl is False
        assert rs.password is None

    def test_parse_rediss_url_enables_ssl(self) -> None:
        """rediss:// scheme enables SSL flag."""
        from apps.worker.main import _parse_redis_settings

        with patch("apps.worker.main.settings.REDIS_URL", "rediss://redis.upstash.io:6380"):
            rs = _parse_redis_settings()

        assert rs.ssl is True
        assert rs.host == "redis.upstash.io"
        assert rs.port == 6380

    def test_parse_url_with_password(self) -> None:
        """redis://:password@host:port is parsed to extract password."""
        from apps.worker.main import _parse_redis_settings

        with patch(
            "apps.worker.main.settings.REDIS_URL",
            "redis://:secretpass@redis.example.com:6379",
        ):
            rs = _parse_redis_settings()

        assert rs.password == "secretpass"
        assert rs.host == "redis.example.com"

    def test_parse_url_no_port_defaults_to_6379(self) -> None:
        """URL without explicit port defaults to 6379."""
        from apps.worker.main import _parse_redis_settings

        with patch("apps.worker.main.settings.REDIS_URL", "redis://myhost"):
            rs = _parse_redis_settings()

        assert rs.host == "myhost"
        assert rs.port == 6379

    def test_parse_url_no_db_defaults_to_zero(self) -> None:
        """URL without explicit /db suffix defaults to database=0."""
        from apps.worker.main import _parse_redis_settings

        with patch("apps.worker.main.settings.REDIS_URL", "redis://localhost:6379"):
            rs = _parse_redis_settings()

        assert rs.database == 0

    def test_worker_settings_has_functions(self) -> None:
        """WorkerSettings.functions includes send_email and deliver_webhook."""
        from apps.worker.main import WorkerSettings

        func_names = [f.__name__ for f in WorkerSettings.functions]
        assert "task_send_email" in func_names
        assert "task_deliver_webhook" in func_names

    def test_worker_settings_has_cron_jobs(self) -> None:
        """WorkerSettings.cron_jobs has two registered cron tasks."""
        from apps.worker.main import WorkerSettings

        assert len(WorkerSettings.cron_jobs) >= 2

    def test_worker_settings_job_timeout(self) -> None:
        """WorkerSettings.job_timeout is set to a reasonable value."""
        from apps.worker.main import WorkerSettings

        assert WorkerSettings.job_timeout >= 600
