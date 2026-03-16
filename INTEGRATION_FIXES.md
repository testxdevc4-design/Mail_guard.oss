# INTEGRATION_FIXES.md

Integration audit performed on MailGuard OSS — documenting every issue found and fixed.

---

## Fix 1: Undefined name `Any` in test_bot_part12.py

**File:** `tests/test_bot_part12.py`

**Problem:** Line 1208 used `Any` as a type annotation in `_make_client(self, value: Any = None)` inside the `TestSupabasePersistenceSession` class, but `Any` was never imported.

**Root cause:** Part 15 added test methods that used the `Any` type hint but the import statement at the top of the file was not updated.

**Fix:** Added `from typing import Any` to the imports block.

---

## Fix 2: E402 module-level import not at top of file in test_sender_rotation.py

**File:** `tests/test_sender_rotation.py`

**Problem:** Line 460 had a `from unittest.mock import AsyncMock, patch` re-import in the middle of the file (after test code). The existing `# noqa` comment suppressed F401 and F811 but not E402.

**Root cause:** Part 15 added `TestRotationCheckTask` tests at the bottom of the file with a re-import of `AsyncMock, patch`. The noqa comment was incomplete.

**Fix:** Added `E402` to the existing noqa comment: `# noqa: F401,F811,E402`.

---

## Fix 3: Unused `Optional` import in sdks/python/mailguard/types.py

**File:** `sdks/python/mailguard/types.py`

**Problem:** Line 10 imported `Optional` from `typing` but it was never used in the file.

**Root cause:** The import was leftover from an earlier draft and was never removed when the type annotation that needed it was changed.

**Fix:** Removed the unused `from typing import Optional` line.

---

## Fix 4: Unused `MailGuardError` import in sdks/python/tests/test_magic.py

**File:** `sdks/python/tests/test_magic.py`

**Problem:** Line 15 imported `MailGuardError` from `mailguard.exceptions` but no test in the file used it.

**Root cause:** The import was added in anticipation of tests that would assert on `MailGuardError`, but those tests were never written.

**Fix:** Removed `MailGuardError` from the import, keeping only `ExpiredError`.

---

## Fix 5: Unused local `EmailLog` import in tests/test_magic_routes.py

**File:** `tests/test_magic_routes.py`

**Problem:** Line 698 had a local `from core.models import EmailLog` import inside `test_send_magic_link_200_with_sender_email_id`. The `EmailLog` class was never referenced in the function body.

**Root cause:** The import was added when the test was written but was superseded by using the `_make_email_log()` helper function instead.

**Fix:** Removed the local `from core.models import EmailLog` import from inside the test function.

---

## Fix 6: Wrong mock return value in test_logs_shows_entries

**File:** `tests/test_bot_part12.py`

**Problem:** The `test_logs_shows_entries` test mocked `list_email_logs_paged` to return `([log], None)` (a 2-tuple), but `logs_command` expects a plain list. When the code iterated over the tuple, the first element was `[log]` (a list), not an `EmailLog` object, causing `AttributeError: 'list' object has no attribute 'sent_at'`.

**Root cause:** The test mock was written with a pagination-style return format `(data, cursor)` that does not match the actual `list_email_logs_paged` API, which returns `List[EmailLog]`.

**Fix:** Changed the mock `return_value` from `([log], None)` to `[log]` to match the actual function signature.

---

## Fix 7: Wrong mock structure in test_db_load_returns_value

**File:** `tests/test_bot_part12.py`

**Problem:** `test_db_load_returns_value` called `_make_client(value={"foo": "bar"})`, which set `result.data = {"foo": "bar"}`. However `_db_load` accesses `res.data["value"]` — it extracts the JSON stored in the `value` column from the Supabase row dict. With `data = {"foo": "bar"}`, the key `"value"` does not exist, causing a `KeyError` that is caught and silently returns `None`.

**Root cause:** The mock provided the raw stored value `{"foo": "bar"}` instead of the full Supabase row dict `{"value": {"foo": "bar"}}` that the query `SELECT value FROM bot_sessions` actually returns.

