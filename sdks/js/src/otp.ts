/**
 * OTP client — wraps the /api/v1/otp/send and /api/v1/otp/verify endpoints.
 *
 * All snake_case keys from the API are converted to camelCase before being
 * returned to the caller. All camelCase input options are converted to
 * snake_case before being sent to the API.
 */

import { MailGuardClient } from './client';
import type {
  OtpSendOptions,
  OtpSendResult,
  OtpVerifyOptions,
  OtpVerifyResult,
} from './types';

/** Raw API response shape for POST /api/v1/otp/send (snake_case). */
interface RawOtpSendResult {
  status: string;
  expires_in: number;
  masked_email: string;
}

/** Raw API response shape for POST /api/v1/otp/verify (snake_case). */
interface RawOtpVerifyResult {
  verified: boolean;
  token: string;
  expires_at: string;
}

export class OtpClient extends MailGuardClient {
  /**
   * Send an OTP to the given email address.
   *
   * @returns OtpSendResult with camelCase keys (status, expiresIn, maskedEmail)
   * @throws RateLimitError  on HTTP 429
   * @throws SandboxError    on HTTP 403 with sandbox_key_in_production
   * @throws InvalidKeyError on HTTP 401
   * @throws MailGuardError  for all other errors
   */
  async send(options: OtpSendOptions): Promise<OtpSendResult> {
    const raw = await this.request<RawOtpSendResult>('POST', '/api/v1/otp/send', {
      email: options.email,
      purpose: options.purpose ?? 'login',
      ...(options.templateId !== undefined ? { template_id: options.templateId } : {}),
    });

    return {
      status: raw.status,
      expiresIn: raw.expires_in,
      maskedEmail: raw.masked_email,
    };
  }

  /**
   * Verify an OTP code submitted by the user.
   *
   * @returns OtpVerifyResult with camelCase keys (verified, token, expiresAt)
   * @throws InvalidCodeError on HTTP 400 (wrong code); exposes attemptsRemaining
   * @throws ExpiredError     on HTTP 410 (OTP expired)
   * @throws LockedError      on HTTP 423 (account locked)
   * @throws RateLimitError   on HTTP 429
   * @throws InvalidKeyError  on HTTP 401
   * @throws MailGuardError   for all other errors
   */
  async verify(options: OtpVerifyOptions): Promise<OtpVerifyResult> {
    const raw = await this.request<RawOtpVerifyResult>('POST', '/api/v1/otp/verify', {
      email: options.email,
      code: options.code,
    });

    return {
      verified: raw.verified,
      token: raw.token,
      expiresAt: raw.expires_at,
    };
  }
}
