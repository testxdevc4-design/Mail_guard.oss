import { describe, it, expect, vi, afterEach } from 'vitest';
import { MailGuard } from '../src/index';
import {
  RateLimitError,
  InvalidCodeError,
  ExpiredError,
  LockedError,
  InvalidKeyError,
  MailGuardError,
} from '../src/index';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a minimal mock Response object for vi.stubGlobal('fetch', ...). */
function makeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    headers: new Headers(),
  } as unknown as Response;
}

/** Return a fetch mock that resolves to the given response once. */
function mockFetch(response: Response) {
  return vi.fn().mockResolvedValue(response);
}

/** Return a fetch mock that rejects with a network error. */
function networkErrorFetch() {
  return vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
}

/** Return a fetch mock that simulates an AbortError (timeout). */
function timeoutFetch() {
  const err = new DOMException('The operation was aborted.', 'AbortError');
  return vi.fn().mockRejectedValue(err);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('OTP SDK — otp.send()', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('returns correct camelCase response shape on success', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(200, {
          status: 'sent',
          expires_in: 300,
          masked_email: 'u***@example.com',
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const result = await mg.otp.send({ email: 'user@example.com' });

    expect(result.status).toBe('sent');
    expect(result.expiresIn).toBe(300);
    expect(result.maskedEmail).toBe('u***@example.com');
    // Raw snake_case keys must NOT be exposed
    expect((result as Record<string, unknown>)['expires_in']).toBeUndefined();
    expect((result as Record<string, unknown>)['masked_email']).toBeUndefined();
  });

  it('throws RateLimitError with correct retryAfter on HTTP 429', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(429, {
          detail: { error: 'rate_limit_exceeded', retry_after: 120 },
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const err = await mg.otp.send({ email: 'user@example.com' }).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(RateLimitError);
    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as RateLimitError).status).toBe(429);
    expect((err as RateLimitError).retryAfter).toBe(120);
  });

  it('throws InvalidKeyError on HTTP 401', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(401, {
          detail: { error: 'invalid_api_key' },
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'bad_key' });
    const err = await mg.otp.send({ email: 'user@example.com' }).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(InvalidKeyError);
    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as InvalidKeyError).status).toBe(401);
  });

  it('throws MailGuardError on timeout (AbortError)', async () => {
    vi.stubGlobal('fetch', timeoutFetch());

    const mg = new MailGuard({ apiKey: 'mg_live_test', timeout: 100 });
    const err = await mg.otp.send({ email: 'user@example.com' }).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as MailGuardError).message).toMatch(/timed out/i);
  });

  it('throws MailGuardError on network failure', async () => {
    vi.stubGlobal('fetch', networkErrorFetch());

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const err = await mg.otp.send({ email: 'user@example.com' }).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as MailGuardError).message).toContain('Failed to fetch');
  });
});

describe('OTP SDK — otp.verify()', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('returns verified:true with token and camelCase expiresAt', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(200, {
          verified: true,
          token: 'eyJhbGciOiJIUzI1NiJ9.test.sig',
          expires_at: '2024-12-31T23:59:59Z',
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const result = await mg.otp.verify({ email: 'user@example.com', code: '123456' });

    expect(result.verified).toBe(true);
    expect(result.token).toBe('eyJhbGciOiJIUzI1NiJ9.test.sig');
    expect(result.expiresAt).toBe('2024-12-31T23:59:59Z');
    // Raw snake_case key must NOT be exposed
    expect((result as Record<string, unknown>)['expires_at']).toBeUndefined();
  });

  it('throws InvalidCodeError with attemptsRemaining on HTTP 400', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(400, {
          detail: { error: 'invalid_code', attempts_remaining: 3 },
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const err = await mg.otp
      .verify({ email: 'user@example.com', code: '000000' })
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(InvalidCodeError);
    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as InvalidCodeError).status).toBe(400);
    expect((err as InvalidCodeError).attemptsRemaining).toBe(3);
  });

  it('throws ExpiredError on HTTP 410', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(410, {
          detail: { error: 'otp_expired' },
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const err = await mg.otp
      .verify({ email: 'user@example.com', code: '123456' })
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ExpiredError);
    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as ExpiredError).status).toBe(410);
  });

  it('throws LockedError on HTTP 423', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(423, {
          detail: { error: 'account_locked' },
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const err = await mg.otp
      .verify({ email: 'user@example.com', code: '999999' })
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(LockedError);
    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as LockedError).status).toBe(423);
  });

  it('throws InvalidKeyError on HTTP 401', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(401, {
          detail: { error: 'invalid_api_key' },
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'bad' });
    const err = await mg.otp
      .verify({ email: 'user@example.com', code: '123456' })
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(InvalidKeyError);
    expect((err as InvalidKeyError).status).toBe(401);
  });

  it('throws MailGuardError on timeout (AbortError)', async () => {
    vi.stubGlobal('fetch', timeoutFetch());

    const mg = new MailGuard({ apiKey: 'mg_live_test', timeout: 50 });
    const err = await mg.otp
      .verify({ email: 'user@example.com', code: '123456' })
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as MailGuardError).message).toMatch(/timed out/i);
    expect((err as MailGuardError).status).toBe(0);
  });

  it('throws MailGuardError on network failure', async () => {
    vi.stubGlobal('fetch', networkErrorFetch());

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const err = await mg.otp
      .verify({ email: 'user@example.com', code: '123456' })
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(MailGuardError);
  });
});
