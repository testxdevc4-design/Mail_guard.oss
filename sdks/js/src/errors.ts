/**
 * Typed error subclasses for every HTTP status code the MailGuard API
 * can return. All subclasses extend MailGuardError so a single
 * `catch (e instanceof MailGuardError)` catches everything.
 */

/**
 * Base error class for all MailGuard SDK errors.
 * Exposes the HTTP status code and a human-readable message.
 */
export class MailGuardError extends Error {
  public readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'MailGuardError';
    this.status = status;
    // Restore correct prototype chain in environments that transpile classes
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown when the API returns HTTP 429 (Too Many Requests).
 * Exposes `retryAfter`: number of seconds to wait before retrying.
 */
export class RateLimitError extends MailGuardError {
  public readonly retryAfter: number;

  constructor(message: string, retryAfter: number) {
    super(message, 429);
    this.name = 'RateLimitError';
    this.retryAfter = retryAfter;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown when the API returns HTTP 400 for an invalid OTP code.
 * Exposes `attemptsRemaining`: how many attempts the user has left.
 */
export class InvalidCodeError extends MailGuardError {
  public readonly attemptsRemaining: number;

  constructor(message: string, attemptsRemaining: number) {
    super(message, 400);
    this.name = 'InvalidCodeError';
    this.attemptsRemaining = attemptsRemaining;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown when the API returns HTTP 410 — the OTP or magic link has
 * expired or has already been used.
 */
export class ExpiredError extends MailGuardError {
  constructor(message: string) {
    super(message, 410);
    this.name = 'ExpiredError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown when the API returns HTTP 423 — the account is locked due to
 * too many failed verification attempts.
 */
export class LockedError extends MailGuardError {
  constructor(message: string) {
    super(message, 423);
    this.name = 'LockedError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown when the API returns HTTP 403 with error key
 * 'sandbox_key_in_production' — a test API key was used against the
 * production environment.
 */
export class SandboxError extends MailGuardError {
  constructor(message: string) {
    super(message, 403);
    this.name = 'SandboxError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown when the API returns HTTP 401 for an invalid or revoked API key.
 */
export class InvalidKeyError extends MailGuardError {
  constructor(message: string) {
    super(message, 401);
    this.name = 'InvalidKeyError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}
