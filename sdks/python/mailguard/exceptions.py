"""
Typed exception subclasses for every HTTP status code the MailGuard API
can return. All subclasses extend MailGuardError so a single
``except MailGuardError`` catches everything.
"""


class MailGuardError(Exception):
    """
    Base error class for all MailGuard SDK errors.

    Exposes the HTTP status code and a human-readable message.
    ``str(error)`` always produces a readable message.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message: str = message
        self.status_code: int = status_code


class RateLimitError(MailGuardError):
    """
    Raised when the API returns HTTP 429 (Too Many Requests).

    Exposes ``retry_after``: number of seconds to wait before retrying.
    """

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message, 429)
        self.retry_after: int = retry_after


class InvalidCodeError(MailGuardError):
    """
    Raised when the API returns HTTP 400 for an invalid OTP code.

    Exposes ``attempts_remaining``: how many attempts the user has left.
    """

    def __init__(self, message: str, attempts_remaining: int) -> None:
        super().__init__(message, 400)
        self.attempts_remaining: int = attempts_remaining


class ExpiredError(MailGuardError):
    """
    Raised when the API returns HTTP 410 — the OTP or magic link has
    expired or has already been used.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, 410)


class LockedError(MailGuardError):
    """
    Raised when the API returns HTTP 423 — the account is locked due to
    too many failed verification attempts.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, 423)


class SandboxError(MailGuardError):
    """
    Raised when the API returns HTTP 403 with error key
    ``sandbox_key_in_production`` — a test API key was used against
    the production environment.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, 403)


class InvalidKeyError(MailGuardError):
    """
    Raised when the API returns HTTP 401 — the API key is invalid or
    has been revoked.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, 401)
