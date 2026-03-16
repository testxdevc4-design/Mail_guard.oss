# HANDOFF — Part 03 of 15

## Files created / modified

| File | Lines | Description |
|------|-------|-------------|
| `requirements.txt` | 51 | Fixed httpx version: `0.27.0` → `0.26.0` (resolves `python-telegram-bot 20.8` conflict) |
| `core/models.py` | 111 | Dataclasses for all 7 tables: SenderEmail, Project, ApiKey, OtpRecord, MagicLink, Webhook, EmailLog |
| `core/crypto.py` | 84 | AES-256-GCM `encrypt()`/`decrypt()` + HMAC-SHA256 `hmac_email()` with email normalisation |
| `core/redis_client.py` | 50 | Async Redis connection pool via `redis.asyncio`; `get_redis()`, `close_redis()`, `arq_redis_settings()` |
| `core/db.py` | 497 | Supabase SERVICE ROLE KEY client + typed CRUD helpers for all 7 tables |
| `tests/test_crypto.py` | 153 | 15 tests: 500-string round-trip, unique IVs, unicode, tamper detection, wrong-key, HMAC normalisation |
| `tests/test_db.py` | 460 | 30 tests: insert/select/update for all 7 tables using mocked Supabase client |

## What works right now

```bash
# All 52 tests pass
pytest tests/ -v
# → 52 passed, 3 warnings

# Lint clean
ruff check .
# → Found 0 errors

# Types clean
mypy apps/ core/ --ignore-missing-imports --no-strict-optional
# → Success: no issues found in 15 source files

# encrypt/decrypt round-trip confirmed
python -c "
import os; os.environ.update({'SUPABASE_URL':'https://t.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'k','REDIS_URL':'redis://localhost:6379','ENCRYPTION_KEY':'a'*64,'JWT_SECRET':'b'*64,'TELEGRAM_BOT_TOKEN':'t:t','TELEGRAM_ADMIN_UID':'1'})
from core.crypto import encrypt, decrypt, hmac_email
assert decrypt(encrypt('hello')) == 'hello'
assert hmac_email('User@Example.com') == hmac_email('user@example.com')
print('ALL OK')
"
```

## What is NOT built yet

- `apps/worker/main.py` — ARQ WorkerSettings (Part 06)
- `apps/bot/main.py` — Telegram bot entry point (Part 11)
- `core/otp.py` — OTP generation/verification lifecycle (Part 04)
- `core/magic.py` — Magic link generation/verification (Part 08)
- `core/jwt_utils.py` — JWT issue/verify (Part 04)
- `core/smtp.py` — aiosmtplib email dispatch (Part 06)
- `core/templates.py` — Jinja2 OTP/magic link templates (Part 06)
- `core/sender_rotation.py` — Auto sender rotation (Part 10)
- `core/webhooks.py` — HMAC-signed webhook delivery (Part 09)
- `core/api_keys.py` — Key generation and validation (Part 05)
- All API route files (OTP, magic, webhooks, etc.) — Parts 05–09
- All SDK code — Part 14
- All bot commands — Parts 11–13
- `SECURITY.md` — Part 15

## Env vars introduced

No new env vars in Part 03 — all vars remain from Part 01.

## DB state

- 7 migration files still pending manual run in Supabase SQL Editor (001 → 007)
- No schema changes in Part 03

## Decisions made

- `httpx` pinned to `0.26.0` (not `0.27.0`) — `python-telegram-bot 20.8` requires `httpx~=0.26.0`
- AES-256-GCM token format: `base64url(iv):base64url(ciphertext+tag)` — `:` as separator
- IV is 12 bytes (96-bit) — GCM recommended nonce size; fresh random IV per call
- `hmac_email()` uses `hmac.new(key, email.encode(), sha256)` after `.strip().lower()` normalisation
- `core/db.py` uses a module-level singleton client (service-role key); never the anon key
- `tests/test_db.py` mocks the Supabase client so CI passes without a live Supabase instance
- Both new test files set `os.environ.setdefault("ENV", "development")` to ensure the pre-existing `test_docs_url_in_development` test keeps passing when tests run in alphabetical order
- Note: build guide mentions "8 tables" but migrations define 7; all 7 are covered

## Test results

```
pytest tests/test_crypto.py  → 15 passed
pytest tests/test_db.py      → 30 passed
pytest tests/                → 52 passed, 0 failed
```

## Known issues

None.

## Next agent: do these first

1. Set up `.env` with real credentials (Supabase, Upstash Redis, Telegram)
2. Run all 7 SQL migrations in Supabase SQL Editor (001 → 007)
3. Deploy to Railway and confirm `/health` returns `{status:ok,db:true,redis:true}`
4. Add `RAILWAY_TOKEN` as a GitHub Actions secret for the deploy job
5. Begin Part 04: create `core/otp.py`, `core/jwt_utils.py`, and their tests

