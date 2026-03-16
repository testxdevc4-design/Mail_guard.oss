/**
 * MailGuard SDK — public entry point.
 *
 * Usage:
 *   import { MailGuard } from 'mailguard-sdk';          // ESM
 *   const { MailGuard } = require('mailguard-sdk');     // CJS
 */

import { OtpClient } from './otp';
import { MagicLinkClient } from './magic';
import type { MailGuardConfig } from './types';

/**
 * Main SDK class. Instantiate once and reuse across your application.
 *
 * @example
 * const mg = new MailGuard({ apiKey: 'mg_live_...' });
 * await mg.otp.send({ email: 'user@example.com' });
 */
export class MailGuard {
  /** OTP send and verify methods. */
  public readonly otp: OtpClient;

  /** Magic link send and verify methods. */
  public readonly magic: MagicLinkClient;

  constructor(config: MailGuardConfig) {
    this.otp = new OtpClient(config);
    this.magic = new MagicLinkClient(config);
  }
}

// Re-export all types so users get full type coverage with a single import
export type {
  MailGuardConfig,
  OtpSendOptions,
  OtpSendResult,
  OtpVerifyOptions,
  OtpVerifyResult,
  MagicLinkSendOptions,
  MagicLinkSendResult,
  MagicLinkVerifyResult,
} from './types';

export {
  MailGuardError,
  RateLimitError,
  InvalidCodeError,
  ExpiredError,
  LockedError,
  SandboxError,
  InvalidKeyError,
} from './errors';
