# HANDOFF — Part 13 of 15

## Files created / modified

### Parts 01–12 files (unchanged)

Refer to prior HANDOFF content for Parts 01–12 files.

### Part 13 files (new)

| File | Lines | Description |
|------|-------|-------------|
| `sdks/js/package.json` | ~35 | Zero runtime deps; dual ESM+CJS via tsup; vitest for tests |
| `sdks/js/tsconfig.json` | ~15 | TypeScript 5 strict config, moduleResolution: bundler |
| `sdks/js/src/types.ts` | ~85 | Exported interfaces: MailGuardConfig, OtpSendOptions, OtpSendResult, OtpVerifyOptions, OtpVerifyResult, MagicLinkSendOptions, MagicLinkSendResult, MagicLinkVerifyResult |
| `sdks/js/src/errors.ts` | ~100 | MailGuardError (base), RateLimitError (+retryAfter), InvalidCodeError (+attemptsRemaining), ExpiredError, LockedError, SandboxError, InvalidKeyError |
| `sdks/js/src/client.ts` | ~130 | MailGuardClient: AbortController timeout, Bearer auth, _throwTyped() with error-key dispatch |
| `sdks/js/src/otp.ts` | ~80 | OtpClient extends MailGuardClient; send() + verify() with camelCase conversion |
| `sdks/js/src/magic.ts` | ~80 | MagicLinkClient extends MailGuardClient; send() (camelCase→snake_case) + verify() (snake_case→camelCase) |
| `sdks/js/src/index.ts` | ~50 | MailGuard facade class; re-exports all types and error classes |
| `sdks/js/tests/otp.test.ts` | ~200 | 12 vitest tests covering all OTP paths and error types |
| `sdks/js/tests/magic.test.ts` | ~170 | 8 vitest tests covering magic link paths and camelCase verification |
| `sdks/js/README.md` | ~220 | Copy-paste-ready docs: installation, quick start, method reference, error handling, config, self-hosting |

## What works right now

```bash
# Python tests still pass (252 from Parts 01–12)
pytest tests/ -q  # 252 passed, 0 failed

# SDK build
cd sdks/js && npm run build
# → CJS dist/index.js, ESM dist/index.mjs, DTS dist/index.d.ts + dist/index.d.mts
# → Zero TypeScript errors

# SDK tests
cd sdks/js && npm test
# → 20 tests, 0 failures (12 OTP + 8 magic link)

# ESM import verification
node --input-type=module <<< "import { MailGuard } from 'mailguard-sdk'; console.log(typeof MailGuard);"
# → function

# CJS require verification
node -e "const { MailGuard } = require('mailguard-sdk'); console.log(typeof MailGuard);"
# → function

# CodeQL: 0 alerts
```

## SDK design decisions

### 1. Build tool: tsup (devDependency, not runtime dependency)

TypeScript's `moduleResolution: "bundler"` is incompatible with `module: "CommonJS"` and `moduleResolution: "node"` does not resolve `.js` extensions to `.ts` source files in TypeScript 5. Using `tsup` as a devDependency is the industry-standard solution for dual ESM/CJS output from a single TypeScript codebase. Runtime dependencies are zero.

### 2. Auth header: `Authorization: Bearer <apiKey>`

The API middleware (`apps/api/middleware/auth.py`) uses `HTTPBearer()` — not a custom `X-API-Key` header. All SDK requests use `Authorization: Bearer ${apiKey}`.

### 3. Error dispatch: status code + error key

`_throwTyped()` in client.ts reads `response.body.detail.error` (the key string) in addition to HTTP status. HTTP 403 can be either `SandboxError` (when `error === 'sandbox_key_in_production'`) or a plain `MailGuardError` (when `error === 'project_inactive'` or similar).

### 4. snake_case ↔ camelCase

- **Requests**: `redirectUrl → redirect_url`, `templateId → template_id`
- **OTP send**: `expires_in → expiresIn`, `masked_email → maskedEmail`
- **OTP verify**: `expires_at → expiresAt`
- **Magic verify**: `email_hash → emailHash`, `project_id → projectId`, `redirect_url → redirectUrl`

### 5. Timeout: AbortController

Every `request()` call creates an `AbortController`, schedules `controller.abort()` via `setTimeout`, and clears the timer in `finally`. Aborted requests throw `MailGuardError` with message `Request timed out after ${timeout}ms` and `status: 0`.

### 6. fetch availability check

The constructor throws `MailGuardError` immediately if `typeof fetch === 'undefined'`, so users in non-fetch environments get a clear error on instantiation rather than a confusing failure at request time.

## What is NOT built yet

- Part 14: `SECURITY.md`

## Env vars introduced

None — SDK has no environment variable dependencies.

## Test results

```
# Python
pytest tests/  →  252 passed, 0 failed

# JavaScript SDK
npm run build  →  zero TypeScript errors, zero warnings
npm test       →  20 passed (12 OTP + 8 magic link), 0 failed
CodeQL         →  0 alerts
```

## Known issues

- Real end-to-end webhook delivery not confirmed in CI (no live endpoint)
- `email_logs.status` CHECK constraint issue from Part 06 still unresolved
- Railway deployment not confirmed — no live credentials in CI

## Next agent: do these first (Part 14)

1. Read Part 14 in `MailGuard_MaxMVP_15Part.docx` — it is labelled SECURITY.md
2. Do not modify any Part 13 SDK files unless there is a verified bug
3. Build on top of 252 Python tests and 20 JavaScript SDK tests
4. Update `HANDOFF.md` with Part 14 results and Part 15 checklist
