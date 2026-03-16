"""
tests/test_webhooks.py — Part 09 webhook tests.

Covers all required test cases:
  1. POST /api/v1/webhooks creates endpoint, returns secret once
  2. GET /api/v1/webhooks lists endpoints without exposing secret
  3. DELETE /api/v1/webhooks/{id} sets is_active=False
  4. fire_event() enqueues one ARQ job per subscribed endpoint
  5. fire_event() with no subscribed endpoints enqueues nothing
  6. sign_payload() produces consistent signature for same input
  7. Modified payload fails signature verification
  8. Delivery success sets last_triggered_at and returns
  9. 1st failure retries after 10s, 2nd after 60s, 3rd marks failed
  10. 3rd failure fires Telegram alert
  11. Delivery timeout (mock slow response) counts as failure
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

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

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from apps.api.routes import webhooks as webhooks_module  # noqa: E402
from apps.worker.tasks.deliver_webhook import task_deliver_webhook  # noqa: E402
from core.crypto import encrypt  # noqa: E402
from core.models import ApiKey, Webhook  # noqa: E402
from core.webhooks import fire_event, sign_payload  # noqa: E402

UTC = timezone.utc
NOW = datetime.now(UTC)

_LIVE_KEY = "mg_live_" + "a" * 64
_PROJECT_ID = "proj-0001"
_KEY_ID = "key-0001"
_WEBHOOK_ID = "webhook-0001"
_WEBHOOK_URL = "https://example.com/webhook"
_RAW_SECRET = "deadbeef" * 8  # 64 hex chars = 32 bytes
_SECRET_ENC = encrypt(_RAW_SECRET)


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------

def _make_api_key(is_active: bool = True, is_sandbox: bool = False) -> ApiKey:
    return ApiKey(
        id=_KEY_ID,
        project_id=_PROJECT_ID,
        key_hash="dead" * 16,
        key_prefix="mg_live_test",
        label="test",
        is_sandbox=is_sandbox,
        is_active=is_active,
        last_used_at=None,
        created_at=NOW,
    )


def _make_webhook(
    webhook_id: str = _WEBHOOK_ID,
    events: list | None = None,
    is_active: bool = True,
    failure_count: int = 0,
) -> Webhook:
    return Webhook(
        id=webhook_id,
        project_id=_PROJECT_ID,
        url=_WEBHOOK_URL,
        secret_enc=_SECRET_ENC,
        events=events if events is not None else ["otp.sent"],
        is_active=is_active,
        failure_count=failure_count,
        last_triggered_at=None,
        created_at=NOW,
    )


# ---------------------------------------------------------------------------
# App factory and fixtures
# ---------------------------------------------------------------------------

def _make_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(webhooks_module.router)
    return app


@pytest.fixture()
def test_app() -> FastAPI:
    return _make_test_app()


@pytest_asyncio.fixture()
async def client(test_app: FastAPI):  # type: ignore[no-untyped-def]
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


def _auth_headers(key: str = _LIVE_KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ===========================================================================
# 1. POST /api/v1/webhooks — creates endpoint, returns secret once
# ===========================================================================

@pytest.mark.asyncio
async def test_register_webhook_returns_secret_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/v1/webhooks creates endpoint and returns plaintext secret once."""
    key_row = _make_api_key()
    webhook = _make_webhook()

    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr(
        "apps.api.routes.webhooks.insert_webhook", lambda data: webhook
    )

    r = await client.post(
        "/api/v1/webhooks",
        json={"url": _WEBHOOK_URL, "events": ["otp.sent"]},
        headers=_auth_headers(),
    )

    assert r.status_code == 201
    body = r.json()
    assert body["id"] == _WEBHOOK_ID
    assert body["url"] == _WEBHOOK_URL
    assert body["is_active"] is True
    # Secret is present and looks like a hex string
    assert "secret" in body
    assert len(body["secret"]) == 64  # token_hex(32) = 64 hex chars
    # secret_enc is NOT exposed
    assert "secret_enc" not in body


