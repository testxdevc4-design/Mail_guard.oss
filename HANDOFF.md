# HANDOFF — Part 09 of 15

## Files created / modified

### Parts 01–08 files (unchanged or only fire_event additions)

| File | Lines | Description |
|------|-------|-------------|
| `core/otp.py` | ~110 | Full OTP lifecycle |
| `core/jwt_utils.py` | ~100 | HS256 JWT with Redis revocation |
| `core/rate_limiter.py` | ~80 | 5-tier Redis sliding window |
| `core/api_keys.py` | ~115 | API key generation and validation |
| `core/smtp.py` | ~100 | Async SMTP email delivery |
| `core/templates.py` | ~135 | Jinja2 email + HTML page rendering |
| `core/magic_links.py` | ~125 | Magic link creation and single-use verification |
| `apps/api/routes/otp.py` | +20 | Added `fire_event` calls for `otp.sent` and `otp.verified` |
| `apps/api/routes/magic.py` | +30 | Added `fire_event` calls for `magic_link.sent` and `magic_link.verified`; pre-lookup of `project_id` by token hash for verified event |

### Part 09 files (new)

| File | Lines | Description |
|------|-------|-------------|
| `core/webhooks.py` | ~95 | `sign_payload(secret, payload)` — HMAC-SHA256, `sort_keys=True`, returns `sha256={hex}`. `fire_event(project_id, event, payload)` — looks up active subscribed webhooks, enqueues one ARQ job per endpoint. |
| `apps/api/routes/webhooks.py` | ~135 | `POST /api/v1/webhooks` (register), `GET /api/v1/webhooks` (list), `DELETE /api/v1/webhooks/{id}` (deactivate). Secret generated with `secrets.token_hex(32)`, returned once, stored AES-encrypted. |
| `apps/worker/tasks/deliver_webhook.py` | ~170 | ARQ task: 3 attempts, 10s/60s/300s backoff, 10s aiohttp timeout. `X-MailGuard-Signature: sha256={hex}` header. Telegram alert on permanent failure. |
| `apps/api/schemas.py` | +35 | Added `WebhookCreateRequest` and `WebhookResponse` |
| `apps/api/main.py` | +2 | `app.include_router(webhooks.router)` after magic router |
| `apps/worker/main.py` | +2 | Added `task_deliver_webhook` to worker functions list |
| `tests/test_webhooks.py` | ~770 | 21 tests covering all required cases |

## What works right now

```bash
# 167 tests pass (146 from Parts 01–08, 21 new)
pytest tests/ -v
# → 167 passed, 0 failed

# CodeQL: 0 alerts
```

## Security guarantees implemented

### From Parts 01–08
- OTP codes: CSPRNG, bcrypt hash (cost 10), attempt counter before hash check
- JWT: unique `jti`, Redis revocation, HS256
- API key: 256-bit entropy, SHA-256 hash stored only, sandbox-first check
- Magic link: 256-bit raw token, SHA-256 hash stored only, single-use atomic
- SMTP password: zeroed in `finally`, never logged
- Rate limiter: atomic Redis pipeline, 5 tiers

### New in Part 09
- Webhook secret: `secrets.token_hex(32)` — 256-bit, returned once in registration response
- **Secret stored AES-256-GCM encrypted** in `webhooks.secret_enc` — never plaintext
- HMAC-SHA256 signature: `sort_keys=True` + compact separators — deterministic regardless of key insertion order
- `X-MailGuard-Signature: sha256={hex}` on every delivery — developer can verify with HMAC-SHA256
- Delivery timeout: 10-second `aiohttp.ClientTimeout` — worker never hangs indefinitely
- fire_event wrapped in `asyncio.create_task()` in routes — webhook failure never delays API response
- One failed delivery never blocks other endpoints — each ARQ job is independent

## Webhook signature verification

Developers verify the `X-MailGuard-Signature` header with:

```python
import hashlib, hmac, json

def verify_webhook(raw_secret: str, payload: dict, header: str) -> bool:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    expected = hmac.new(raw_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", header)
```

## What is NOT built yet

- `core/sender_rotation.py` — Auto sender rotation (Part 10)
- All SDK code — Part 14
- All bot commands — Parts 11–13
- `SECURITY.md` — Part 15

## Env vars introduced

No new env vars in Part 09.

## DB state

- 7 migration files still pending manual run in Supabase SQL Editor (001 → 007)
- `webhooks` table must have: `id`, `project_id`, `url`, `secret_enc`, `events` (text[]), `is_active`, `failure_count`, `last_triggered_at`, `created_at`
- `magic_links` table `used_at TIMESTAMPTZ` column must exist (from Part 08)

## Decisions made

- Webhook secret stored as AES-256-GCM encrypted (not SHA-256 hash) so the worker can decrypt and use it for HMAC signing at delivery time
- `fire_event()` uses `asyncio.to_thread` for the sync DB lookup (consistent with rest of codebase)
- `magic_link.verified` route does a pre-lookup of the magic link row by token hash to resolve `project_id` before calling `verify_magic_link` — this adds one DB read but is the only way to get `project_id` without modifying core files
- `_BACKOFF_DELAYS = (10, 60, 300)` — only first 2 values used as inter-attempt delays; the third is documented as reserved

## Test results

```
pytest tests/test_webhooks.py   → 21 passed, 0 failed
pytest tests/                   → 167 passed, 0 failed
CodeQL                          → 0 alerts
```

## Known issues

- Real end-to-end webhook delivery (HTTP POST to external endpoint) not confirmed in CI (no live endpoint)
- `magic_link.verified` project_id lookup fires one extra DB read per verify call — acceptable for correctness
- `email_logs.status` CHECK constraint issue from Part 06 still unresolved

## Next agent: do these first (Part 10)

1. Read Part 10 in `MailGuard_MaxMVP_15Part.docx` — understand sender rotation spec
2. Create `core/sender_rotation.py` — auto rotation logic
3. Write tests — zero failures
4. Update `HANDOFF.md` with Part 10 results and Part 11 checklist

