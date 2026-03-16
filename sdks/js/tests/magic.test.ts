import { describe, it, expect, vi, afterEach } from 'vitest';
import { MailGuard } from '../src/index';
import {
  ExpiredError,
  MailGuardError,
  SandboxError,
  InvalidKeyError,
} from '../src/index';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    headers: new Headers(),
  } as unknown as Response;
}

function mockFetch(response: Response) {
  return vi.fn().mockResolvedValue(response);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Magic link SDK — magic.send()', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('returns status:sent on success', async () => {
    vi.stubGlobal('fetch', mockFetch(makeResponse(200, { status: 'sent' })));

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const result = await mg.magic.send({
      email: 'user@example.com',
      purpose: 'login',
      redirectUrl: 'https://app.example.com/dashboard',
    });

    expect(result.status).toBe('sent');
  });

  it('sends redirectUrl as redirect_url (snake_case) in the request body', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(makeResponse(200, { status: 'sent' }));
    vi.stubGlobal('fetch', fetchSpy);

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    await mg.magic.send({
      email: 'user@example.com',
      purpose: 'signup',
      redirectUrl: 'https://app.example.com/welcome',
    });

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const sentBody = JSON.parse(init.body as string) as Record<string, unknown>;

    // Must use snake_case in the request
    expect(sentBody['redirect_url']).toBe('https://app.example.com/welcome');
    // Must NOT send camelCase
    expect(sentBody['redirectUrl']).toBeUndefined();
  });

  it('throws SandboxError on HTTP 403 sandbox_key_in_production', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(403, {
          detail: { error: 'sandbox_key_in_production' },
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_test_key' });
    const err = await mg.magic
      .send({ email: 'u@e.com', purpose: 'login', redirectUrl: 'https://x.com' })
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(SandboxError);
    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as SandboxError).status).toBe(403);
  });

  it('throws MailGuardError (not SandboxError) on HTTP 403 project_inactive', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(403, {
          detail: { error: 'project_inactive' },
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const err = await mg.magic
      .send({ email: 'u@e.com', purpose: 'login', redirectUrl: 'https://x.com' })
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(MailGuardError);
    expect(err).not.toBeInstanceOf(SandboxError);
    expect((err as MailGuardError).status).toBe(403);
  });

  it('throws InvalidKeyError on HTTP 401', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(makeResponse(401, { detail: { error: 'invalid_api_key' } })),
    );

    const mg = new MailGuard({ apiKey: 'bad' });
    const err = await mg.magic
      .send({ email: 'u@e.com', purpose: 'login', redirectUrl: 'https://x.com' })
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(InvalidKeyError);
  });
});

describe('Magic link SDK — magic.verify()', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('returns correct camelCase response on success', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(200, {
          valid: true,
          email_hash: 'abc123hash',
          project_id: 'proj-uuid',
          purpose: 'login',
          redirect_url: 'https://app.example.com/dashboard',
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const result = await mg.magic.verify('some-token-abc');

    expect(result.valid).toBe(true);
    expect(result.emailHash).toBe('abc123hash');
    expect(result.projectId).toBe('proj-uuid');
    expect(result.purpose).toBe('login');
    expect(result.redirectUrl).toBe('https://app.example.com/dashboard');

    // Raw snake_case keys must NOT be exposed
    expect((result as Record<string, unknown>)['email_hash']).toBeUndefined();
    expect((result as Record<string, unknown>)['project_id']).toBeUndefined();
    expect((result as Record<string, unknown>)['redirect_url']).toBeUndefined();
  });

  it('throws ExpiredError on HTTP 410 (expired or already-used token)', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(
        makeResponse(410, {
          detail: { error: 'magic_link_expired' },
        }),
      ),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const err = await mg.magic.verify('used-token').catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ExpiredError);
    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as ExpiredError).status).toBe(410);
  });

  it('throws MailGuardError on generic server error', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(makeResponse(500, { detail: 'Internal Server Error' })),
    );

    const mg = new MailGuard({ apiKey: 'mg_live_test' });
    const err = await mg.magic.verify('any-token').catch((e: unknown) => e);

    expect(err).toBeInstanceOf(MailGuardError);
    expect((err as MailGuardError).status).toBe(500);
  });
});