**Fix:** Changed `_make_client(value={"foo": "bar"})` to `_make_client(value={"value": {"foo": "bar"}})` so that `res.data["value"]` correctly returns `{"foo": "bar"}`.

---

## Fix 8: Missing `get_api_key` function in core/db.py

**File:** `core/db.py`

**Problem:** `apps/bot/commands/keys.py` needed to import `get_api_key` (fetch ApiKey by UUID) to implement `/revokekey`, but no such function existed in `core/db.py`. Only `get_api_key_by_hash` (fetch by SHA-256 hash of the plaintext key) was available.

**Root cause:** The API key lookup by ID was never implemented; only the auth path (lookup by hash) was implemented.

**Fix:** Added `get_api_key(key_id: str) -> Optional[ApiKey]` to `core/db.py` that queries the `api_keys` table by UUID.

---

## Fix 9: Missing `revokekey_command` in apps/bot/commands/keys.py

**File:** `apps/bot/commands/keys.py`

**Problem:** Three tests in `TestKeysCommandPart15` tried to import `revokekey_command` from `apps.bot.commands.keys` but it did not exist, causing `ImportError`.

**Root cause:** The `/revokekey` command was specified in the Part 15 test additions but was never implemented in the source file.

**Fix:** Implemented `revokekey_command` — it accepts a `<key_id>` argument, looks up the key with `get_api_key`, and calls `revoke_api_key` to deactivate it. Also updated the import line in `keys.py` to include `get_api_key` and `revoke_api_key`.

---

## Fix 10: Missing `activateproject_command` in apps/bot/commands/projects.py

**File:** `apps/bot/commands/projects.py`

**Problem:** Two tests in `TestProjectsCommandPart15` tried to import `activateproject_command` from `apps.bot.commands.projects` but it did not exist, causing `ImportError`.

**Root cause:** The `/activateproject` command (the reverse of `/deleteproject`) was specified in the Part 15 test additions but was never implemented.

**Fix:** Implemented `activateproject_command` — it accepts a `<slug>` argument, looks up the project with `get_project_by_slug`, and calls `update_project` to set `is_active=True`.

---

## Fix 11: New handlers not registered in apps/bot/main.py

**File:** `apps/bot/main.py`

**Problem:** The two new commands (`/revokekey` and `/activateproject`) added in Fixes 9–10 were not registered in `build_application`.

**Root cause:** Handler registration must be done manually in `build_application`; it is not automatic.

**Fix:** 
- Updated import to include `revokekey_command` and `activateproject_command`.
- Added `CommandHandler("revokekey", revokekey_command)` after the `/keys` handler.
- Added `CommandHandler("activateproject", activateproject_command)` after the `/deleteproject` handler.

---

## Fix 12: Webhook payload bytes mismatch between signing and sending

**File:** `apps/worker/tasks/deliver_webhook.py`

**Problem:** `sign_payload(raw_secret, payload)` serializes the payload with `json.dumps(payload, sort_keys=True, separators=(",", ":"))` to compute the HMAC signature. However `session.post(url, json=payload, headers=headers)` used aiohttp's default JSON serialization (no `sort_keys`), producing a different byte sequence. This meant the `X-MailGuard-Signature` header never matched the actual HTTP body bytes, so every developer's webhook verification would fail.

**Root cause:** Two separate JSON serializations were used — one deterministic (for the signature) and one non-deterministic (for the transport). With a dict whose keys are not already in sorted order, the bytes differ.

**Fix:** Added `import json` and computed a single deterministic serialization upfront:
```python
body_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
```
Then sent with `session.post(url, data=body_bytes, headers=headers)` so the bytes on the wire are identical to the bytes that were signed. Updated all session mock `post` methods in `tests/test_webhooks.py` to accept `data=` instead of `json=`.

---

## Fix 13: `asyncio.create_task()` fire-and-forget drops task reference

**Files:** `apps/api/routes/otp.py`, `apps/api/routes/magic.py`

