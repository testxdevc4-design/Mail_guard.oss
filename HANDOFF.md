# HANDOFF — Part 14 of 15

## Files created / modified

### Parts 01–13 files (unchanged)

Refer to prior HANDOFF content for Parts 01–13 files.

### Part 14 files (new)

| File | Lines | Description |
|------|-------|-------------|
| `sdks/python/pyproject.toml` | ~50 | Zero runtime deps; optional aiohttp[async]; pytest config |
| `sdks/python/mailguard/__init__.py` | ~110 | MailGuard + AsyncMailGuard facade; re-exports all types + exceptions |
| `sdks/python/mailguard/client.py` | ~120 | Sync HTTP client using stdlib urllib.request only |
| `sdks/python/mailguard/async_client.py` | ~145 | Async client with lazy aiohttp import inside methods |
| `sdks/python/mailguard/otp.py` | ~115 | OtpClient + AsyncOtpClient with send() and verify() |
| `sdks/python/mailguard/magic.py` | ~120 | MagicLinkClient + AsyncMagicLinkClient with send() and verify() |
| `sdks/python/mailguard/exceptions.py` | ~90 | 7 typed exception classes; all inherit MailGuardError |
| `sdks/python/mailguard/types.py` | ~100 | TypedDicts: stdlib typing.TypedDict only — zero external deps |
| `sdks/python/tests/test_otp.py` | ~250 | 13 tests: success paths, all error types, timeout, network failure |
| `sdks/python/tests/test_magic.py` | ~195 | 8 tests: sync (httpretty) + async (unittest.mock) |
| `sdks/python/README.md` | ~250 | Copy-paste docs: install, sync/async quickstart, method ref, errors |

## What works right now

```bash
# Python tests (Part 01–13 unchanged)
pytest tests/ -q  # 252 passed, 0 failed

# Python SDK tests
cd sdks/python
pytest tests/ -v  # 21 passed, 0 failed

# Build
cd sdks/python && python -m build
# → Successfully built mailguard_sdk-1.0.0.tar.gz and mailguard_sdk-1.0.0-py3-none-any.whl
# → Zero warnings

# Fresh venv install + imports
python3 -m venv /tmp/mg_venv && /tmp/mg_venv/bin/pip install dist/*.whl -q
/tmp/mg_venv/bin/python -c "from mailguard import MailGuard; print('OK')"
/tmp/mg_venv/bin/python -c "from mailguard import AsyncMailGuard; print('OK')"  # no aiohttp needed
/tmp/mg_venv/bin/python -c "from mailguard.exceptions import RateLimitError; print('OK')"
/tmp/mg_venv/bin/python -c "import mailguard; print(mailguard.__version__)"  # 1.0.0

# Zero runtime dependencies
pip show mailguard-sdk | grep Requires
# Requires:   (empty)

# CodeQL: 0 alerts
```

## SDK design decisions

### 1. Zero runtime deps — stdlib urllib.request only

The sync client uses `urllib.request`, `urllib.error`, and `json` — all Python stdlib. No `requests`, no `httpx`. This allows installation in air-gapped environments.

### 2. Lazy aiohttp import

`aiohttp` is imported inside each `_request()` method in `AsyncMailGuardClient`, not at module level. This means `from mailguard import AsyncMailGuard` succeeds even when `aiohttp` is not installed.

### 3. snake_case throughout (Python convention)

Unlike the JS SDK which converts to camelCase, the Python SDK returns the API's snake_case keys unchanged: `expires_in`, `masked_email`, `attempts_remaining`, `email_hash`, `project_id`, `redirect_url`.

### 4. TypedDicts use stdlib typing only

`types.py` uses `from typing import TypedDict` (available since Python 3.8) — no `typing_extensions` dependency.

### 5. Bearer auth (same as JS SDK)

`Authorization: Bearer <api_key>` on every request — matches the FastAPI `HTTPBearer()` middleware.

### 6. Tests use httpretty (not responses)

The `responses` library only mocks the `requests` library. Since the SDK uses `urllib.request`, tests use `httpretty` which intercepts at the socket level and works transparently with `urllib.request`. Async tests use `unittest.mock.patch` on `aiohttp.ClientSession`.

### 7. httpretty added to test dependencies only

`httpretty` is listed under `[project.optional-dependencies] dev = [...]` — it is not a runtime dependency.

## What is NOT built yet

- Part 15: Full pytest suite, bandit, mypy, CI hardening, SECURITY.md

## Env vars introduced

None — Python SDK has no environment variable dependencies.

## Test results

```
# Part 14 — Python SDK
pytest sdks/python/tests/ -v
→ 21 passed, 0 failed

# Wheel build
python -m build (from sdks/python/)
→ Successfully built mailguard_sdk-1.0.0-py3-none-any.whl
→ Zero warnings

# pip show mailguard-sdk | grep Requires
→ Requires:   (empty — zero runtime deps)

# CodeQL
→ 0 alerts

# JS SDK (Part 13 unchanged)
npm test (from sdks/js/)
→ 20 passed, 0 failed
```

## Known issues

- `httpretty` deprecation warning (`datetime.utcnow()`) appears in pytest output — this is inside httpretty's internal code and cannot be suppressed without patching the library itself. All tests still pass.
- Real end-to-end tests not run (no live MailGuard instance in CI)

## Next agent: do these first (Part 15)

1. Read Part 15 in `MailGuard_MaxMVP_15Part.docx` — Tests + CI + Hardening + SECURITY.md
2. Do not modify any Part 14 SDK files unless there is a verified bug
3. Build on top of 252 Python tests + 21 Python SDK tests + 20 JavaScript SDK tests
4. Run `bandit -r apps/ core/ -ll` and fix any HIGH severity findings
5. Run `mypy apps/ core/ --ignore-missing-imports` and fix type errors
6. Update GitHub Actions CI to include bandit + mypy + SDK tests
7. Create `SECURITY.md` with 12-point audit as specified in Part 15
8. Update `HANDOFF.md` with Part 15 results — this is the final handoff
