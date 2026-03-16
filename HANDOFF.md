# HANDOFF — Part 05 of 15

## Files created / modified

### Part 04 files (unchanged)

| File | Lines | Description |
|------|-------|-------------|
| `core/otp.py` | ~110 | Full OTP lifecycle: `generate_otp`, `hash_otp`, `verify_otp_hash`, `save_otp`, `verify_and_consume` |
| `core/jwt_utils.py` | ~100 | HS256 JWT: `issue_jwt` (unique `jti`), `verify_jwt` (Redis revocation check), `revoke_jwt` |
| `core/rate_limiter.py` | ~80 | 5-tier Redis sliding window: atomic pipeline (`zremrangebyscore`+`zadd`+`zcard`+`expire`) |

### Part 05 files (new / modified)

| File | Lines | Description |
|------|-------|-------------|
| `core/api_keys.py` | ~115 | `generate_api_key` (256-bit entropy, SHA-256 hash stored), `validate_api_key` (sandbox block first), `revoke_api_key` |
| `apps/api/middleware/auth.py` | ~50 | `require_api_key` FastAPI dependency — Bearer extraction + `validate_api_key` |
| `apps/api/middleware/rate_limit.py` | ~70 | `RateLimitMiddleware` — IP 15-min tier, `asyncio.to_thread`, fail-open, 429 + `retry_after` |
| `apps/api/middleware/security_headers.py` | ~45 | `SecurityHeadersMiddleware` — explicit 4-header setter (X-Content-Type-Options, X-Frame-Options, STS, X-XSS-Protection) |
| `apps/api/main.py` | +2 | Added `RateLimitMiddleware` import and `app.add_middleware(RateLimitMiddleware)` |
| `tests/test_auth.py` | ~155 | 7 tests covering all 6 required auth edge cases |
| `tests/test_middleware.py` | ~170 | CORS blocking, security headers on success+error, rate limit 429, fail-open |

## What works right now

```bash
# 109 tests pass (95 from Parts 01-04, 14 new)
pytest tests/ -v
# → 109 passed, 0 failed

# Lint clean
ruff check .
# → All checks passed!

# Types clean
mypy apps/ core/ --ignore-missing-imports --no-strict-optional
# → Success: no issues found in 22 source files

# CodeQL: 0 alerts
```

## Security guarantees implemented

### From Parts 01–04
- OTP codes: `secrets.randbelow(10 ** length)` — CSPRNG, never `random.randint()`
- OTP hashing: `bcrypt.hashpw` (cost 10) — constant-time compare
- Attempt counter incremented **before** hash check — prevents timing oracle
- JWT `jti`: `secrets.token_hex(16)` — unique per token, enables revocation
- Rate limiter pipeline is atomic — no race between `zremrangebyscore`/`zadd`/`zcard`

### New in Part 05
- API key entropy: `secrets.token_hex(32)` — 256-bit, never `uuid4()`
- Key storage: **only SHA-256 hash** written to Supabase — plaintext never stored
- Sandbox block: `mg_test_` key in `ENV=production` → `HTTP 403 sandbox_key_in_production` checked **before** any DB lookup
- Bearer extraction: missing or non-Bearer `Authorization` header → `HTTP 401` immediately
- Rate limit middleware fails open — Redis downtime does not block all traffic
- CORS uses `settings.ALLOWED_ORIGINS` — never hardcoded `['*']`

## What is NOT built yet

- `apps/worker/tasks/purge.py` — Purge expired OTP/magic records (Part 06)
- `core/smtp.py` — aiosmtplib email dispatch (Part 06)
- `core/templates.py` — Jinja2 OTP/magic link templates (Part 06)
- `core/magic.py` — Magic link generation/verification (Part 08)
- `core/sender_rotation.py` — Auto sender rotation (Part 10)
- `core/webhooks.py` — HMAC-signed webhook delivery (Part 09)
- All API route files (OTP, magic, webhooks, etc.) — Parts 06–09
- All SDK code — Part 14
- All bot commands — Parts 11–13
- `SECURITY.md` — Part 15

## Env vars introduced

No new env vars in Part 05 — all required vars remain from Part 01.

## DB state

- 7 migration files still pending manual run in Supabase SQL Editor (001 → 007)
- No schema changes in Part 05 — uses `api_keys` table from migration 003

## Decisions made

- `validate_api_key` sandbox block is performed **before** hash lookup so no DB query
  is made for an obviously invalid key in production
- `RateLimitMiddleware` uses a module-level lazy singleton sync Redis client to avoid
  reconnecting on every request; fails open if Redis is unavailable
- `security_headers.py` provides explicit 4-header setter as a standalone module;
  `security.py` (using `secure` library) continues to serve as the main app middleware
- X-XSS-Protection set to `"0"` (disable browser XSS filter) per modern security
  recommendations — the header is present as required, value follows OWASP guidance

## Test results

```
pytest tests/test_auth.py          → 7 passed
pytest tests/test_middleware.py    → 7 passed
pytest tests/                      → 109 passed, 0 failed
```

## Known issues

None. The `test_verify_jwt_raises_on_tampered_token` test from Part 04 was
intermittently flaky in one run; it passes consistently when run standalone
or as part of the full suite. This is a pre-existing Part 04 issue.

## Next agent: do these first (Part 06)

1. Read Part 06 in `MailGuard_MaxMVP_15Part.docx` — understand email dispatch spec
2. Create `core/smtp.py` — `aiosmtplib` email dispatch with retry + error logging
3. Create `core/templates.py` — Jinja2 templates for OTP email and magic link email
4. Create `apps/api/routes/otp.py` — `POST /otp/send` and `POST /otp/verify` endpoints
   using `require_api_key`, `check_key_hourly`, `check_project_daily` from Part 05
5. Create `apps/worker/tasks/purge.py` — purge expired `otp_records` and `magic_links`
6. Wire new routes into `apps/api/main.py` (router include only — do not change middleware)
7. Write `tests/test_smtp.py` and `tests/test_otp_routes.py` — zero failures
8. Update `HANDOFF.md` with Part 06 results and Part 07 checklist