@pytest.mark.asyncio
async def test_register_webhook_401_no_auth(client: AsyncClient) -> None:
    """Missing auth header returns 401."""
    r = await client.post(
        "/api/v1/webhooks",
        json={"url": _WEBHOOK_URL, "events": ["otp.sent"]},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_register_webhook_422_bad_url(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-http(s) URL returns 422."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)

    r = await client.post(
        "/api/v1/webhooks",
        json={"url": "ftp://example.com/hook", "events": ["otp.sent"]},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


# ===========================================================================
# 2. GET /api/v1/webhooks — lists endpoints without exposing secret
# ===========================================================================

@pytest.mark.asyncio
async def test_list_webhooks_no_secret_exposed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/v1/webhooks returns list without secret or secret_enc."""
    key_row = _make_api_key()
    webhook = _make_webhook()

    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr(
        "apps.api.routes.webhooks.list_webhooks", lambda _: [webhook]
    )

    r = await client.get("/api/v1/webhooks", headers=_auth_headers())

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    item = body[0]
    assert item["id"] == _WEBHOOK_ID
    assert item["url"] == _WEBHOOK_URL
    # Secret must never appear in list response
    assert "secret" not in item
    assert "secret_enc" not in item


@pytest.mark.asyncio
async def test_list_webhooks_empty(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/v1/webhooks returns empty list when no webhooks registered."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.webhooks.list_webhooks", lambda _: [])

    r = await client.get("/api/v1/webhooks", headers=_auth_headers())

    assert r.status_code == 200
    assert r.json() == []


# ===========================================================================
# 3. DELETE /api/v1/webhooks/{id} — sets is_active=False
# ===========================================================================

@pytest.mark.asyncio
async def test_delete_webhook_sets_is_active_false(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELETE /api/v1/webhooks/{id} deactivates the endpoint."""
    key_row = _make_api_key()
    webhook = _make_webhook()
    deactivated = _make_webhook(is_active=False)
    update_calls: list = []

    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr(
        "apps.api.routes.webhooks.get_webhook", lambda _: webhook
    )

    def _mock_update(wid: str, data: dict) -> Webhook:
        update_calls.append((wid, data))
        return deactivated

    monkeypatch.setattr("apps.api.routes.webhooks.update_webhook", _mock_update)

    r = await client.delete(
        f"/api/v1/webhooks/{_WEBHOOK_ID}", headers=_auth_headers()
    )

    assert r.status_code == 200
    body = r.json()
    assert body["is_active"] is False
    # Verify the update was called with is_active=False
    assert len(update_calls) == 1
    assert update_calls[0][1] == {"is_active": False}


@pytest.mark.asyncio
async def test_delete_webhook_404_not_found(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELETE /api/v1/webhooks/{id} returns 404 for unknown webhook."""
    key_row = _make_api_key()
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.webhooks.get_webhook", lambda _: None)

    r = await client.delete(
        f"/api/v1/webhooks/{_WEBHOOK_ID}", headers=_auth_headers()
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_webhook_404_wrong_project(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELETE /api/v1/webhooks/{id} returns 404 when webhook belongs to another project."""
    key_row = _make_api_key()
    # Webhook belongs to a different project
    other_webhook = Webhook(
        id=_WEBHOOK_ID,
        project_id="other-project",
        url=_WEBHOOK_URL,
        secret_enc=_SECRET_ENC,
        events=["otp.sent"],
        is_active=True,
        failure_count=0,
        last_triggered_at=None,
        created_at=NOW,
    )
    monkeypatch.setattr("core.api_keys.get_api_key_by_hash", lambda _: key_row)
    monkeypatch.setattr("apps.api.routes.webhooks.get_webhook", lambda _: other_webhook)

    r = await client.delete(
        f"/api/v1/webhooks/{_WEBHOOK_ID}", headers=_auth_headers()
    )
    assert r.status_code == 404


# ===========================================================================
# 4. fire_event() enqueues one ARQ job per subscribed endpoint
# ===========================================================================

@pytest.mark.asyncio
async def test_fire_event_enqueues_job_per_subscribed_endpoint() -> None:
    """fire_event() enqueues one task_deliver_webhook job per subscribed webhook."""
    w1 = _make_webhook("wh-001", events=["otp.sent"])
    w2 = _make_webhook("wh-002", events=["otp.sent", "otp.verified"])
    # w3 is NOT subscribed to otp.sent
    w3 = _make_webhook("wh-003", events=["magic_link.sent"])

    enqueued: list = []

    mock_arq = AsyncMock()
    mock_arq.enqueue_job = AsyncMock(side_effect=lambda *a, **kw: enqueued.append(a))
    mock_arq.aclose = AsyncMock()

    with (
        patch("core.webhooks.list_webhooks", return_value=[w1, w2, w3]),
        patch("core.webhooks.create_pool", return_value=mock_arq),
    ):
        await fire_event(_PROJECT_ID, "otp.sent", {"purpose": "login"})

    # Only w1 and w2 are subscribed to otp.sent
    assert len(enqueued) == 2
    job_names = [e[0] for e in enqueued]
    assert all(n == "task_deliver_webhook" for n in job_names)
    webhook_ids = [e[1] for e in enqueued]
    assert set(webhook_ids) == {"wh-001", "wh-002"}


# ===========================================================================
# 5. fire_event() with no subscribed endpoints enqueues nothing
# ===========================================================================

@pytest.mark.asyncio
async def test_fire_event_no_subscribed_endpoints_enqueues_nothing() -> None:
    """fire_event() does nothing when no endpoints are subscribed to the event."""
    w1 = _make_webhook("wh-001", events=["magic_link.sent"])

    mock_arq = AsyncMock()
    mock_arq.enqueue_job = AsyncMock()
    mock_arq.aclose = AsyncMock()

    with (
        patch("core.webhooks.list_webhooks", return_value=[w1]),
        patch("core.webhooks.create_pool", return_value=mock_arq) as mock_pool,
    ):
        await fire_event(_PROJECT_ID, "otp.sent", {})

    # Pool was never created because there are no subscribers
    mock_pool.assert_not_called()
    mock_arq.enqueue_job.assert_not_called()


# ===========================================================================
# 6. sign_payload() produces consistent signature for same input
# ===========================================================================

def test_sign_payload_deterministic() -> None:
    """sign_payload returns identical signature for the same key and payload."""
    secret = "my-secret-key"
    payload = {"z": 1, "a": 2, "m": 3}

    sig1 = sign_payload(secret, payload)
    sig2 = sign_payload(secret, payload)

    assert sig1 == sig2
    assert sig1.startswith("sha256=")


def test_sign_payload_key_order_invariant() -> None:
    """sign_payload produces the same signature regardless of key insertion order."""
    secret = "my-secret-key"
    payload_a = {"z": 1, "a": 2}
    payload_b = {"a": 2, "z": 1}

    sig_a = sign_payload(secret, payload_a)
    sig_b = sign_payload(secret, payload_b)

    assert sig_a == sig_b


def test_sign_payload_format() -> None:
    """sign_payload returns signature in 'sha256={hex}' format."""
    sig = sign_payload("secret", {"key": "value"})

    assert sig.startswith("sha256=")
    hex_part = sig[len("sha256="):]
    assert len(hex_part) == 64  # SHA-256 = 32 bytes = 64 hex chars
    # Must be valid hex
    int(hex_part, 16)


# ===========================================================================
# 7. Modified payload fails signature verification
# ===========================================================================

def test_sign_payload_modified_payload_fails_verification() -> None:
    """A signature computed for one payload does not verify a different payload."""
    secret = "my-secret-key"
    original_payload = {"event": "otp.sent", "data": {"purpose": "login"}}
    tampered_payload = {"event": "otp.sent", "data": {"purpose": "EVIL"}}

    sig = sign_payload(secret, original_payload)

    # Verify tampered payload against original signature
    tampered_bytes = json.dumps(
        tampered_payload, sort_keys=True, separators=(",", ":")
    ).encode()
    expected_digest = hmac.new(
        secret.encode(), tampered_bytes, hashlib.sha256
    ).hexdigest()
    tampered_sig = f"sha256={expected_digest}"

    assert not hmac.compare_digest(sig, tampered_sig)


def test_sign_payload_wrong_secret_fails_verification() -> None:
    """A signature produced with secret A does not verify under secret B."""
    payload = {"event": "otp.sent"}
    sig_a = sign_payload("secret-a", payload)
    sig_b = sign_payload("secret-b", payload)

    assert not hmac.compare_digest(sig_a, sig_b)


# ===========================================================================
# 8. Delivery success sets last_triggered_at and returns
# ===========================================================================

class _SuccessResp:
    """Fake aiohttp response with 200 status."""

    status = 200

    async def __aenter__(self) -> "_SuccessResp":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _SuccessSession:
    """Fake aiohttp session that returns a 200 response on POST."""

    def __init__(self, **kwargs: Any) -> None:
        pass

    def post(self, url: str, json: Any = None, headers: Any = None) -> _SuccessResp:  # type: ignore[override]
        return _SuccessResp()

    async def __aenter__(self) -> "_SuccessSession":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False


@pytest.mark.asyncio
async def test_deliver_webhook_success_updates_last_triggered_at() -> None:
    """On 2xx response, task updates webhooks.last_triggered_at."""
    update_calls: list = []

    def _mock_update(webhook_id: str, data: dict) -> Webhook:
        update_calls.append((webhook_id, data))
        return _make_webhook()

    with (
        patch("apps.worker.tasks.deliver_webhook.aiohttp.ClientSession", _SuccessSession),
        patch("apps.worker.tasks.deliver_webhook.update_webhook", _mock_update),
    ):
        await task_deliver_webhook(
            {},
            _WEBHOOK_ID,
            _WEBHOOK_URL,
            _SECRET_ENC,
            "otp.sent",
            {"purpose": "login"},
        )

    # last_triggered_at was set
    assert len(update_calls) == 1
    assert "last_triggered_at" in update_calls[0][1]


@pytest.mark.asyncio
async def test_deliver_webhook_request_has_signature_header() -> None:
    """The HTTP POST carries an X-MailGuard-Signature header."""
    captured_headers: list = []

    class _HeaderCapturingResp:
        status = 200

        async def __aenter__(self) -> "_HeaderCapturingResp":
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

    class _HeaderCapturingSession:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def post(self, url: str, json: Any = None, headers: Any = None) -> _HeaderCapturingResp:  # type: ignore[override]
            captured_headers.append(headers or {})
            return _HeaderCapturingResp()

        async def __aenter__(self) -> "_HeaderCapturingSession":
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

    with (
        patch("apps.worker.tasks.deliver_webhook.aiohttp.ClientSession", _HeaderCapturingSession),
        patch("apps.worker.tasks.deliver_webhook.update_webhook", lambda *a, **kw: _make_webhook()),
    ):
        await task_deliver_webhook(
            {},
            _WEBHOOK_ID,
            _WEBHOOK_URL,
            _SECRET_ENC,
            "otp.sent",
            {"purpose": "login"},
        )

    assert len(captured_headers) == 1
    assert "X-MailGuard-Signature" in captured_headers[0]
    sig = captured_headers[0]["X-MailGuard-Signature"]
    assert sig.startswith("sha256=")


# ===========================================================================
# 9. 1st failure retries after 10s, 2nd after 60s, 3rd marks failed
# ===========================================================================

@pytest.mark.asyncio
async def test_deliver_webhook_retry_backoff() -> None:
    """Delivery fails 3 times with correct backoff delays."""
    sleep_calls: list = []

    class _FailResp:
        status = 500

        async def __aenter__(self) -> "_FailResp":
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

    class _FailSession:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def post(self, url: str, json: Any = None, headers: Any = None) -> _FailResp:  # type: ignore[override]
            return _FailResp()

        async def __aenter__(self) -> "_FailSession":
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

    mock_webhook = _make_webhook()

    async def _mock_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with (
        patch("apps.worker.tasks.deliver_webhook.aiohttp.ClientSession", _FailSession),
        patch("apps.worker.tasks.deliver_webhook.asyncio.sleep", _mock_sleep),
        patch("apps.worker.tasks.deliver_webhook.get_webhook", return_value=mock_webhook),
        patch("apps.worker.tasks.deliver_webhook.update_webhook", return_value=mock_webhook),
        patch("apps.worker.tasks.deliver_webhook._send_telegram_alert", new_callable=AsyncMock),
    ):
        await task_deliver_webhook(
            {},
            _WEBHOOK_ID,
            _WEBHOOK_URL,
            _SECRET_ENC,
            "otp.sent",
            {"purpose": "login"},
        )

    # 1st failure → 10s, 2nd failure → 60s, 3rd failure → no more sleep
    assert sleep_calls == [10, 60]


@pytest.mark.asyncio
async def test_deliver_webhook_third_failure_marks_failed() -> None:
    """After 3 failures, failure_count is incremented on the webhook row."""
    update_calls: list = []

    class _FailResp:
        status = 503

        async def __aenter__(self) -> "_FailResp":
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

    class _FailSession:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def post(self, url: str, json: Any = None, headers: Any = None) -> _FailResp:  # type: ignore[override]
            return _FailResp()

        async def __aenter__(self) -> "_FailSession":
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

    mock_webhook = _make_webhook(failure_count=2)

    def _mock_update(wid: str, data: dict) -> Webhook:
        update_calls.append((wid, data))
        return mock_webhook

    with (
        patch("apps.worker.tasks.deliver_webhook.aiohttp.ClientSession", _FailSession),
        patch("apps.worker.tasks.deliver_webhook.asyncio.sleep", new_callable=AsyncMock),
        patch("apps.worker.tasks.deliver_webhook.get_webhook", return_value=mock_webhook),
        patch("apps.worker.tasks.deliver_webhook.update_webhook", _mock_update),
        patch("apps.worker.tasks.deliver_webhook._send_telegram_alert", new_callable=AsyncMock),
    ):
        await task_deliver_webhook(
            {},
            _WEBHOOK_ID,
            _WEBHOOK_URL,
            _SECRET_ENC,
            "otp.sent",
            {},
        )

    # failure_count should be incremented (2 + 1 = 3)
    assert any("failure_count" in data for _, data in update_calls)
    count_updates = [data["failure_count"] for _, data in update_calls if "failure_count" in data]
    assert count_updates == [3]


# ===========================================================================
# 10. 3rd failure fires Telegram alert
# ===========================================================================

@pytest.mark.asyncio
async def test_deliver_webhook_third_failure_fires_telegram_alert() -> None:
    """After 3 delivery failures, a Telegram alert is sent."""

    class _FailResp:
        status = 500

        async def __aenter__(self) -> "_FailResp":
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

    class _FailSession:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def post(self, url: str, json: Any = None, headers: Any = None) -> _FailResp:  # type: ignore[override]
            return _FailResp()

        async def __aenter__(self) -> "_FailSession":
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

    mock_webhook = _make_webhook()
    telegram_calls: list = []

    async def _mock_telegram(msg: str) -> None:
        telegram_calls.append(msg)

    with (
        patch("apps.worker.tasks.deliver_webhook.aiohttp.ClientSession", _FailSession),
        patch("apps.worker.tasks.deliver_webhook.asyncio.sleep", new_callable=AsyncMock),
        patch("apps.worker.tasks.deliver_webhook.get_webhook", return_value=mock_webhook),
        patch("apps.worker.tasks.deliver_webhook.update_webhook", return_value=mock_webhook),
        patch(
            "apps.worker.tasks.deliver_webhook._send_telegram_alert",
            side_effect=_mock_telegram,
        ),
    ):
        await task_deliver_webhook(
            {},
            _WEBHOOK_ID,
            _WEBHOOK_URL,
            _SECRET_ENC,
            "otp.sent",
            {},
        )

    assert len(telegram_calls) == 1
    assert _WEBHOOK_ID in telegram_calls[0]
    assert "[MailGuard]" in telegram_calls[0]


# ===========================================================================
# 11. Delivery timeout counts as failure
# ===========================================================================

@pytest.mark.asyncio
async def test_deliver_webhook_timeout_counts_as_failure() -> None:
    """A timeout (aiohttp.ServerTimeoutError) on POST counts as a failure."""
    import aiohttp

    attempt_count = 0

    class _TimeoutSession:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def post(self, url: str, json: Any = None, headers: Any = None) -> Any:  # type: ignore[override]
            class _TimeoutContext:
                async def __aenter__(self) -> "_TimeoutContext":
                    nonlocal attempt_count
                    attempt_count += 1
                    raise aiohttp.ServerTimeoutError()

                async def __aexit__(self, *args: Any) -> bool:
                    return False

            return _TimeoutContext()

        async def __aenter__(self) -> "_TimeoutSession":
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

    telegram_calls: list = []
    mock_webhook = _make_webhook()

    async def _mock_telegram(msg: str) -> None:
        telegram_calls.append(msg)

    with (
        patch("apps.worker.tasks.deliver_webhook.aiohttp.ClientSession", _TimeoutSession),
        patch("apps.worker.tasks.deliver_webhook.asyncio.sleep", new_callable=AsyncMock),
        patch("apps.worker.tasks.deliver_webhook.get_webhook", return_value=mock_webhook),
        patch("apps.worker.tasks.deliver_webhook.update_webhook", return_value=mock_webhook),
        patch(
            "apps.worker.tasks.deliver_webhook._send_telegram_alert",
            side_effect=_mock_telegram,
        ),
    ):
        await task_deliver_webhook(
            {},
            _WEBHOOK_ID,
            _WEBHOOK_URL,
            _SECRET_ENC,
            "otp.sent",
            {},
        )

    # All 3 attempts were made (all timed out)
    assert attempt_count == 3
    # Telegram alert fired after permanent failure
    assert len(telegram_calls) == 1