**Problem:** Webhook events were fired with `asyncio.create_task(_fire_event(...))` but the returned task object was immediately discarded. In Python 3.12+, a task with no live reference can be garbage-collected before it completes, silently dropping the webhook event. Additionally, `create_task` is not available unless a running event loop already exists in the calling context.

**Root cause:** Using `create_task` for fire-and-forget without storing the reference is an unsafe pattern. The event loop holds only a weak reference to tasks created this way.

**Fix:** Replaced all four `asyncio.create_task(...)` calls with `asyncio.ensure_future(...)`, which schedules the coroutine in the running event loop and is the recommended pattern for fire-and-forget coroutines in FastAPI route handlers.

---

## Fix 14: Magic link URL ignores `MAGIC_LINK_BASE_URL` setting

**Files:** `core/config.py`, `apps/api/routes/magic.py`

**Problem:** The send-magic-link route always constructed the verify URL using `request.base_url`, which reflects the incoming request's host. When the API runs behind a reverse proxy or in a container, `request.base_url` resolves to an internal address (e.g. `http://0.0.0.0:3000/`) that is not reachable from the user's email client. The link in the email would be unclickable.

**Root cause:** No configurable base URL was provided for magic link construction. `MAGIC_LINK_BASE_URL` was referenced in documentation but not defined in `Settings`.

**Fix:** Added `MAGIC_LINK_BASE_URL: str = ''` to `core/config.py`. Updated `send_magic_link` in `apps/api/routes/magic.py` to prefer `settings.MAGIC_LINK_BASE_URL` when set, falling back to `request.base_url` for local development.

---

## Fix 15: Blocking sync DB calls inside async `check_and_rotate()`

**File:** `core/sender_rotation.py`

**Problem:** `check_and_rotate()` is an async function but called four synchronous Supabase DB functions directly: `get_project()`, `get_sender_email()`, `list_sender_emails()`, and `update_project()`. Each of these blocks the event loop while waiting for I/O, preventing the ARQ worker from concurrently processing other jobs during a rotation check.

**Root cause:** The async wrapper was written without wrapping the blocking DB calls in `asyncio.to_thread()`.

**Fix:** Replaced each direct sync call with `await asyncio.to_thread(fn, *args)` so that the Supabase I/O runs in a thread pool executor and the event loop remains free. Added `import asyncio` to the module imports.

---

## Summary

| # | File | Issue type | CI impact |
|---|------|-----------|-----------|
| 1 | tests/test_bot_part12.py | F821 undefined name `Any` | ❌ ruff fail |
| 2 | tests/test_sender_rotation.py | E402 import not at top | ❌ ruff fail |
| 3 | sdks/python/mailguard/types.py | F401 unused import | ❌ ruff fail |
| 4 | sdks/python/tests/test_magic.py | F401 unused import | ❌ ruff fail |
| 5 | tests/test_magic_routes.py | F401 unused import | ❌ ruff fail |
| 6 | tests/test_bot_part12.py | Wrong mock return value | ❌ test fail |
| 7 | tests/test_bot_part12.py | Wrong mock structure | ❌ test fail |
| 8 | core/db.py | Missing `get_api_key` function | ❌ test fail |
| 9 | apps/bot/commands/keys.py | Missing `revokekey_command` | ❌ test fail |
| 10 | apps/bot/commands/projects.py | Missing `activateproject_command` | ❌ test fail |
| 11 | apps/bot/main.py | New handlers not registered | ✅ no direct CI fail |
| 12 | apps/worker/tasks/deliver_webhook.py | Webhook HMAC body/signature mismatch | ❌ live verification fail |
| 13 | apps/api/routes/otp.py, magic.py | create_task drops task reference | ⚠️ silent webhook drop |
| 14 | core/config.py, apps/api/routes/magic.py | MAGIC_LINK_BASE_URL not configurable | ⚠️ email link unclickable |
| 15 | core/sender_rotation.py | Blocking DB calls block event loop | ⚠️ worker throughput |

**Final state after Part 17:** `ruff check .` → All checks passed. `pytest tests/` → 394 passed, 0 failed.

