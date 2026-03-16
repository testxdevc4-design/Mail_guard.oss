"""
TypedDicts for every request and response shape in the MailGuard SDK.

All types are re-exported from ``mailguard.__init__`` so users get full
type coverage with a single import::

    from mailguard import OtpSendResult, OtpVerifyResult
"""

from typing import Optional
from typing import TypedDict


class MailGuardConfig(TypedDict, total=False):
    """Configuration options for the MailGuard or AsyncMailGuard constructor."""

    api_key: str
    """Your MailGuard API key (starts with mg_live_ or mg_test_)."""

    base_url: str
    """
    Base URL of your MailGuard instance.
    Defaults to 'https://api.mailguard.dev'.
    Override to point at your self-hosted Railway URL.
    """

    timeout: int
    """
    Request timeout in seconds. Defaults to 10.
    Requests that exceed this limit raise MailGuardError.
    """


class OtpSendOptions(TypedDict, total=False):
    """Options for sending an OTP."""

    email: str
    """Recipient email address. (required)"""

    purpose: str
    """Optional purpose label (e.g. 'login', 'verify'). Defaults to 'login'."""

    template_id: str
    """Optional template ID to use for the OTP email."""


class OtpSendResult(TypedDict):
    """Successful response from MailGuard.otp.send()."""

    status: str
    """Always 'sent' on success."""

    expires_in: int
    """Number of seconds until the OTP expires."""

    masked_email: str
    """Partially masked recipient email (e.g. u***@example.com)."""


class OtpVerifyOptions(TypedDict):
    """Options for verifying an OTP."""

    email: str
    """The email address the OTP was sent to."""

    code: str
    """The 4–8 digit OTP code entered by the user."""


class OtpVerifyResult(TypedDict):
    """Successful response from MailGuard.otp.verify()."""

    verified: bool
    """True when the code is correct and not expired."""

    token: str
    """Signed JWT for authenticating the session."""

    expires_at: str
    """ISO 8601 timestamp when the JWT expires."""


class MagicLinkSendOptions(TypedDict):
    """Options for sending a magic link."""

    email: str
    """Recipient email address."""

    purpose: str
    """Purpose label (e.g. 'login', 'signup')."""

    redirect_url: str
    """URL to redirect the user to after clicking the magic link."""


class MagicLinkSendResult(TypedDict):
    """Successful response from MailGuard.magic.send()."""

    status: str
    """Always 'sent' on success."""


class MagicLinkVerifyResult(TypedDict):
    """Successful response from MailGuard.magic.verify()."""

    valid: bool
    """True when the token is valid and not yet used or expired."""

    email_hash: str
    """HMAC-SHA256 hash of the verified email address."""

    project_id: str
    """Project ID the magic link belongs to."""

    purpose: str
    """Purpose label the magic link was created with."""

    redirect_url: str
    """Redirect URL the magic link was created with."""
