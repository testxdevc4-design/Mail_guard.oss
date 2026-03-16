# HANDOFF — Part 10 of 15

## Files created / modified

### Parts 01–09 files (unchanged)

| File | Lines | Description |
|------|-------|-------------|
| `core/otp.py` | ~110 | Full OTP lifecycle |
| `core/jwt_utils.py` | ~100 | HS256 JWT with Redis revocation |
| `core/rate_limiter.py` | ~80 | 5-tier Redis sliding window |
| `core/api_keys.py` | ~115 | API key generation and validation |
| `core/smtp.py` | ~100 | Async SMTP email delivery |
| `core/templates.py` | ~135 | Jinja2 email + HTML page rendering |
| `core/magic_links.py` | ~125 | Magic link creation and single-use verification |
| `core/webhooks.py` | ~95 | HMAC-SHA256 webhook signing and event dispatch |
| `apps/api/routes/webhooks.py` | ~135 | Webhook registration, list, deactivate |
| `apps/worker/tasks/deliver_webhook.py` | ~170 | ARQ task: 3 attempts, 10s/60s/300s backoff |

### Part 10 files (new / modified)

| File | Lines | Description |
|------|-------|-------------|
| `core/sender_rotation.py` | ~200 | `increment_sender_usage()`, `get_usage_pct()`, `select_best_sender()`, `check_and_rotate()` |
| `apps/worker/tasks/rotation_check.py` | ~50 | ARQ cron: iterates active projects, calls `check_and_rotate()` |
| `apps/worker/main.py` | +3 | Added `rotation_check` cron (every 60 min), added import |
| `apps/worker/tasks/send_email.py` | +5 | Calls `increment_sender_usage()` after successful delivery (try/except so Redis failure doesn't affect delivery) |
| `tests/test_sender_rotation.py` | ~340 | 18 tests covering all required cases |

## What works right now

```bash
# 185 tests pass (167 from Parts 01–09, 18 new)
pytest tests/ -v
# → 185 passed, 0 failed

# CodeQL: 0 alerts
```

## Security guarantees implemented

### From Parts 01–09
- OTP codes: CSPRNG, bcrypt hash (cost 10), attempt counter before hash check
- JWT: unique `jti`, Redis revocation, HS256
- API key: 256-bit entropy, SHA-256 hash stored only, sandbox-first check
- Magic link: 256-bit raw token, SHA-256 hash stored only, single-use atomic
- SMTP password: zeroed in `finally`, never logged
- Rate limiter: atomic Redis pipeline, 5 tiers
- Webhook secret: `secrets.token_hex(32)` — 256-bit, returned once; stored AES-256-GCM encrypted

### New in Part 10
- Sender daily counters stored in Redis with TTL-based expiry (86400 s from first use)
- INCR + EXPIRE in the same pipeline — no key left without TTL on crash
- Rotation fallback: lowest-usage sender returned even when all are above threshold
- `increment_sender_usage()` wrapped in try/except in `send_email.py` — Redis failure never blocks delivery

## Rotation design decisions

- Redis key pattern: `sender:daily:{sender_id}` — TTL 86400 s set on every INCR (not a fixed midnight reset)
- Threshold from `settings.ROTATION_THRESHOLD` (default 0.80)
- `select_best_sender()` never returns `None` when at least one active sender exists
- `check_and_rotate()` only updates Supabase if it actually switches to a different sender
- Telegram alert contains: project slug, old sender address, new sender address, old sender usage %
- `increment_sender_usage()` failure is logged but does not abort the successful email delivery

## What is NOT built yet

- All SDK code — Part 14
- All bot commands — Parts 11–13
- `SECURITY.md` — Part 15

## Env vars introduced

No new env vars in Part 10 (`ROTATION_THRESHOLD` already existed in `core/config.py`).

## DB state

- 7 migration files still pending manual run in Supabase SQL Editor (001 → 007)
- `webhooks` table must have: `id`, `project_id`, `url`, `secret_enc`, `events` (text[]), `is_active`, `failure_count`, `last_triggered_at`, `created_at`
- `magic_links` table `used_at TIMESTAMPTZ` column must exist (from Part 08)

## Test results

```
pytest tests/test_sender_rotation.py  → 18 passed, 0 failed
pytest tests/                         → 185 passed, 0 failed
CodeQL                                → 0 alerts
```

## Known issues

- Real end-to-end webhook delivery (HTTP POST to external endpoint) not confirmed in CI (no live endpoint)
- `email_logs.status` CHECK constraint issue from Part 06 still unresolved
- Manual rotation test (Supabase + Telegram) not confirmed — no live environment available in CI

## Next agent: do these first (Part 11)

1. Read Part 11 in `MailGuard_MaxMVP_15Part.docx` — understand the next part's spec
2. Do not modify `core/sender_rotation.py` unless there is a verified bug
3. Continue building on top of the 185 passing tests
4. Update `HANDOFF.md` with Part 11 results and Part 12 checklist

