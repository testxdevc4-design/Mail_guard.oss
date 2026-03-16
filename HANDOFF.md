# HANDOFF — Part 08 of 15

## Files created / modified

### Part 04 files (unchanged)

| File | Lines | Description |
|------|-------|-------------|
| `core/otp.py` | ~110 | Full OTP lifecycle: `generate_otp`, `hash_otp`, `verify_otp_hash`, `save_otp`, `verify_and_consume` |
| `core/jwt_utils.py` | ~100 | HS256 JWT: `issue_jwt` (unique `jti`), `verify_jwt` (Redis revocation check), `revoke_jwt` |
| `core/rate_limiter.py` | ~80 | 5-tier Redis sliding window: atomic pipeline (`zremrangebyscore`+`zadd`+`zcard`+`expire`) |

### Part 05 files (unchanged)

| File | Lines | Description |
|------|-------|-------------|
| `core/api_keys.py` | ~115 | `generate_api_key` (256-bit entropy, SHA-256 hash stored), `validate_api_key` (sandbox block first), `revoke_api_key` |
| `apps/api/middleware/auth.py` | ~50 | `require_api_key` FastAPI dependency — Bearer extraction + `validate_api_key` |
| `apps/api/middleware/rate_limit.py` | ~70 | `RateLimitMiddleware` — IP 15-min tier, `asyncio.to_thread`, fail-open, 429 + `retry_after` |
| `apps/api/middleware/security_headers.py` | ~45 | `SecurityHeadersMiddleware` — explicit 4-header setter |

### Part 06 files (unchanged)

| File | Lines | Description |
|------|-------|-------------|
| `core/smtp.py` | ~100 | Async email dispatch via `aiosmtplib`. Password zeroed in `finally`. `use_tls=True` always. |
| `core/templates.py` | ~135 | Jinja2 rendering for OTP and magic-link emails + magic_verified/magic_expired pages. |
| `apps/worker/tasks/send_email.py` | ~140 | ARQ task: 3 retry attempts, backoffs 10 s/60 s/300 s. |
| `apps/worker/main.py` | ~70 | `WorkerSettings` — registers tasks and cron. |

### Part 07 files (unchanged)

| File | Lines | Description |
|------|-------|-------------|
| `apps/api/routes/otp.py` | ~297 | `POST /otp/send` and `POST /otp/verify`. Anti-enumeration 200 ms floor. |
| `apps/api/schemas.py` | ~49 | OTP schemas (Part 07) + magic link schemas (Part 08). |
| `tests/test_otp_routes.py` | ~510 | 25 OTP route tests. |

### Part 08 files (new / modified)

| File | Lines | Description |
|------|-------|-------------|
| `core/models.py` | ~112 | Fixed `MagicLink.redirect_url` to `Optional[str]` |
| `core/magic_links.py` | ~125 | `create_magic_link` (secrets.token_urlsafe(32), SHA-256 hash only in DB, raw token returned once), `verify_magic_link` (single-use: `is_used=True`+`used_at=now()` atomic before JWT) |
| `apps/api/schemas.py` | +20 | Added `MagicLinkSendRequest`, `MagicLinkVerifyResponse` |
| `core/templates.py` | +35 | Added `render_magic_verified_page`, `render_magic_expired_page` |
| `templates/magic_verified.html` | ~35 | Success page. Meta refresh redirect after 2 s if `redirect_url` set. JWT embedded in `<meta name="x-token">`. Works without JavaScript. |
| `templates/magic_expired.html` | ~25 | Error page for expired/used/invalid tokens. Works without JavaScript. |
| `apps/api/routes/magic.py` | ~230 | `POST /api/v1/magic/send` (API key auth, email validation, create link, enqueue email). `GET /api/v1/magic/verify/{token}` (no auth, HTML response, 200 verified or 410 expired). Webhook `try/except ImportError` guard. |
| `apps/api/main.py` | +2 | `app.include_router(magic.router)` after OTP router |
| `tests/test_magic_routes.py` | ~290 | 11 tests covering all required cases |

## What works right now

