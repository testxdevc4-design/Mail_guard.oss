/**
 * Magic link client — wraps the /api/v1/magic/send and
 * /api/v1/magic/verify endpoints.
 *
 * All camelCase input options are converted to snake_case before being sent
 * to the API. All snake_case keys in the API response are converted to
 * camelCase before being returned to the caller.
 */

import { MailGuardClient } from './client';
import type {
  MagicLinkSendOptions,
  MagicLinkSendResult,
  MagicLinkVerifyResult,
} from './types';

/** Raw API response shape for GET /api/v1/magic/verify/{token} (snake_case). */
interface RawMagicLinkVerifyResult {
  valid: boolean;
  email_hash: string;
  project_id: string;
  purpose: string;
  redirect_url: string;
}

export class MagicLinkClient extends MailGuardClient {
  /**
   * Send a magic link to the given email address.
   *
   * @param options - email, purpose, and redirectUrl (camelCase) — redirectUrl
   *   is automatically converted to redirect_url (snake_case) in the request.
   * @returns MagicLinkSendResult with status: 'sent'
   * @throws RateLimitError  on HTTP 429
   * @throws SandboxError    on HTTP 403 with sandbox_key_in_production
   * @throws InvalidKeyError on HTTP 401
   * @throws MailGuardError  for all other errors
   */
  async send(options: MagicLinkSendOptions): Promise<MagicLinkSendResult> {
    return this.request<MagicLinkSendResult>('POST', '/api/v1/magic/send', {
      email: options.email,
      purpose: options.purpose,
      redirect_url: options.redirectUrl,
    });
  }

  /**
   * Verify a magic link token.
   *
   * @param token - Raw magic link token extracted from the URL
   * @returns MagicLinkVerifyResult with camelCase keys
   * @throws ExpiredError    on HTTP 410 (token expired or already used)
   * @throws InvalidKeyError on HTTP 401
   * @throws MailGuardError  for all other errors
   */
  async verify(token: string): Promise<MagicLinkVerifyResult> {
    const raw = await this.request<RawMagicLinkVerifyResult>(
      'GET',
      `/api/v1/magic/verify/${encodeURIComponent(token)}`,
    );

    return {
      valid: raw.valid,
      emailHash: raw.email_hash,
      projectId: raw.project_id,
      purpose: raw.purpose,
      redirectUrl: raw.redirect_url,
    };
  }
}
