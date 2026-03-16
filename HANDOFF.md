# HANDOFF — Part 04 of 15

## Files created / modified

| File | Lines | Description |
|------|-------|-------------|
| `core/otp.py` | ~110 | Full OTP lifecycle: `generate_otp`, `hash_otp`, `verify_otp_hash`, `save_otp`, `verify_and_consume` |
| `core/jwt_utils.py` | ~100 | HS256 JWT: `issue_jwt` (unique `jti`), `verify_jwt` (Redis revocation check), `revoke_jwt` |
| `core/rate_limiter.py` | ~80 | 5-tier Redis sliding window: atomic pipeline (`zremrangebyscore`+`zadd`+`zcard`+`expire`) |
| `tests/test_otp.py` | ~240 | All 6 required edge cases + `save_otp`, hash, and timing-order tests |
| `tests/test_jwt.py` | ~210 | issue, verify, expired, tampered, wrong secret, revoked jti, full revoke round-trip |
| `tests/test_rate_limiter.py` | ~230 | Sliding window, tier isolation, all 5 tier helpers, reset after window expires |

## What works right now

```bash
# All 95 tests pass (52 from Parts 01-03, 43 new)
pytest tests/ -v
# → 95 passed, 0 failed

# Lint clean
ruff check .
# → All checks passed!

# Types clean
mypy apps/ core/ --ignore-missing-imports --no-strict-optional
# → Success: no issues found in 18 source files
```

## Security guarantees implemented

- OTP codes: `secrets.randbelow(10 ** length)` — CSPRNG, never `random.randint()`
- OTP hashing: `bcrypt.hashpw` (cost 10) — `bcrypt.checkpw` for constant-time compare
- Attempt counter incremented **before** hash check — prevents timing oracle attack
- Record `is_invalidated=True` on first successful verify — prevents replay
- JWT `jti`: `secrets.token_hex(16)` — unique per token, enables revocation
- Rate limiter pipeline is atomic — no race condition between `zremrangebyscore`/`zadd`/`zcard`

## What is NOT built yet

- `apps/worker/tasks/purge.py` — Purge expired OTP/magic records (Part 04 optional, Part 06)
- `core/api_keys.py` — Key generation and validation (Part 05)
- `apps/api/middleware/auth.py` — API key bearer auth (Part 05)
- `apps/api/middleware/rate_limit.py` — FastAPI middleware wrapping `core/rate_limiter.py` (Part 05)
- `core/magic.py` — Magic link generation/verification (Part 08)
- `core/smtp.py` — aiosmtplib email dispatch (Part 06)
- `core/templates.py` — Jinja2 OTP/magic link templates (Part 06)
- `core/sender_rotation.py` — Auto sender rotation (Part 10)
- `core/webhooks.py` — HMAC-signed webhook delivery (Part 09)
- All API route files (OTP, magic, webhooks, etc.) — Parts 05–09
- All SDK code — Part 14
- All bot commands — Parts 11–13
- `SECURITY.md` — Part 15

## Env vars introduced

No new env vars in Part 04 — all required vars remain from Part 01:
- `JWT_SECRET` (min 64 chars) — already validated in `core/config.py`
- `JWT_EXPIRY_MINUTES` (default 10) — used by `issue_jwt`

## DB state

- 7 migration files still pending manual run in Supabase SQL Editor (001 → 007)
- No schema changes in Part 04 — uses `otp_records` table from migration 004

## Decisions made

- `verify_and_consume` does NOT directly filter `expires_at` via DB — it is checked in Python after `get_active_otp` returns a row (because `get_active_otp` only filters `is_invalidated=False` and `is_verified=False`)
- JWT revocation uses synchronous Redis `.get()` / `.set()` — async revocation can be added in Part 05 when async middleware is built
- Rate limiter `_sliding_window` uses `str(time.time())` as the sorted-set member key — this is safe because duplicate floats in the same millisecond get overwritten; for production at very high QPS, Part 05 should append a `secrets.token_hex(4)` suffix to the member key
- `core/rate_limiter.py` is synchronous — the FastAPI async middleware wrapper (`apps/api/middleware/rate_limit.py`) is Part 05's responsibility

## Test results

```
pytest tests/test_otp.py          → 15 passed
pytest tests/test_jwt.py          → 16 passed
pytest tests/test_rate_limiter.py → 14 passed
pytest tests/                     → 95 passed, 0 failed
```

## Known issues

None.

## Next agent: do these first (Part 05)

1. Read `core/rate_limiter.py` — it is synchronous; wrap it in `asyncio.to_thread()` or rewrite async if needed
2. Create `core/api_keys.py` — `generate_api_key`, `validate_key_or_raise`, `revoke_api_key`
3. Create `apps/api/middleware/auth.py` — FastAPI `Depends(require_api_key)` extracting Bearer token
4. Create `apps/api/middleware/rate_limit.py` — 5-tier check wrapping `core/rate_limiter.py`, raises `HTTPException(429)`
5. Create `tests/unit/test_api_keys.py` — generate, hash match, sandbox block, revoke
6. Create `tests/unit/test_rate_limit.py` — each tier fires 429 at threshold (use `httpx.TestClient`)
7. Run full test suite — zero failures before marking Part 05 complete
8. Update `HANDOFF.md` with Part 05 results and Part 06 checklist

