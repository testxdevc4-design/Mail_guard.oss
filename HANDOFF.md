# HANDOFF — Part 01 of 15

## Files created / modified

| File | Description |
|------|-------------|
| `core/__init__.py` | Empty package init |
| `core/config.py` | Pydantic v2 BaseSettings — validates ENCRYPTION_KEY (64 hex chars), JWT_SECRET (≥64 chars), all required env vars on import |
| `apps/__init__.py` | Empty package init |
| `apps/api/__init__.py` | Empty package init |
| `apps/api/routes/__init__.py` | Empty package init |
| `apps/api/middleware/__init__.py` | Empty package init |
| `apps/worker/__init__.py` | Empty package init |
| `apps/bot/__init__.py` | Empty package init |
| `tests/__init__.py` | Empty package init |
| `tests/unit/__init__.py` | Empty package init |
| `tests/integration/__init__.py` | Empty package init |
| `db/migrations/001_sender_emails.sql` | sender_emails table — SMTP accounts with encrypted app passwords |
| `db/migrations/002_projects.sql` | projects table — per-integration config with OTP settings and email templates |
| `db/migrations/003_api_keys.sql` | api_keys table — SHA-256 key hash only, no plaintext |
| `db/migrations/004_otp_records.sql` | otp_records table — OTP lifecycle, bcrypt hash, attempt counter |
| `db/migrations/005_magic_links.sql` | magic_links table — single-use tokens stored as SHA-256 hash |
| `db/migrations/006_webhooks.sql` | webhooks table — developer webhook URLs with encrypted signing secrets |
| `db/migrations/007_email_logs.sql` | email_logs table — immutable audit log, recipient stored as HMAC hash |
| `requirements.txt` | All Python dependencies for api, worker, bot + SDK dev tools |
| `.env.example` | Every environment variable with generation commands and descriptions |
| `docker-compose.yml` | api + worker + bot + redis for local development |
| `Dockerfile.api` | API service Dockerfile — python:3.12-slim, non-root user |
| `Dockerfile.worker` | Worker service Dockerfile — python:3.12-slim, non-root user |
| `Dockerfile.bot` | Bot service Dockerfile — python:3.12-slim, non-root user |
| `railway.toml` | Railway deployment config — 3 services: api, worker, bot |

## What works right now

```bash
# Verify settings load with valid env vars
python -c "
import os
os.environ.update({
  'SUPABASE_URL': 'https://test.supabase.co',
  'SUPABASE_SERVICE_ROLE_KEY': 'key',
  'REDIS_URL': 'rediss://x:x@host:6379',
  'ENCRYPTION_KEY': 'a' * 64,
  'JWT_SECRET': 'b' * 64,
  'TELEGRAM_BOT_TOKEN': 'tok',
  'TELEGRAM_ADMIN_UID': '1',
})
from core.config import Settings; s = Settings(); print(s.ENV)
"

# Verify bad key raises immediately
python -c "from core.config import Settings; Settings(ENCRYPTION_KEY='short')"
# → raises pydantic_core.ValidationError (contains ValueError: ENCRYPTION_KEY must be 64 hex chars)
```

## What is NOT built yet

- `apps/api/main.py` — FastAPI app factory (Part 02)
- `apps/api/routes/health.py` — /health endpoint (Part 02)
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
- All SDK code — Part 14
- All bot commands — Parts 11–13
- All tests — Parts 03–15
- `SECURITY.md` — Part 15

## Env vars introduced

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service role key from Supabase dashboard>
REDIS_URL=rediss://default:<token>@<host>.upstash.io:6379
ENCRYPTION_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
JWT_SECRET=<python -c "import secrets; print(secrets.token_hex(64))">
JWT_EXPIRY_MINUTES=10
MAGIC_LINK_EXPIRY_MINUTES=15
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_ADMIN_UID=<integer, from @userinfobot>
ENV=production
PORT=3000
ALLOWED_ORIGINS=
INTERNAL_API_URL=
ROTATION_THRESHOLD=0.80
```

## DB state

- 7 migration files created: `db/migrations/001–007.sql`
- **Migrations must be run manually in the Supabase SQL Editor before Part 02**
- Run each file in order: 001 → 002 → 003 → 004 → 005 → 006 → 007
- Verify with: `SELECT table_name FROM information_schema.tables WHERE table_schema='public'`
- Expected tables: `sender_emails`, `projects`, `api_keys`, `otp_records`, `magic_links`, `webhooks`, `email_logs`

## Decisions made

- Used `pydantic-settings` v2 `BaseSettings` with `@field_validator` decorators (not v1 `@validator`)
- `settings = Settings()` at module level — fails fast at process startup on bad config
- All Dockerfiles use `python:3.12-slim` with a non-root `appuser` for security
- `docker-compose.yml` uses 3 separate Dockerfiles (Dockerfile.api/worker/bot) matching the Railway 3-service layout
- `docker-compose.yml` uses `redis://redis:6379` (non-TLS) for local dev; production uses Upstash `rediss://` TLS URL
- SQL migrations use `IF NOT EXISTS` for idempotency
- `email_logs.type` uses CHECK constraint: `IN ('otp', 'magic')`
- `email_logs.status` uses CHECK constraint: `IN ('sent', 'failed', 'queued')`

## Next agent: do these first

1. Set up `.env` with real credentials (Supabase, Upstash Redis, Telegram)
2. Generate ENCRYPTION_KEY: `python -c "import secrets; print(secrets.token_hex(32))"`
3. Generate JWT_SECRET: `python -c "import secrets; print(secrets.token_hex(64))"`
4. Run all 7 SQL migrations in Supabase SQL Editor (001 → 007)
5. Verify all 7 tables: `SELECT table_name FROM information_schema.tables WHERE table_schema='public'`
6. Verify config: `python -c "from core.config import settings; print(settings.ENV)"`
7. Begin Part 02: create `apps/api/main.py`, `apps/api/routes/health.py`, Dockerfiles, Railway deploy, GitHub Actions CI