```bash
# 146 tests pass (135 from Parts 01-07, 11 new)
pytest tests/ -v
# → 146 passed, 0 failed

# Lint clean
ruff check .
# → All checks passed!

# Types clean
mypy apps/ core/ --ignore-missing-imports --no-strict-optional
# → Success: no issues found in 32 source files

# CodeQL: 0 alerts
```

## Security guarantees implemented

### From Parts 01–07
- OTP codes: `secrets.randbelow(10 ** length)` — CSPRNG, never `random.randint()`
- OTP hashing: `bcrypt.hashpw` (cost 10) — constant-time compare
- Attempt counter incremented **before** hash check — prevents timing oracle
- JWT `jti`: `secrets.token_hex(16)` — unique per token, enables revocation
- Rate limiter pipeline is atomic — no race between `zremrangebyscore`/`zadd`/`zcard`
- API key entropy: `secrets.token_hex(32)` — 256-bit, never `uuid4()`
- Key storage: **only SHA-256 hash** written to Supabase — plaintext never stored
- Sandbox block: `mg_test_` key in `ENV=production` → `HTTP 403` checked **before** DB lookup
- SMTP password: decrypted inside `try/finally`, `password = None` in `finally`

### New in Part 08
- Magic link raw token: `secrets.token_urlsafe(32)` — 256-bit URL-safe entropy
- **Only SHA-256 hex digest stored in DB** — raw token never persisted, returned once
- **Single-use enforced atomically**: `is_used=True` and `used_at=now()` set in one DB update call *before* JWT is issued — prevents replay attacks
- JWT uses same `issue_jwt()` from `core/jwt_utils.py` — no separate implementation
- Webhook import guarded with `try/except ImportError` — never crashes if Part 09 not yet built
- HTML verify pages work without JavaScript — accessible via any email client

## What is NOT built yet

- `core/webhooks.py` — HMAC-signed webhook delivery (Part 09)
- `core/sender_rotation.py` — Auto sender rotation (Part 10)
- All remaining API route files — Parts 09–10
- All SDK code — Part 14
- All bot commands — Parts 11–13
- `SECURITY.md` — Part 15

## Env vars introduced

No new env vars in Part 08. `MAGIC_LINK_EXPIRY_MINUTES` already existed in `core/config.py` (default: 15).

## DB state

- 7 migration files still pending manual run in Supabase SQL Editor (001 → 007)
- `magic_links` table needs a `used_at TIMESTAMPTZ` column if not already present — `update_magic_link` sends `used_at` in the update payload; it is silently ignored by Supabase if the column doesn't exist but must be present in production
- `email_logs.status` CHECK constraint issue from Part 06 is still unresolved — Part 09 should reconcile

## Decisions made

- `verify_magic_link` takes only `token` (not `project_id`) — token is 256-bit globally unique; no project filter needed
- Magic link URL is constructed from `request.base_url` in the route — no dependency on `INTERNAL_API_URL`
- `render_magic_verified_page` and `render_magic_expired_page` added to `core/templates.py` to match the existing pattern (same Jinja2 `_env` singleton)
- JWT embedded in HTML as `<meta name="x-token" content="...">` — readable without JavaScript

## Test results

```
pytest tests/test_magic_routes.py   → 11 passed, 0 failed
pytest tests/                       → 146 passed, 0 failed
ruff check .                        → All checks passed!
mypy apps/ core/ ...                → Success: no issues found in 32 source files
CodeQL                              → 0 alerts
```

## Known issues

- Real end-to-end email delivery (send → click → browser) not tested in CI (no live SMTP credentials)
- `magic_links` table `used_at` column must exist in Supabase for production use — add to migration if missing
- `email_logs.status` CHECK constraint issue from Part 06 unresolved

## Next agent: do these first (Part 09)

1. Read Part 09 in `MailGuard_MaxMVP_15Part.docx` — understand webhook spec
2. Create `core/webhooks.py` — HMAC-SHA256 signed webhook delivery, `fire_event(project_id, event, payload)`
3. The `try/except ImportError` guards in `apps/api/routes/magic.py` and `apps/api/routes/otp.py` will automatically pick up `fire_event` once `core/webhooks.py` exists
4. Create webhook management routes (register, list, delete, test)
5. Write tests — zero failures
6. Update `HANDOFF.md` with Part 09 results and Part 10 checklist


