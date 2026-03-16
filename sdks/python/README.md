# mailguard-sdk (Python)

Official Python SDK for [MailGuard OSS](https://github.com/testxdevc4-design/Mail_guard.oss) — a self-hosted OTP and magic link authentication server.

---

## Installation

```bash
pip install mailguard-sdk
```

For async support (adds `aiohttp`):

```bash
pip install mailguard-sdk[async]
```

**The sync client has zero runtime dependencies.** You can use `MailGuard` immediately after `pip install mailguard-sdk` in any Python 3.9+ environment, including restricted environments without internet access to PyPI at runtime.

---

## Sync Quick Start — OTP

```python
from mailguard import MailGuard

mg = MailGuard(api_key="mg_live_...")

# Send an OTP
result = mg.otp.send({"email": "user@example.com"})
print(result["status"])       # "sent"
print(result["expires_in"])   # 300 (seconds)
print(result["masked_email"]) # "u***@example.com"

# Verify the OTP code submitted by the user
verified = mg.otp.verify({"email": "user@example.com", "code": "123456"})
print(verified["verified"])   # True
print(verified["token"])      # "eyJhbGciOiJIUzI1NiJ9..."
print(verified["expires_at"]) # "2026-01-01T00:10:00Z"
```

---

## Async Quick Start — OTP

Requires `pip install mailguard-sdk[async]`.

```python
import asyncio
from mailguard import AsyncMailGuard

async def main():
    mg = AsyncMailGuard(api_key="mg_live_...")

    # Send an OTP
    result = await mg.otp.send({"email": "user@example.com"})
    print(result["status"])       # "sent"
    print(result["expires_in"])   # 300
    print(result["masked_email"]) # "u***@example.com"

    # Verify the OTP code
    verified = await mg.otp.verify({"email": "user@example.com", "code": "123456"})
    print(verified["verified"])   # True
    print(verified["token"])      # "eyJhbGciOiJIUzI1NiJ9..."

asyncio.run(main())
```

---

## Magic Link Quick Start

```python
from mailguard import MailGuard

mg = MailGuard(api_key="mg_live_...")

# Send a magic link
result = mg.magic.send({
    "email": "user@example.com",
    "purpose": "login",
    "redirect_url": "https://yourapp.com/verify",
})
print(result["status"])  # "sent"

# Verify the token when the user clicks the link
# (token comes from the URL query parameter)
verified = mg.magic.verify("tok_abc123xyz")
print(verified["valid"])        # True
print(verified["email_hash"])   # "abc123..." (HMAC-SHA256)
print(verified["project_id"])   # "proj_xyz"
print(verified["purpose"])      # "login"
print(verified["redirect_url"]) # "https://yourapp.com/verify"
```

---

## All Methods

### `MailGuard` / `AsyncMailGuard`

Both classes expose `.otp` and `.magic` sub-clients.

```python
mg = MailGuard(
    api_key: str,                               # required
    base_url: str = "https://api.mailguard.dev", # optional
    timeout: int = 10,                          # seconds, optional
)

async_mg = AsyncMailGuard(
    api_key: str,
    base_url: str = "https://api.mailguard.dev",
    timeout: int = 10,
)
```

---

### OTP Methods

#### `mg.otp.send(options) → OtpSendResult`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `email` | `str` | ✓ | — | Recipient email address |
| `purpose` | `str` | | `"login"` | Purpose label (e.g. `"verify"`) |
| `template_id` | `str` | | — | Custom email template ID |

**Returns** `OtpSendResult`:

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | Always `"sent"` |
| `expires_in` | `int` | Seconds until expiry |
| `masked_email` | `str` | Partially masked recipient email |

---

#### `mg.otp.verify(options) → OtpVerifyResult`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email` | `str` | ✓ | The email the OTP was sent to |
| `code` | `str` | ✓ | The OTP code entered by the user |

**Returns** `OtpVerifyResult`:

| Field | Type | Description |
|-------|------|-------------|
| `verified` | `bool` | `True` when correct and not expired |
| `token` | `str` | Signed JWT for authenticating the session |
| `expires_at` | `str` | ISO 8601 timestamp when the JWT expires |

---

### Magic Link Methods

#### `mg.magic.send(options) → MagicLinkSendResult`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `email` | `str` | ✓ | Recipient email address |
| `purpose` | `str` | ✓ | Purpose label (e.g. `"login"`) |
| `redirect_url` | `str` | ✓ | URL to redirect after clicking the link |

**Returns** `MagicLinkSendResult`:

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | Always `"sent"` |

---

#### `mg.magic.verify(token) → MagicLinkVerifyResult`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `token` | `str` | ✓ | Raw token from the URL query parameter |

**Returns** `MagicLinkVerifyResult`:

| Field | Type | Description |
|-------|------|-------------|
| `valid` | `bool` | `True` when token is valid and unused |
| `email_hash` | `str` | HMAC-SHA256 hash of the verified email |
| `project_id` | `str` | Project the magic link belongs to |
| `purpose` | `str` | Purpose label the link was created with |
| `redirect_url` | `str` | Redirect URL the link was created with |

---

## Error Handling

All errors inherit from `MailGuardError` so a single `except` catches everything:

```python
from mailguard import MailGuard
from mailguard.exceptions import (
    MailGuardError,
    RateLimitError,
    InvalidCodeError,
    ExpiredError,
    LockedError,
    SandboxError,
    InvalidKeyError,
)

mg = MailGuard(api_key="mg_live_...")

try:
    result = mg.otp.verify({"email": "user@example.com", "code": "000000"})

except RateLimitError as e:
    # HTTP 429 — too many requests
    print(f"Rate limited. Retry after {e.retry_after}s")  # e.retry_after: int

except InvalidCodeError as e:
    # HTTP 400 — wrong OTP code
    print(f"Wrong code. {e.attempts_remaining} attempts left")  # e.attempts_remaining: int

except ExpiredError as e:
    # HTTP 410 — OTP or magic link expired / already used
    print(f"Expired: {e.message}")

except LockedError as e:
    # HTTP 423 — account locked after too many failed attempts
    print(f"Account locked: {e.message}")

except SandboxError as e:
    # HTTP 403 with sandbox_key_in_production
    print("Test key used in production environment")

except InvalidKeyError as e:
    # HTTP 401 — invalid or revoked API key
    print(f"Invalid API key: {e.message}")

except MailGuardError as e:
    # Catch-all for any other error (network, timeout, unexpected status)
    print(f"Error {e.status_code}: {e.message}")
```

### Exception Attributes

| Exception | HTTP Status | Extra Attributes |
|-----------|-------------|-----------------|
| `MailGuardError` | any | `.status_code: int`, `.message: str` |
| `RateLimitError` | 429 | `.retry_after: int` |
| `InvalidCodeError` | 400 | `.attempts_remaining: int` |
| `ExpiredError` | 410 | — |
| `LockedError` | 423 | — |
| `SandboxError` | 403 | — |
| `InvalidKeyError` | 401 | — |

All exceptions produce a human-readable message via `str(error)`.

---

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `api_key` | `str` | required | Your MailGuard API key |
| `base_url` | `str` | `"https://api.mailguard.dev"` | Base URL of your MailGuard instance |
| `timeout` | `int` | `10` | Request timeout in seconds |

```python
mg = MailGuard(
    api_key="mg_live_...",
    base_url="https://api.mailguard.dev",  # or your Railway URL
    timeout=30,
)
```

---

## Self-Hosting

If you are running MailGuard on your own Railway deployment, set `base_url` to your Railway API service URL:

```python
mg = MailGuard(
    api_key="mg_live_...",
    base_url="https://mailguard-api-production.up.railway.app",
)
```

The SDK will automatically strip any trailing slash and route all requests through your instance.

---

## Async Installation

```bash
pip install mailguard-sdk[async]
```

This installs `aiohttp>=3.8` as an additional dependency. The `AsyncMailGuard` class lazy-imports `aiohttp` inside each request method, so `from mailguard import AsyncMailGuard` succeeds even when `aiohttp` is not installed — the import only fails if you actually call an async method without `aiohttp` present.

---

## Type Checking

All response shapes are `TypedDict` instances. Import them for use in type annotations:

```python
from mailguard import (
    OtpSendResult,
    OtpVerifyResult,
    MagicLinkSendResult,
    MagicLinkVerifyResult,
)

def process_otp_result(result: OtpSendResult) -> None:
    print(result["expires_in"])  # IDE knows this is int
```

---

## License

MIT
