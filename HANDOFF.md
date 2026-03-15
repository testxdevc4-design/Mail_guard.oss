# HANDOFF — Part 02 of 15

## Files created / modified

| File | Description |
|------|-------------|
| `apps/api/main.py` | FastAPI app factory — CORS middleware, SecurityHeadersMiddleware, router registration, /docs only in development (~30 lines) |
| `apps/api/routes/health.py` | GET /health — checks Supabase + Redis connectivity, returns `{status, db, redis}` with 200 always (~40 lines) |
| `apps/api/middleware/security.py` | `SecurityHeadersMiddleware` — Secure() headers (X-Frame-Options, X-Content-Type-Options, HSTS, etc.), X-Request-ID passthrough/generation, X-Response-Time (~22 lines) |
| `apps/api/Dockerfile` | python:3.12-slim, non-root appuser, uvicorn CMD, EXPOSE 3000 (~10 lines) |
| `apps/worker/Dockerfile` | python:3.12-slim, non-root appuser, arq CMD, EXPOSE 3000 (~10 lines) |
| `apps/bot/Dockerfile` | python:3.12-slim, non-root appuser, python -m apps.bot.main CMD, EXPOSE 3000 (~10 lines) |
| `.github/workflows/ci.yml` | ruff + mypy + pytest on every push/PR; Railway deploy on main push; permissions: contents: read (~58 lines) |
| `core/config.py` | Added `# type: ignore[call-arg]` to `settings = Settings()` for mypy/pydantic-settings compatibility |

## What works right now

```bash
# Verify app creates and /health route exists
python -c "
import os
os.environ.update({
  'SUPABASE_URL': 'https://test.supabase.co',
  'SUPABASE_SERVICE_ROLE_KEY': 'key',
  'REDIS_URL': 'redis://localhost:6379',
  'ENCRYPTION_KEY': 'a' * 64,
  'JWT_SECRET': 'b' * 64,
  'TELEGRAM_BOT_TOKEN': 'tok',
  'TELEGRAM_ADMIN_UID': '1',
})
from apps.api.main import create_app
app = create_app()
print(app.title, [r.path for r in app.routes])
"
# → MailGuard OSS ['/openapi.json', '/health']

# Verify security headers work
python -c "
import os, asyncio
os.environ.update({
  'SUPABASE_URL': 'https://test.supabase.co',
  'SUPABASE_SERVICE_ROLE_KEY': 'key',
  'REDIS_URL': 'redis://localhost:6379',
  'ENCRYPTION_KEY': 'a' * 64,
  'JWT_SECRET': 'b' * 64,
  'TELEGRAM_BOT_TOKEN': 'tok',
  'TELEGRAM_ADMIN_UID': '1',
})
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
async def t():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        r = await c.get('/health')
        assert r.status_code == 200
        assert r.headers.get('x-frame-options') == 'SAMEORIGIN'
        assert r.headers.get('x-content-type-options') == 'nosniff'
        assert r.headers.get('x-request-id')
        print('ALL OK', r.json())
asyncio.run(t())
"
# → ALL OK {'status': 'degraded', 'db': False, 'redis': False}

# Lint: all checks passed
ruff check apps/ core/

# Types: no issues
mypy apps/ core/ --ignore-missing-imports --no-strict-optional
```

## What is NOT built yet

- `apps/worker/main.py` — ARQ WorkerSettings (Part 06)
- `apps/bot/main.py` — Telegram bot entry point (Part 11)
- `core/crypto.py` — AES-256-GCM encrypt/decrypt + HMAC email (Part 03)
- `core/db.py` — Supabase table helpers (Part 03)
- `core/otp.py` — OTP generation/verification lifecycle (Part 04)
- `core/magic.py` — Magic link generation/verification (Part 08)
- `core/jwt_utils.py` — JWT issue/verify (Part 04)
- `core/smtp.py` — aiosmtplib email dispatch (Part 06)
- `core/templates.py` — Jinja2 OTP/magic link templates (Part 06)
- `core/sender_rotation.py` — Auto sender rotation (Part 10)
- `core/webhooks.py` — HMAC-signed webhook delivery (Part 09)
- `core/redis_client.py` — Redis/ARQ connection pool (Part 06)
- `core/api_keys.py` — Key generation and validation (Part 05)
- All API route files (OTP, magic, webhooks, etc.) — Parts 05–09
- All SDK code — Part 14
- All bot commands — Parts 11–13
- All tests — Parts 03–15
- `SECURITY.md` — Part 15

## Env vars introduced

No new env vars in Part 02 — all vars remain from Part 01.

## DB state

- 7 migration files still pending manual run in Supabase SQL Editor (001 → 007)
- No schema changes in Part 02

## Decisions made

- Used `SecurityHeadersMiddleware` class (in `security.py`) added via `app.add_middleware()` instead of inline decorator — cleaner separation of concerns
- `secure.Secure().framework.fastapi(response)` sets: Strict-Transport-Security, X-Frame-Options (SAMEORIGIN), X-XSS-Protection (0), X-Content-Type-Options (nosniff), Referrer-Policy, Cache-Control
- `/health` always returns HTTP 200; `status` field is `"ok"` (both up) or `"degraded"` (one/both down) — never 503, so load balancers don't route away
- `SecurityHeadersMiddleware` preserves incoming `X-Request-ID` from clients/proxies for distributed tracing
- CI uses `--ignore-missing-imports --no-strict-optional` for mypy — sufficient for current scope
- Added `permissions: contents: read` to both CI jobs (CodeQL/security requirement)
- `core/config.py` `Settings()` call has `# type: ignore[call-arg]` — pydantic-settings reads from env vars, not constructor args; mypy doesn't understand this without the pydantic mypy plugin
- Dockerfiles follow the exact template from the guide (all 3 use same base pattern, EXPOSE 3000)

## Next agent: do these first

1. Set up `.env` with real credentials (Supabase, Upstash Redis, Telegram)
2. Run all 7 SQL migrations in Supabase SQL Editor (001 → 007)
3. Deploy to Railway and confirm `/health` returns `{status:ok,db:true,redis:true}`
4. Add `RAILWAY_TOKEN` as a GitHub Actions secret for the deploy job
5. Optionally add `ENCRYPTION_KEY` and `JWT_SECRET` as GitHub Actions secrets (fallback defaults are in CI for tests)
6. Begin Part 03: create `core/crypto.py`, `core/db.py`, `core/redis_client.py`, and their tests