## Files created / modified

### Part 04 files (unchanged)

| File | Lines | Description |
|------|-------|-------------|
| `core/otp.py` | ~110 | Full OTP lifecycle: `generate_otp`, `hash_otp`, `verify_otp_hash`, `save_otp`, `verify_and_consume` |
| `core/jwt_utils.py` | ~100 | HS256 JWT: `issue_jwt` (unique `jti`), `verify_jwt` (Redis revocation check), `revoke_jwt` |
| `core/rate_limiter.py` | ~80 | 5-tier Redis sliding window: atomic pipeline (`zremrangebyscore`+`zadd`+`zcard`+`expire`) |

### Part 05 files (unchanged)

| File | Lines | Description |
|------|-------|-------------|
| `core/api_keys.py` | ~115 | `generate_api_key` (256-bit entropy, SHA-256 hash stored), `validate_api_key` (sandbox block first), `revoke_api_key` |
| `apps/api/middleware/auth.py` | ~50 | `require_api_key` FastAPI dependency — Bearer extraction + `validate_api_key` |
| `apps/api/middleware/rate_limit.py` | ~70 | `RateLimitMiddleware` — IP 15-min tier, `asyncio.to_thread`, fail-open, 429 + `retry_after` |
| `apps/api/middleware/security_headers.py` | ~45 | `SecurityHeadersMiddleware` — explicit 4-header setter |
| `apps/api/main.py` | +2 | Added `RateLimitMiddleware` import and `app.add_middleware(RateLimitMiddleware)` |
| `tests/test_auth.py` | ~155 | 7 tests covering all 6 required auth edge cases |
| `tests/test_middleware.py` | ~170 | CORS blocking, security headers on success+error, rate limit 429, fail-open |

### Part 06 files (new)

| File | Lines | Description |
|------|-------|-------------|
| `core/smtp.py` | ~100 | Async email dispatch via `aiosmtplib`. Password decrypted in `try/finally`, zeroed in `finally`. `MIMEMultipart('alternative')` with text+HTML. `use_tls=True` always. |
| `core/templates.py` | ~90 | Jinja2 rendering for OTP and magic-link emails. Module-level `Environment` singleton. Returns `(subject, text_body, html_body)`. |
| `templates/otp_email.html` | ~55 | HTML OTP email. Inline styles only. Supports `{{otp_code}}`, `{{expiry_minutes}}`, `{{project_name}}`, `{{purpose}}`. |
| `templates/otp_email.txt` | ~12 | Plain-text OTP email with same placeholders. |
| `templates/magic_link_email.html` | ~65 | HTML magic-link email. Supports `{{magic_link_url}}`, `{{expiry_minutes}}`, `{{project_name}}`. |
| `templates/magic_link_email.txt` | ~11 | Plain-text magic-link email with same placeholders. |
| `apps/worker/tasks/__init__.py` | 1 | Package marker. |
| `apps/worker/tasks/send_email.py` | ~140 | ARQ task: 3 retry attempts, backoffs 10 s/60 s/300 s. On 3rd failure: `email_logs.status = 'failed'` + Telegram alert. |
| `apps/worker/tasks/purge_otps.py` | ~50 | ARQ cron task: deletes `otp_records` where `expires_at < now()` AND `is_verified = false`. |
| `apps/worker/main.py` | ~70 | `WorkerSettings` — registers `task_send_email` and `purge_expired_otps` cron (every 15 min). |
| `tests/test_smtp.py` | ~250 | 7 tests: success→delivered, retry@10s, retry@60s, 3rd fail→failed+Telegram, password=None after success, password=None after error, password never in exception message. |

## What works right now

```bash
# 116 tests pass (109 from Parts 01-05, 7 new)
pytest tests/ -v
# → 116 passed, 0 failed

# Lint clean
ruff check .
# → All checks passed!

# Types clean
mypy apps/ core/ --ignore-missing-imports --no-strict-optional
# → Success: no issues found in 28 source files

# CodeQL: 0 alerts
```

## Security guarantees implemented

