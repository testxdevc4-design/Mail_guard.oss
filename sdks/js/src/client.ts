/**
 * MailGuardClient — base HTTP client for the MailGuard SDK.
 *
 * Features:
 * - Zero runtime dependencies (uses native fetch from Node 18+ / browsers)
 * - AbortController-based configurable timeout (default 10 000 ms)
 * - Typed error subclass dispatch via _throwTyped()
 * - Bearer token authentication
 */

import {
  MailGuardError,
  RateLimitError,
  InvalidCodeError,
  ExpiredError,
  LockedError,
  SandboxError,
  InvalidKeyError,
} from './errors';
import type { MailGuardConfig } from './types';

export class MailGuardClient {
  protected readonly apiKey: string;
  protected readonly baseUrl: string;
  protected readonly timeout: number;

  constructor(config: MailGuardConfig) {
    if (typeof fetch === 'undefined') {
      throw new MailGuardError(
        'fetch is not available in this environment. ' +
          'Use Node 18+ or a browser that supports the Fetch API.',
        0,
      );
    }
    this.apiKey = config.apiKey;
    this.baseUrl = (config.baseUrl ?? 'https://api.mailguard.dev').replace(/\/$/, '');
    this.timeout = config.timeout ?? 10_000;
  }

  /**
   * Execute an HTTP request with a configurable AbortController timeout.
   *
   * @param method - HTTP method (GET, POST, …)
   * @param path   - URL path relative to baseUrl (e.g. '/api/v1/otp/send')
   * @param body   - Optional request body, serialised to JSON
   * @returns Parsed JSON response body typed as T
   * @throws MailGuardError (or a subclass) on any non-2xx response or timeout
   */
  protected async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.apiKey}`,
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });

      if (!response.ok) {
        await this._throwTyped(response);
      }

      return response.json() as Promise<T>;
    } catch (err) {
      if (err instanceof MailGuardError) {
        throw err;
      }
      if (err instanceof Error && err.name === 'AbortError') {
        throw new MailGuardError(`Request timed out after ${this.timeout}ms`, 0);
      }
      throw new MailGuardError(
        err instanceof Error ? err.message : 'Network request failed',
        0,
      );
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Inspect the HTTP status code AND the error key in the response body to
   * determine which typed error subclass to throw.
   *
   * Status code alone is not sufficient: HTTP 403 can be either SandboxError
   * (sandbox_key_in_production) or a plain MailGuardError (project_inactive).
   *
   * FastAPI wraps error detail in a `detail` key. Both string and object
   * `detail` values are handled.
   */
  protected async _throwTyped(response: Response): Promise<never> {
    let rawBody: Record<string, unknown> = {};
    try {
      rawBody = (await response.json()) as Record<string, unknown>;
    } catch {
      // JSON parse failed — proceed with empty body
    }

    const status = response.status;

    // FastAPI wraps error detail in the `detail` key; unwrap if present.
    const detail = rawBody.detail;
    let errorKey = '';
    let message = `Request failed with status ${status}`;
    let retryAfter = 60;
    let attemptsRemaining = 0;

    if (typeof detail === 'string') {
      message = detail;
    } else if (typeof detail === 'object' && detail !== null) {
      const d = detail as Record<string, unknown>;
      errorKey = typeof d['error'] === 'string' ? d['error'] : '';
      message =
        typeof d['message'] === 'string'
          ? d['message']
          : errorKey !== ''
            ? errorKey
            : message;
      retryAfter = typeof d['retry_after'] === 'number' ? d['retry_after'] : 60;
      attemptsRemaining =
        typeof d['attempts_remaining'] === 'number' ? d['attempts_remaining'] : 0;
    }

    switch (status) {
      case 429:
        throw new RateLimitError(message, retryAfter);

      case 400:
        throw new InvalidCodeError(message, attemptsRemaining);

      case 410:
        throw new ExpiredError(message);

      case 423:
        throw new LockedError(message);

      case 403:
        if (errorKey === 'sandbox_key_in_production') {
          throw new SandboxError(message);
        }
        throw new MailGuardError(message, status);

      case 401:
        throw new InvalidKeyError(message);

      default:
        throw new MailGuardError(message, status);
    }
  }
}
