from fastapi import APIRouter
from fastapi.responses import JSONResponse
from core.config import settings
import redis.asyncio as aioredis

router = APIRouter()


@router.get("/health")
async def health_check() -> JSONResponse:
    db_ok = False
    redis_ok = False

    # Check Supabase connectivity (simple HTTP ping via supabase client)
    try:
        from supabase import create_client

        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        # Lightweight query — just checks connectivity
        client.table("sender_emails").select("id").limit(1).execute()
        db_ok = True
    except Exception:
        db_ok = False

    # Check Redis connectivity
    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await r.ping()  # type: ignore[misc]
        await r.aclose()
        redis_ok = True
    except Exception:
        redis_ok = False

    status = "ok" if (db_ok and redis_ok) else "degraded"
    return JSONResponse(
        content={"status": status, "db": db_ok, "redis": redis_ok},
        status_code=200,
    )