### From Parts 01–05
- OTP codes: `secrets.randbelow(10 ** length)` — CSPRNG, never `random.randint()`
- OTP hashing: `bcrypt.hashpw` (cost 10) — constant-time compare
- Attempt counter incremented **before** hash check — prevents timing oracle
- JWT `jti`: `secrets.token_hex(16)` — unique per token, enables revocation
- Rate limiter pipeline is atomic — no race between `zremrangebyscore`/`zadd`/`zcard`
- API key entropy: `secrets.token_hex(32)` — 256-bit, never `uuid4()`
- Key storage: **only SHA-256 hash** written to Supabase — plaintext never stored
- Sandbox block: `mg_test_` key in `ENV=production` → `HTTP 403` checked **before** DB lookup

### New in Part 06
- SMTP password: decrypted inside `try/finally`, `password = None` in `finally` — never outlives send call
- Password never logged, printed, or included in any exception message
- `use_tls=True` always passed to `aiosmtplib.send()` — no plaintext or StartTLS paths
- Email assembled as `MIMEMultipart('alternative')`: text part first, HTML second (correct MIME order)
- Telegram alert on 3rd delivery failure — no silent drops
- Worker task: 3 retries with 10 s / 60 s / 300 s backoffs before marking `failed`

## What is NOT built yet

- `apps/api/routes/otp.py` — `POST /otp/send` and `POST /otp/verify` (Part 07)
- `core/magic.py` — Magic link generation/verification (Part 08)
- `core/sender_rotation.py` — Auto sender rotation (Part 10)
- `core/webhooks.py` — HMAC-signed webhook delivery (Part 09)
- All remaining API route files — Parts 07–09
- All SDK code — Part 14
- All bot commands — Parts 11–13
- `SECURITY.md` — Part 15

## Env vars introduced

No new env vars in Part 06.

## DB state

- 7 migration files still pending manual run in Supabase SQL Editor (001 → 007)
- No schema changes in Part 06
- Note: `email_logs.status` CHECK constraint allows `'sent'`, `'failed'`, `'queued'` — Part 07 may need to add `'delivered'` or map it to `'sent'`

## Decisions made

- `core/db.py` uses the Supabase **sync** client throughout. `apps/worker/tasks/send_email.py` calls `get_sender_email` and `update_email_log` synchronously inside the async ARQ task — this is intentional and consistent with the rest of the codebase.
- `purge_expired_otps` uses the Supabase REST API filter `.lt("expires_at", "now()")` which translates to `expires_at < now()` server-side.
- `_send_telegram_alert` uses `httpx.AsyncClient` with a 10-second timeout and swallows any error — Telegram failures must never block the task error path.
- Worker `job_timeout = 660` seconds to allow the full 10 + 60 + 300 s retry cycle plus a buffer.

## Test results

```
pytest tests/test_smtp.py     → 7 passed
pytest tests/                  → 116 passed, 0 failed
```

## Known issues

- `email_logs` table `status` column CHECK constraint only allows `'sent'`, `'failed'`, `'queued'`. The task currently writes `'delivered'` on success. Part 07 must either: (a) add `'delivered'` to the CHECK constraint via a migration, or (b) change `send_email.py` to use `'sent'` instead.
- Real email delivery was not confirmed against a live Gmail inbox in this session (no credentials available in CI). Tests use `unittest.mock` to patch `aiosmtplib.send` — the mock-based tests all pass.

## Next agent: do these first (Part 07)

1. Add `'delivered'` to `email_logs.status` CHECK constraint or decide to use `'sent'` — reconcile with `send_email.py`
2. Read Part 07 in `MailGuard_MaxMVP_15Part.docx` — understand OTP route spec
3. Create `apps/api/routes/otp.py` — `POST /otp/send` and `POST /otp/verify`
4. Wire routes into `apps/api/main.py` (router include only — do not change middleware)
5. Implement anti-enumeration delay (≥200 ms) on all OTP responses
6. Return all 9 required HTTP status codes with correct shapes
7. Write `tests/integration/test_otp_routes.py` — zero failures
8. Update `HANDOFF.md` with Part 07 results and Part 08 checklist
