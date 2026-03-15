"""
Part 02 smoke tests — verifies FastAPI app factory and security headers.
Full test suites are added in Parts 03–15.
"""
import os
import pytest
import pytest_asyncio

# Set required env vars before importing app modules
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")


@pytest.fixture
def app():
    from apps.api.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(app):
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_returns_200(client):
    r = await client.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_health_response_shape(client):
    r = await client.get("/health")
    body = r.json()
    assert "status" in body
    assert "db" in body
    assert "redis" in body
    assert body["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_security_headers_present(client):
    r = await client.get("/health")
    assert r.headers.get("x-frame-options") == "SAMEORIGIN"
    assert r.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_request_id_generated(client):
    r = await client.get("/health")
    assert r.headers.get("x-request-id")


@pytest.mark.asyncio
async def test_request_id_preserved(client):
    r = await client.get("/health", headers={"X-Request-ID": "my-trace-id"})
    assert r.headers.get("x-request-id") == "my-trace-id"


@pytest.mark.asyncio
async def test_docs_url_in_development(app):
    """Docs should be available in development mode."""
    assert app.docs_url == "/docs"


def test_cors_origins_not_wildcard(app):
    """ALLOWED_ORIGINS should never be ['*'] — must be explicitly set."""
    from core.config import settings

    assert "*" not in settings.ALLOWED_ORIGINS
