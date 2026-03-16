# MailGuard OSS — Integration & Error Resolution Summary

## Part 16 Fixes (Import & Syntax Errors)

### Fix 1 — Undefined name `Any` in test_bot_part12.py
**File:** `tests/test_bot_part12.py`
Added `from typing import Any` import to resolve F821 undefined name.

### Fix 2 — E402 module-level import not at top in test_sender_rotation.py
**File:** `tests/test_sender_rotation.py`
Added `E402` to the existing noqa comment: `# noqa: F401,F811,E402`.

### Fix 3 — Unused `Optional` import in sdks/python/mailguard/types.py
**File:** `sdks/python/mailguard/types.py`
Removed unused `from typing import Optional` import.

### Fix 4 — Unused `MailGuardError` import in sdks/python/tests/test_magic.py
**File:** `sdks/python/tests/test_magic.py`
Removed `MailGuardError` from the import — it was never used in the file.

### Fix 5 — Unused local `EmailLog` import in tests/test_magic_routes.py
**File:** `tests/test_magic_routes.py`
Removed local `from core.models import EmailLog` import from inside a test function.

### Fix 6 — Wrong mock return value in test_logs_shows_entries
**File:** `tests/test_bot_part12.py`
Changed mock `return_value` from `([log], None)` to `[log]` to match actual function signature.

### Fix 7 — Wrong mock structure in test_db_load_returns_value
**File:** `tests/test_bot_part12.py`
Changed `_make_client(value={"foo": "bar"})` to `_make_client(value={"value": {"foo": "bar"}})`.

### Fix 8 — Missing `get_api_key` function in core/db.py
**File:** `core/db.py`
Added `get_api_key(key_id: str) -> Optional[ApiKey]` to query the `api_keys` table by UUID.

### Fix 9 — Missing `revokekey_command` in apps/bot/commands/keys.py
**File:** `apps/bot/commands/keys.py`
Implemented `/revokekey` command with `get_api_key` and `revoke_api_key` calls.

### Fix 10 — Missing `activateproject_command` in apps/bot/commands/projects.py
**File:** `apps/bot/commands/projects.py`
Implemented `/activateproject` command that sets `is_active=True` on a project.

### Fix 11 — New handlers not registered in apps/bot/main.py
**File:** `apps/bot/main.py`
Registered `revokekey_command` and `activateproject_command` handlers.

---

## Part 17 Fixes (Cross-Service Connection Errors)

### Fix 12 — Webhook payload/signature mismatch
**File:** `apps/worker/tasks/deliver_webhook.py`
Computed a single deterministic `body_bytes` with `sort_keys=True` for both signing and HTTP
transport so the `X-MailGuard-Signature` header always matches the on-wire bytes.

### Fix 13 — `asyncio.create_task()` drops reference in OTP/magic routes
**Files:** `apps/api/routes/otp.py`, `apps/api/routes/magic.py`
Replaced `asyncio.create_task(...)` with `asyncio.ensure_future(...)` for fire-and-forget
webhook events to prevent GC-collection of unawaited tasks in Python 3.12+.

### Fix 14 — `MAGIC_LINK_BASE_URL` not configurable
**Files:** `core/config.py`, `apps/api/routes/magic.py`
Added `MAGIC_LINK_BASE_URL: str = ''` to `Settings`. Route prefers this when set, falls
back to `request.base_url` for local development.

### Fix 15 — Blocking sync DB calls in async `check_and_rotate()`
**File:** `core/sender_rotation.py`
Wrapped all four sync Supabase DB calls with `await asyncio.to_thread(fn, *args)`.

---

## Part 18 Fixes (Runtime & Production Errors)

### Fix 16 — OTP send response shape mismatch
**File:** `apps/api/routes/otp.py`
Changed response from `{"sent": true, "masked_email": "..."}` to the documented shape
`{"status": "sent", "expires_in": N, "masked_email": "..."}` where `N` is
`project.otp_expiry_seconds`. Updated two test assertions in `tests/test_otp_routes.py`
that checked the old `sent: true` format.

### Fix 17 — OTP verify response missing `expires_at`
**File:** `apps/api/routes/otp.py`
Added `expires_at` field to the successful verify response
(`datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRY_MINUTES)`).
Response now matches documented shape: `{"verified": true, "token": "...", "expires_at":
"...", "otp_id": "..."}`.

### Fix 18 — Magic link send response missing `expires_in`
**File:** `apps/api/routes/magic.py`
Changed response from `{"status": "sent"}` to `{"status": "sent", "expires_in": N}` where
`N` is `settings.MAGIC_LINK_EXPIRY_MINUTES * 60` (900 seconds by default).

### Fix 19 — CI deploy action version not found
**File:** `.github/workflows/ci.yml`
Updated `bervProject/railway-deploy@v1.2.0` to `bervProject/railway-deploy@v1.3.0`.
The v1.2.0 tag did not resolve in GitHub Actions causing the deploy job to fail with
"Unable to resolve action `bervproject/railway-deploy@v1.2.0`, unable to find version
`v1.2.0`".

### Fix 20 — `MAGIC_LINK_BASE_URL` missing from `.env.example`
**File:** `.env.example`
Added `MAGIC_LINK_BASE_URL=` entry with documentation. This variable was added to
`core/config.py` in Fix 14 but was not reflected in the environment variable reference
file, making it invisible to operators deploying the service.

---

## Final Test Results

- **pytest tests/:** 394 passed, 0 failed, 70 warnings
- **ruff check .:** All checks passed
- **mypy apps/ core/ --ignore-missing-imports --no-strict-optional:** No issues found in 55 source files
- **Baseline (Part 17):** 394 passed — no regression

---

## Production Readiness Statement

MailGuard OSS has been systematically audited across Parts 16, 17, and 18. All import
errors and syntax failures are resolved (Part 16). Every cross-service connection path —
webhook HMAC signing, async task scheduling, magic link URL construction, and sender
rotation blocking calls — has been corrected (Part 17). The final production pass (Part 18)
aligns all API response shapes with the documented specification, adds missing environment
variable documentation, and resolves the CI deploy pipeline. The test suite passes at 394
tests with clean ruff and mypy output. The project is ready for production deployment.
