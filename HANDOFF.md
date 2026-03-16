# HANDOFF — Part 11 of 15

## Files created / modified

### Parts 01–10 files (unchanged)

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
| `core/sender_rotation.py` | ~200 | `increment_sender_usage()`, `get_usage_pct()`, `select_best_sender()`, `check_and_rotate()` |
| `apps/worker/tasks/rotation_check.py` | ~50 | ARQ cron: iterates active projects, calls `check_and_rotate()` |

### Part 11 files (new)

| File | Lines | Description |
|------|-------|-------------|
| `apps/bot/main.py` | ~70 | Application factory; TypeHandler admin gate at group=-1; /start and /addemail registered |
| `apps/bot/middleware/admin_gate.py` | ~30 | Silent admin-only gate using ApplicationHandlerStop |
| `apps/bot/commands/start.py` | ~65 | /start — checks 4 live systems (Supabase DB, Redis, Internal API, Bot) |
| `apps/bot/wizards/add_email.py` | ~310 | 3-state ConversationHandler: email→provider detect→custom host→App Password→SMTP verify→encrypt→save |
| `apps/bot/session.py` | ~200 | Supabase-backed BasePersistence (bot_sessions table) |
| `apps/bot/keyboards.py` | ~65 | `confirm_cancel_keyboard()`, `yes_no_keyboard()`, `paginated_list_keyboard()` |
| `apps/bot/formatters.py` | ~55 | `format_status_line()`, `format_table()` |
| `tests/test_bot_admin_gate.py` | ~80 | 5 tests: admin passes, non-admin dropped, no reply sent |
| `tests/test_bot_formatters.py` | ~105 | 11 tests: status lines, tables, code blocks |
| `tests/test_bot_keyboards.py` | ~105 | 9 tests: button data, pagination edge cases |

### Part 11 bug fixes

| File | Change |
|------|--------|
| `tests/test_webhooks.py` | Removed unused imports (`asyncio`, `MagicMock`, `call`) — CI ruff failure |
| `tests/test_sender_rotation.py` | Removed unused imports (`Any`, `call`) — CI ruff failure |

## What works right now

```bash
# 213 tests pass (185 from Parts 01–10, 28 new)
pytest tests/ -v
# → 213 passed, 0 failed

# Ruff: all checks passed
ruff check .

# Mypy: no issues
mypy apps/ core/ --ignore-missing-imports --no-strict-optional

# CodeQL: 0 alerts
```

## Admin gate design

The admin gate is registered as `TypeHandler(Update, admin_gate)` in **group=-1**.
This ensures it runs before every command, conversation, and callback handler (which
are in group=0). If the `update.effective_user.id` does not exactly match
`settings.TELEGRAM_ADMIN_UID`, `ApplicationHandlerStop` is raised immediately.

Security contract:
- No reply, no typing indicator, no read receipt
- No log entry containing the user's ID or any identifying information
- PTB never passes the update to any downstream handler

## Add-email wizard design

States: `ASK_EMAIL (0) → ASK_CUSTOM_HOST (1, custom only) → ASK_PASSWORD (2)`

Provider auto-detection table (all 6 required providers):

| Domain(s) | Provider | Host | Port |
|-----------|----------|------|------|
| gmail.com, googlemail.com | Gmail | smtp.gmail.com | 465 |
| outlook.com, hotmail.com, live.com, msn.com | Outlook | smtp.office365.com | 587 |
| yahoo.com, ymail.com | Yahoo | smtp.mail.yahoo.com | 465 |
| zoho.com, zohomail.com | Zoho | smtp.zoho.com | 465 |
| icloud.com, me.com, mac.com | iCloud | smtp.mail.me.com | 587 |
| any other | custom | user-supplied | 587 |

App Password security:
1. `encrypt(raw_password)` called before zeroing the local variable
2. SMTP verification via `aiosmtplib.SMTP` login attempt
3. Password message deleted from Telegram chat regardless of outcome
4. Failed credentials are never saved (SMTP verify must pass before DB write)
5. DB write uses `upsert(on_conflict="email_address")` — re-adding same email updates credentials

## Session persistence design

`SupabasePersistence(BasePersistence)` stores all PTB session data in the
`bot_sessions` table (key TEXT PK, value JSONB). Conversation tuple-keys are
serialised as JSON strings to avoid delimiter ambiguity. All DB failures are
caught and logged silently — a temporary Supabase outage never crashes the bot.

Required table (one-time setup):
```sql
CREATE TABLE IF NOT EXISTS bot_sessions (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## Railway deployment

Railway deployment not confirmed in this session (no live Railway credentials
available in CI). The Dockerfile for the bot service (`Dockerfile.bot`) already
exists from Part 02. The `railway.toml` bot service is configured with:
```
startCommand = "python -m apps.bot.main"
```
Bot will start once `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ADMIN_UID` env vars
are set in the Railway dashboard.

## Security guarantees implemented (Part 11 additions)

- Admin gate: silent drop — no acknowledgement of bot's existence to non-admin users
- App Password: encrypted before zeroing, SMTP-verified before saving, message deleted
  from chat immediately after processing
- Supabase persistence: DB failures never crash the bot; no sensitive data logged

## What is NOT built yet

- Part 12: `/senders`, `/projects`, `/keys`, `/logs`, `/webhooks` commands
- Part 12: wizards `/newproject`, `/setotp`, `/setwebhook`
- Part 14: SDK code
- Part 15: `SECURITY.md`

## Env vars introduced in Part 11

No new env vars. All bot env vars (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_UID`,
`INTERNAL_API_URL`) were already in `core/config.py` from Part 02.

## DB state

- `bot_sessions` table must be created (schema above)
- All previous migration files still pending manual run in Supabase SQL Editor

## Test results

```
pytest tests/test_bot_admin_gate.py   →  5 passed, 0 failed
pytest tests/test_bot_formatters.py  → 11 passed, 0 failed
pytest tests/test_bot_keyboards.py   →  9 passed, 0 failed
pytest tests/                        → 213 passed, 0 failed
CodeQL                               → 0 alerts
```

## Known issues

- Real end-to-end webhook delivery not confirmed in CI (no live endpoint)
- `email_logs.status` CHECK constraint issue from Part 06 still unresolved
- Railway deployment not confirmed — no live credentials in CI
- SMTP verification in wizard uses `use_tls` (SSL on port 465) and `starttls()`
  (STARTTLS on port 587); Outlook/iCloud connections via port 587 require the
  Telegram admin to have 2FA + App Password enabled on their Microsoft/Apple account

## Next agent: do these first (Part 12)

1. Read Part 12 in `MailGuard_MaxMVP_15Part.docx`
2. Do not modify any Part 11 files unless there is a verified bug
3. Create the following command files (Part 12 scope):
   - `apps/bot/commands/senders.py`
   - `apps/bot/commands/projects.py`
   - `apps/bot/commands/keys.py`
   - `apps/bot/commands/logs.py`
   - `apps/bot/commands/webhooks.py`
4. Create the following wizard files (Part 12 scope):
   - `apps/bot/wizards/new_project.py`
   - `apps/bot/wizards/set_otp.py`
   - `apps/bot/wizards/set_webhook.py`
5. Register all new handlers in `apps/bot/main.py`
6. Continue building on top of the 213 passing tests
7. Update `HANDOFF.md` with Part 12 results and Part 13 checklist


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

