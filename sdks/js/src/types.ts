/**
 * TypeScript interfaces for every request and response shape in the
 * MailGuard SDK. All interfaces are re-exported from `index.ts` so
 * users get full type coverage with a single import.
 */

/** Configuration options passed to the MailGuard constructor. */
export interface MailGuardConfig {
  /** Your MailGuard API key (starts with mg_live_ or mg_test_). */
  apiKey: string;
  /**
   * Base URL of your MailGuard instance.
   * Defaults to 'https://api.mailguard.dev'.
   * Override to point at your self-hosted Railway URL.
   */
  baseUrl?: string;
  /**
   * Request timeout in milliseconds. Defaults to 10000 (10 seconds).
   * Requests that exceed this limit are aborted and throw a MailGuardError.
   */
  timeout?: number;
}

/** Options for sending an OTP. */
export interface OtpSendOptions {
  /** Recipient email address. */
  email: string;
  /** Optional purpose label (e.g. 'login', 'verify'). Defaults to 'login'. */
  purpose?: string;
  /** Optional template ID to use for the OTP email. */
  templateId?: string;
}

/** Successful response from otp.send(). */
export interface OtpSendResult {
  /** Always 'sent' on success. */
  status: string;
  /** Number of seconds until the OTP expires. */
  expiresIn: number;
  /** Partially masked recipient email (e.g. u***@example.com). */
  maskedEmail: string;
}

/** Options for verifying an OTP. */
export interface OtpVerifyOptions {
  /** The email address the OTP was sent to. */
  email: string;
  /** The 4–8 digit OTP code entered by the user. */
  code: string;
}

/** Successful response from otp.verify(). */
export interface OtpVerifyResult {
  /** true when the code is correct and not expired. */
  verified: boolean;
  /** Signed JWT for authenticating the session. */
  token: string;
  /** ISO 8601 timestamp when the JWT expires. */
  expiresAt: string;
}

/** Options for sending a magic link. */
export interface MagicLinkSendOptions {
  /** Recipient email address. */
  email: string;
  /** Purpose label (e.g. 'login', 'signup'). */
  purpose: string;
  /** URL to redirect the user to after clicking the magic link. */
  redirectUrl: string;
}

/** Successful response from magic.send(). */
export interface MagicLinkSendResult {
  /** Always 'sent' on success. */
  status: string;
}

/** Successful response from magic.verify(). */
export interface MagicLinkVerifyResult {
  /** true when the token is valid and not yet used or expired. */
  valid: boolean;
  /** HMAC-SHA256 hash of the verified email address. */
  emailHash: string;
  /** Project ID the magic link belongs to. */
  projectId: string;
  /** Purpose label the magic link was created with. */
  purpose: string;
  /** Redirect URL the magic link was created with. */
  redirectUrl: string;
}
