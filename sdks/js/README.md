# mailguard-sdk

Official JavaScript / TypeScript SDK for [MailGuard OSS](https://github.com/testxdevc4-design/Mail_guard.oss) — a self-hosted OTP and magic link automation server.

- **Zero runtime dependencies** — uses native `fetch` (Node 18 + / all modern browsers)
- **Dual ESM + CJS** — works with `import` and `require` out of the box
- **Fully typed** — every request, response, and error has TypeScript interfaces
- **Configurable timeout** — AbortController-based, default 10 s

---

## Installation

```bash
npm install mailguard-sdk
```

Requires **Node 18+** (for native `fetch`) or any modern browser.

---

## Quick start — OTP

```typescript
import { MailGuard } from 'mailguard-sdk';

const mg = new MailGuard({ apiKey: 'mg_live_your_key_here' });

// 1. Send OTP to the user
const sent = await mg.otp.send({ email: 'user@example.com' });
console.log(sent.status);      // 'sent'
console.log(sent.maskedEmail); // 'u***@example.com'
console.log(sent.expiresIn);   // 300 (seconds)

// 2. Verify the code the user typed
const result = await mg.otp.verify({
  email: 'user@example.com',
  code: '482910',
});
console.log(result.verified);  // true
console.log(result.token);     // signed JWT for this session
console.log(result.expiresAt); // ISO 8601 timestamp
```

---

## Quick start — Magic links

```typescript
import { MailGuard } from 'mailguard-sdk';

const mg = new MailGuard({ apiKey: 'mg_live_your_key_here' });

// 1. Send a magic link
const sent = await mg.magic.send({
  email: 'user@example.com',
  purpose: 'login',
  redirectUrl: 'https://app.example.com/dashboard',
});
console.log(sent.status); // 'sent'

// 2. Verify the token when the user clicks the link
//    (token comes from the URL query param your backend receives)
const verified = await mg.magic.verify('the-raw-token-from-url');
console.log(verified.valid);       // true
console.log(verified.emailHash);   // HMAC-SHA256 hash of the email
console.log(verified.projectId);   // your project UUID
console.log(verified.purpose);     // 'login'
console.log(verified.redirectUrl); // 'https://app.example.com/dashboard'
```

---

## All methods

### `new MailGuard(config: MailGuardConfig)`

| Option    | Type     | Default                       | Description                                      |
|-----------|----------|-------------------------------|--------------------------------------------------|
| `apiKey`  | `string` | **required**                  | API key starting with `mg_live_` or `mg_test_`  |
| `baseUrl` | `string` | `https://api.mailguard.dev`   | Override to point at your self-hosted instance   |
| `timeout` | `number` | `10000`                       | Request timeout in milliseconds                  |

---

### `mg.otp.send(options: OtpSendOptions): Promise<OtpSendResult>`

Send a one-time password to an email address.

**Options:**

| Field        | Type     | Default   | Description                          |
|--------------|----------|-----------|--------------------------------------|
| `email`      | `string` | required  | Recipient email address              |
| `purpose`    | `string` | `'login'` | Label stored on the OTP record       |
| `templateId` | `string` | —         | Optional custom email template ID    |

**Result (`OtpSendResult`):**

| Field         | Type     | Description                              |
|---------------|----------|------------------------------------------|
| `status`      | `string` | Always `'sent'` on success               |
| `expiresIn`   | `number` | Seconds until the OTP expires            |
| `maskedEmail` | `string` | Partially masked address, e.g. `u***@…` |

---

### `mg.otp.verify(options: OtpVerifyOptions): Promise<OtpVerifyResult>`

Verify a code typed by the user.

**Options:**

| Field   | Type     | Description                     |
|---------|----------|---------------------------------|
| `email` | `string` | The email the OTP was sent to   |
| `code`  | `string` | The 4–8 digit code from the user |

**Result (`OtpVerifyResult`):**

| Field       | Type      | Description                        |
|-------------|-----------|------------------------------------|
| `verified`  | `boolean` | `true` when the code is correct    |
| `token`     | `string`  | Signed JWT for the authenticated session |
| `expiresAt` | `string`  | ISO 8601 timestamp when the JWT expires  |

---

### `mg.magic.send(options: MagicLinkSendOptions): Promise<MagicLinkSendResult>`

Generate and email a single-use magic link.

**Options:**

| Field         | Type     | Description                                          |
|---------------|----------|------------------------------------------------------|
| `email`       | `string` | Recipient email address                              |
| `purpose`     | `string` | Label (e.g. `'login'`, `'signup'`)                  |
| `redirectUrl` | `string` | URL to redirect the user to after clicking the link |

**Result (`MagicLinkSendResult`):**

| Field    | Type     | Description              |
|----------|----------|--------------------------|
| `status` | `string` | Always `'sent'` on success |

---

### `mg.magic.verify(token: string): Promise<MagicLinkVerifyResult>`

Verify a raw magic link token.

**Result (`MagicLinkVerifyResult`):**

| Field         | Type      | Description                                  |
|---------------|-----------|----------------------------------------------|
| `valid`       | `boolean` | `true` when the token is valid and unused     |
| `emailHash`   | `string`  | HMAC-SHA256 hash of the verified email        |
| `projectId`   | `string`  | UUID of the project the link belongs to       |
| `purpose`     | `string`  | Purpose label the link was created with       |
| `redirectUrl` | `string`  | Redirect URL the link was created with        |

---

## Error handling

All errors extend `MailGuardError`, so a single `catch` block works for everything:

```typescript
import {
  MailGuardError,
  RateLimitError,
  InvalidCodeError,
  ExpiredError,
  LockedError,
  SandboxError,
  InvalidKeyError,
} from 'mailguard-sdk';

try {
  await mg.otp.verify({ email, code });
} catch (err) {
  if (err instanceof RateLimitError) {
    // HTTP 429 — wait before retrying
    console.log(`Retry after ${err.retryAfter} seconds`);
  } else if (err instanceof InvalidCodeError) {
    // HTTP 400 — wrong code
    console.log(`${err.attemptsRemaining} attempts left`);
  } else if (err instanceof ExpiredError) {
    // HTTP 410 — OTP or magic link expired / already used
    console.log('Code expired, please request a new one');
  } else if (err instanceof LockedError) {
    // HTTP 423 — too many failed attempts
    console.log('Account locked, contact support');
  } else if (err instanceof SandboxError) {
    // HTTP 403 — test key used in production
    console.log('Switch to a mg_live_ key for production');
  } else if (err instanceof InvalidKeyError) {
    // HTTP 401 — invalid or revoked API key
    console.log('Check your API key');
  } else if (err instanceof MailGuardError) {
    // All other API errors (5xx, unknown 4xx, timeout, network)
    console.log(`Status ${err.status}: ${err.message}`);
  }
}
```

### Error class reference

| Class             | Status | Extra properties               | Trigger                                |
|-------------------|--------|-------------------------------|----------------------------------------|
| `MailGuardError`  | any    | `status: number`              | Base class — all other errors extend it |
| `RateLimitError`  | 429    | `retryAfter: number`          | Too many requests                      |
| `InvalidCodeError`| 400    | `attemptsRemaining: number`   | Wrong OTP code                         |
| `ExpiredError`    | 410    | —                             | OTP or magic link expired / used       |
| `LockedError`     | 423    | —                             | Account locked after too many failures |
| `SandboxError`    | 403    | —                             | Test key used in production            |
| `InvalidKeyError` | 401    | —                             | Invalid or revoked API key             |

Timeout and network errors throw `MailGuardError` with `status: 0`.

---

## Configuration options

```typescript
const mg = new MailGuard({
  apiKey: 'mg_live_abc123',

  // Self-hosted Railway URL — see below
  baseUrl: 'https://your-project.up.railway.app',

  // Abort requests that take longer than 5 seconds (default: 10 000 ms)
  timeout: 5000,
});
```

---

## Self-hosting

If you are running MailGuard OSS on your own Railway instance, point `baseUrl`
at your deployment URL:

```typescript
const mg = new MailGuard({
  apiKey: process.env.MAILGUARD_API_KEY!,
  baseUrl: process.env.MAILGUARD_BASE_URL!, // e.g. https://mail-guard-prod.up.railway.app
});
```

All API paths (`/api/v1/otp/send`, `/api/v1/magic/send`, etc.) are automatically
appended to the `baseUrl`. Do not include a trailing slash.
