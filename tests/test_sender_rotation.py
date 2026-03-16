"""
tests/test_sender_rotation.py — Part 10 sender rotation tests.

Covers all required test cases:
  1. increment_sender_usage() returns correct incremented count
  2. Redis key TTL is set to 86400 after increment
  3. get_usage_pct() returns correct percentage based on daily_limit
  4. select_best_sender() returns sender with lowest usage below threshold
  5. select_best_sender() returns lowest-usage sender when all are above threshold
  6. check_and_rotate() updates project sender_email_id in DB
  7. check_and_rotate() fires Telegram alert with all 4 fields
  8. check_and_rotate() returns False when sender is below threshold
  9. check_and_rotate() returns True when rotation fires
  10. No crash when project has zero active senders
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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

from core.models import Project, SenderEmail  # noqa: E402
from core.sender_rotation import (  # noqa: E402
    check_and_rotate,
    get_usage_pct,
    increment_sender_usage,
    select_best_sender,
)

UTC = timezone.utc
NOW = datetime.now(UTC)

_PROJECT_ID = "proj-0001"
_SENDER_ID_A = "sender-0001"
_SENDER_ID_B = "sender-0002"
_SENDER_ID_C = "sender-0003"


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------

def _make_sender(
    sender_id: str = _SENDER_ID_A,
    email: str = "a@example.com",
    daily_limit: int = 100,
    daily_sent: int = 0,
    is_active: bool = True,
) -> SenderEmail:
    return SenderEmail(
        id=sender_id,
        email_address=email,
        display_name="Test Sender",
        provider="smtp",
        smtp_host="smtp.example.com",
        smtp_port=587,
        app_password_enc="encrypted",
        daily_limit=daily_limit,
        daily_sent=daily_sent,
        last_reset_at=NOW,
        is_active=is_active,
        created_at=NOW,
        updated_at=NOW,
    )


def _make_project(
    project_id: str = _PROJECT_ID,
    slug: str = "my-project",
    sender_email_id: str | None = _SENDER_ID_A,
) -> Project:
    return Project(
        id=project_id,
        name="My Project",
        slug=slug,
        sender_email_id=sender_email_id,
        otp_length=6,
        otp_expiry_seconds=300,
        otp_max_attempts=5,
        rate_limit_per_hour=100,
        template_subject="Your OTP",
        template_body_text="OTP: {otp}",
        template_body_html="<p>OTP: {otp}</p>",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


# ---------------------------------------------------------------------------
# Fixtures: mock Redis pipeline
# ---------------------------------------------------------------------------

def _make_redis_mock(incr_return: int = 1, ttl_return: bool = True) -> MagicMock:
    """Build a mock Redis client with pipeline support."""
    mock_redis = AsyncMock()

    # Pipeline mock
    mock_pipe = AsyncMock()
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[incr_return, ttl_return])

    # redis.pipeline() returns the pipe context manager
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    # For get() used in get_usage_pct
    mock_redis.get = AsyncMock(return_value=None)

    return mock_redis


# ===========================================================================
# 1. increment_sender_usage() — returns correct incremented count
# ===========================================================================

@pytest.mark.asyncio
async def test_increment_sender_usage_returns_count() -> None:
    """increment_sender_usage() returns the new counter value from INCR."""
    mock_redis = _make_redis_mock(incr_return=5)

    with patch("core.sender_rotation.get_redis", return_value=AsyncMock(return_value=mock_redis)):
        # get_redis is awaited inside increment_sender_usage
        with patch("core.sender_rotation.get_redis", new=AsyncMock(return_value=mock_redis)):
            result = await increment_sender_usage(_SENDER_ID_A)

    assert result == 5


# ===========================================================================
# 2. Redis key TTL is set to 86400 after increment
# ===========================================================================

@pytest.mark.asyncio
async def test_increment_sender_usage_sets_ttl() -> None:
    """increment_sender_usage() calls EXPIRE with 86400 in the same pipeline."""
    mock_redis = _make_redis_mock(incr_return=1)
    mock_pipe = mock_redis.pipeline()

    with patch("core.sender_rotation.get_redis", new=AsyncMock(return_value=mock_redis)):
        await increment_sender_usage(_SENDER_ID_A)

    # Verify INCR and EXPIRE were both called on the pipeline.
    mock_pipe.incr.assert_called_once_with(f"sender:daily:{_SENDER_ID_A}")
    mock_pipe.expire.assert_called_once_with(f"sender:daily:{_SENDER_ID_A}", 86400)
    mock_pipe.execute.assert_called_once()


# ===========================================================================
# 3. get_usage_pct() — correct percentage based on daily_limit
# ===========================================================================

@pytest.mark.asyncio
async def test_get_usage_pct_correct_percentage() -> None:
    """get_usage_pct() returns count / daily_limit."""
    sender = _make_sender(daily_limit=100)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="80")

    with patch("core.sender_rotation.get_redis", new=AsyncMock(return_value=mock_redis)):
        pct = await get_usage_pct(sender)

    assert pct == pytest.approx(0.80)


@pytest.mark.asyncio
async def test_get_usage_pct_zero_when_no_key() -> None:
    """get_usage_pct() returns 0.0 when Redis key does not exist."""
    sender = _make_sender(daily_limit=100)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with patch("core.sender_rotation.get_redis", new=AsyncMock(return_value=mock_redis)):
        pct = await get_usage_pct(sender)

    assert pct == 0.0


@pytest.mark.asyncio
async def test_get_usage_pct_zero_limit() -> None:
    """get_usage_pct() returns 0.0 when daily_limit is zero (no division by zero)."""
    sender = _make_sender(daily_limit=0)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="50")

    with patch("core.sender_rotation.get_redis", new=AsyncMock(return_value=mock_redis)):
        pct = await get_usage_pct(sender)

    assert pct == 0.0


# ===========================================================================
# 4. select_best_sender() — lowest usage below threshold
# ===========================================================================

@pytest.mark.asyncio
async def test_select_best_sender_below_threshold() -> None:
    """select_best_sender() picks the sender with lowest usage below threshold."""
    sender_a = _make_sender(_SENDER_ID_A, "a@x.com", daily_limit=100)
    sender_b = _make_sender(_SENDER_ID_B, "b@x.com", daily_limit=100)

    # a is at 30%, b is at 60% — both below 0.80 threshold; should pick a.
    async def _mock_pct(sender: SenderEmail) -> float:
        return 0.30 if sender.id == _SENDER_ID_A else 0.60

    with patch("core.sender_rotation.get_usage_pct", side_effect=_mock_pct):
        best = await select_best_sender([sender_a, sender_b])

    assert best is not None
    assert best.id == _SENDER_ID_A


# ===========================================================================
# 5. select_best_sender() — fallback when all above threshold (never None)
# ===========================================================================

@pytest.mark.asyncio
async def test_select_best_sender_fallback_when_all_above_threshold() -> None:
    """select_best_sender() returns lowest-usage sender when all are above threshold."""
    sender_a = _make_sender(_SENDER_ID_A, "a@x.com", daily_limit=100)
    sender_b = _make_sender(_SENDER_ID_B, "b@x.com", daily_limit=100)

    # Both above 0.80 threshold; b is lower — should return b.
    async def _mock_pct(sender: SenderEmail) -> float:
        return 0.95 if sender.id == _SENDER_ID_A else 0.85

    with patch("core.sender_rotation.get_usage_pct", side_effect=_mock_pct):
        best = await select_best_sender([sender_a, sender_b])

    assert best is not None
    assert best.id == _SENDER_ID_B


@pytest.mark.asyncio
async def test_select_best_sender_returns_none_for_empty_list() -> None:
    """select_best_sender() returns None when the sender list is empty."""
    best = await select_best_sender([])
    assert best is None


@pytest.mark.asyncio
async def test_select_best_sender_no_active_returns_none() -> None:
    """select_best_sender() returns None when all senders are inactive."""
    sender_a = _make_sender(_SENDER_ID_A, is_active=False)

    best = await select_best_sender([sender_a])
    assert best is None


# ===========================================================================
# 6. check_and_rotate() — updates project sender_email_id in DB
# ===========================================================================

@pytest.mark.asyncio
async def test_check_and_rotate_updates_db() -> None:
    """check_and_rotate() calls update_project with the new sender_email_id."""
    project = _make_project(sender_email_id=_SENDER_ID_A)
    sender_a = _make_sender(_SENDER_ID_A, "a@x.com", daily_limit=100)
    sender_b = _make_sender(_SENDER_ID_B, "b@x.com", daily_limit=100)

    async def _mock_pct(sender: SenderEmail) -> float:
        return 0.90 if sender.id == _SENDER_ID_A else 0.20

    with (
        patch("core.sender_rotation.get_project", return_value=project),
        patch("core.sender_rotation.get_sender_email", return_value=sender_a),
        patch("core.sender_rotation.get_usage_pct", side_effect=_mock_pct),
        patch("core.sender_rotation.list_sender_emails", return_value=[sender_a, sender_b]),
        patch("core.sender_rotation.update_project") as mock_update,
        patch("core.sender_rotation._send_telegram_alert", new=AsyncMock()),
    ):
        rotated = await check_and_rotate(_PROJECT_ID)

    assert rotated is True
    mock_update.assert_called_once_with(_PROJECT_ID, {"sender_email_id": _SENDER_ID_B})


# ===========================================================================
# 7. check_and_rotate() — Telegram alert includes all 4 fields
# ===========================================================================

@pytest.mark.asyncio
async def test_check_and_rotate_telegram_alert_has_all_fields() -> None:
    """check_and_rotate() fires Telegram alert with slug, old, new, usage%."""
    project = _make_project(slug="my-project", sender_email_id=_SENDER_ID_A)
    sender_a = _make_sender(_SENDER_ID_A, "old@x.com", daily_limit=100)
    sender_b = _make_sender(_SENDER_ID_B, "new@x.com", daily_limit=100)

    async def _mock_pct(sender: SenderEmail) -> float:
        return 0.90 if sender.id == _SENDER_ID_A else 0.20

    captured: list[str] = []

    async def _capture_alert(msg: str) -> None:
        captured.append(msg)

    with (
        patch("core.sender_rotation.get_project", return_value=project),
        patch("core.sender_rotation.get_sender_email", return_value=sender_a),
        patch("core.sender_rotation.get_usage_pct", side_effect=_mock_pct),
        patch("core.sender_rotation.list_sender_emails", return_value=[sender_a, sender_b]),
        patch("core.sender_rotation.update_project"),
        patch("core.sender_rotation._send_telegram_alert", side_effect=_capture_alert),
    ):
        await check_and_rotate(_PROJECT_ID)

    assert len(captured) == 1
    alert = captured[0]
    assert "my-project" in alert       # project slug
    assert "old@x.com" in alert        # old sender address
    assert "new@x.com" in alert        # new sender address
    assert "90.0%" in alert            # usage percentage


# ===========================================================================
# 8. check_and_rotate() — returns False when below threshold
# ===========================================================================

@pytest.mark.asyncio
async def test_check_and_rotate_returns_false_below_threshold() -> None:
    """check_and_rotate() returns False when sender usage is below threshold."""
    project = _make_project(sender_email_id=_SENDER_ID_A)
    sender_a = _make_sender(_SENDER_ID_A, daily_limit=100)

    async def _mock_pct(sender: SenderEmail) -> float:
        return 0.50  # well below 0.80

    with (
        patch("core.sender_rotation.get_project", return_value=project),
        patch("core.sender_rotation.get_sender_email", return_value=sender_a),
        patch("core.sender_rotation.get_usage_pct", side_effect=_mock_pct),
    ):
        result = await check_and_rotate(_PROJECT_ID)

    assert result is False


# ===========================================================================
# 9. check_and_rotate() — returns True when rotation fires
# ===========================================================================

@pytest.mark.asyncio
async def test_check_and_rotate_returns_true_on_rotation() -> None:
    """check_and_rotate() returns True when rotation happens."""
    project = _make_project(sender_email_id=_SENDER_ID_A)
    sender_a = _make_sender(_SENDER_ID_A, "a@x.com", daily_limit=100)
    sender_b = _make_sender(_SENDER_ID_B, "b@x.com", daily_limit=100)

    async def _mock_pct(sender: SenderEmail) -> float:
        return 0.90 if sender.id == _SENDER_ID_A else 0.10

    with (
        patch("core.sender_rotation.get_project", return_value=project),
        patch("core.sender_rotation.get_sender_email", return_value=sender_a),
        patch("core.sender_rotation.get_usage_pct", side_effect=_mock_pct),
        patch("core.sender_rotation.list_sender_emails", return_value=[sender_a, sender_b]),
        patch("core.sender_rotation.update_project"),
        patch("core.sender_rotation._send_telegram_alert", new=AsyncMock()),
    ):
        result = await check_and_rotate(_PROJECT_ID)

    assert result is True


# ===========================================================================
# 10. No crash when project has zero active senders
# ===========================================================================

@pytest.mark.asyncio
async def test_check_and_rotate_no_crash_zero_senders() -> None:
    """check_and_rotate() does not crash and returns False with no active senders."""
    project = _make_project(sender_email_id=_SENDER_ID_A)
    sender_a = _make_sender(_SENDER_ID_A, daily_limit=100)

    async def _mock_pct(sender: SenderEmail) -> float:
        return 0.95  # above threshold

    with (
        patch("core.sender_rotation.get_project", return_value=project),
        patch("core.sender_rotation.get_sender_email", return_value=sender_a),
        patch("core.sender_rotation.get_usage_pct", side_effect=_mock_pct),
        patch("core.sender_rotation.list_sender_emails", return_value=[]),
    ):
        result = await check_and_rotate(_PROJECT_ID)

    # With no senders, rotation cannot happen — must not crash.
    assert result is False


@pytest.mark.asyncio
async def test_select_best_sender_no_crash_zero_active_senders() -> None:
    """select_best_sender() does not crash with a list of inactive senders."""
    senders = [_make_sender(is_active=False), _make_sender(_SENDER_ID_B, is_active=False)]
    best = await select_best_sender(senders)
    assert best is None


# ===========================================================================
# Edge cases
# ===========================================================================

@pytest.mark.asyncio
async def test_check_and_rotate_project_not_found() -> None:
    """check_and_rotate() returns False when project does not exist."""
    with patch("core.sender_rotation.get_project", return_value=None):
        result = await check_and_rotate("nonexistent-project")
    assert result is False


@pytest.mark.asyncio
async def test_check_and_rotate_no_sender_assigned() -> None:
    """check_and_rotate() returns False when project has no sender assigned."""
    project = _make_project(sender_email_id=None)
    with patch("core.sender_rotation.get_project", return_value=project):
        result = await check_and_rotate(_PROJECT_ID)
    assert result is False


@pytest.mark.asyncio
async def test_check_and_rotate_only_one_sender_no_rotation() -> None:
    """check_and_rotate() returns False when only one sender exists (can't rotate)."""
    project = _make_project(sender_email_id=_SENDER_ID_A)
    sender_a = _make_sender(_SENDER_ID_A, "a@x.com", daily_limit=100)

    async def _mock_pct(sender: SenderEmail) -> float:
        return 0.95  # above threshold but only one sender

    with (
        patch("core.sender_rotation.get_project", return_value=project),
        patch("core.sender_rotation.get_sender_email", return_value=sender_a),
        patch("core.sender_rotation.get_usage_pct", side_effect=_mock_pct),
        patch("core.sender_rotation.list_sender_emails", return_value=[sender_a]),
        patch("core.sender_rotation.update_project") as mock_update,
    ):
        result = await check_and_rotate(_PROJECT_ID)

    # Cannot rotate to itself — must return False and NOT call update_project.
    assert result is False
    mock_update.assert_not_called()


# ===========================================================================
# Part 15 additions — rotation_check.py cron task tests
# ===========================================================================

from unittest.mock import AsyncMock, patch  # noqa: F401,F811 (re-import is fine)

# Import the worker task under test
from apps.worker.tasks.rotation_check import rotation_check  # noqa: E402


class TestRotationCheckTask:
    @pytest.mark.asyncio
    async def test_rotation_check_rotates_project_with_sender(self) -> None:
        """rotation_check calls check_and_rotate for each project with a sender."""
        project = _make_project(sender_email_id=_SENDER_ID_A)
        rotated_ids: list = []

        async def _mock_rotate(project_id: str) -> bool:
            rotated_ids.append(project_id)
            return True

        with (
            patch("apps.worker.tasks.rotation_check.list_projects", return_value=[project]),
            patch("apps.worker.tasks.rotation_check.check_and_rotate", side_effect=_mock_rotate),
        ):
            await rotation_check({})

        assert _PROJECT_ID in rotated_ids

    @pytest.mark.asyncio
    async def test_rotation_check_skips_project_without_sender(self) -> None:
        """rotation_check skips projects where sender_email_id is None."""
        project = _make_project(sender_email_id=None)
        rotated_ids: list = []

        async def _mock_rotate(project_id: str) -> bool:
            rotated_ids.append(project_id)
            return False

        with (
            patch("apps.worker.tasks.rotation_check.list_projects", return_value=[project]),
            patch("apps.worker.tasks.rotation_check.check_and_rotate", side_effect=_mock_rotate),
        ):
            await rotation_check({})

        assert rotated_ids == []  # No rotation for project without sender

    @pytest.mark.asyncio
    async def test_rotation_check_handles_list_projects_exception(self) -> None:
        """rotation_check returns gracefully when list_projects raises."""
        with patch(
            "apps.worker.tasks.rotation_check.list_projects",
            side_effect=RuntimeError("db down"),
        ):
            # Must not raise — exception is caught and logged
            await rotation_check({})

    @pytest.mark.asyncio
    async def test_rotation_check_handles_check_and_rotate_exception(self) -> None:
        """rotation_check continues to next project when check_and_rotate raises."""
        project_a = _make_project(sender_email_id=_SENDER_ID_A)
        project_b = _make_project(sender_email_id=_SENDER_ID_B)
        project_b.id = "proj-0002"
        project_b.slug = "proj-b"

        successful_ids: list = []

        async def _mock_rotate(project_id: str) -> bool:
            if project_id == _PROJECT_ID:
                raise RuntimeError("rotation error")
            successful_ids.append(project_id)
            return True

        with (
            patch(
                "apps.worker.tasks.rotation_check.list_projects",
                return_value=[project_a, project_b],
            ),
            patch(
                "apps.worker.tasks.rotation_check.check_and_rotate",
                side_effect=_mock_rotate,
            ),
        ):
            # Must not raise even when one project fails
            await rotation_check({})

        # Second project was still processed despite first failing
        assert "proj-0002" in successful_ids

    @pytest.mark.asyncio
    async def test_rotation_check_no_rotation_returns_false(self) -> None:
        """rotation_check does not log rotation when check_and_rotate returns False."""
        project = _make_project(sender_email_id=_SENDER_ID_A)

        async def _mock_rotate(project_id: str) -> bool:
            return False

        with (
            patch("apps.worker.tasks.rotation_check.list_projects", return_value=[project]),
            patch("apps.worker.tasks.rotation_check.check_and_rotate", side_effect=_mock_rotate),
        ):
            # Should complete without exception; no rotation happened
            await rotation_check({})


# ===========================================================================
# Part 15 additions — purge_otps cron task tests
# ===========================================================================

from apps.worker.tasks.purge_otps import purge_expired_otps  # noqa: E402


class TestPurgeExpiredOtps:
    @pytest.mark.asyncio
    async def test_purge_deletes_expired_records(self) -> None:
        """purge_expired_otps calls the correct Supabase delete chain."""
        mock_client = MagicMock()
        # Chain: .table().delete().lt().eq().execute()
        mock_execute = MagicMock()
        mock_execute.data = [{"id": "otp-1"}, {"id": "otp-2"}]
        (
            mock_client
            .table.return_value
            .delete.return_value
            .lt.return_value
            .eq.return_value
            .execute.return_value
        ) = mock_execute

        with patch("apps.worker.tasks.purge_otps.get_client", return_value=mock_client):
            await purge_expired_otps({})

        mock_client.table.assert_called_with("otp_records")

    @pytest.mark.asyncio
    async def test_purge_handles_empty_result(self) -> None:
        """purge_expired_otps handles empty result.data gracefully."""
        mock_client = MagicMock()
        mock_execute = MagicMock()
        mock_execute.data = []
        (
            mock_client
            .table.return_value
            .delete.return_value
            .lt.return_value
            .eq.return_value
            .execute.return_value
        ) = mock_execute

        with patch("apps.worker.tasks.purge_otps.get_client", return_value=mock_client):
            await purge_expired_otps({})  # Must not raise

    @pytest.mark.asyncio
    async def test_purge_handles_none_data(self) -> None:
        """purge_expired_otps handles None result.data gracefully."""
        mock_client = MagicMock()
        mock_execute = MagicMock()
        mock_execute.data = None
        (
            mock_client
            .table.return_value
            .delete.return_value
            .lt.return_value
            .eq.return_value
            .execute.return_value
        ) = mock_execute

        with patch("apps.worker.tasks.purge_otps.get_client", return_value=mock_client):
            await purge_expired_otps({})  # Must not raise

    @pytest.mark.asyncio
    async def test_purge_handles_exception(self) -> None:
        """purge_expired_otps returns gracefully when an exception is raised."""
        with patch(
            "apps.worker.tasks.purge_otps.get_client",
            side_effect=RuntimeError("db down"),
        ):
            # Must not raise — exception is caught and logged
            await purge_expired_otps({})
