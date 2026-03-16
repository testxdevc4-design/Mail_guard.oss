"""
MailGuard Python SDK — public entry point.

Usage::

    from mailguard import MailGuard

    mg = MailGuard(api_key="mg_live_...")
    result = mg.otp.send({"email": "user@example.com"})

    # Async usage (requires: pip install mailguard-sdk[async])
    from mailguard import AsyncMailGuard
    import asyncio

    async def main():
        mg = AsyncMailGuard(api_key="mg_live_...")
        result = await mg.otp.send({"email": "user@example.com"})

    asyncio.run(main())
"""

from .otp import OtpClient, AsyncOtpClient
from .magic import MagicLinkClient, AsyncMagicLinkClient
from .exceptions import (
    MailGuardError,
    RateLimitError,
    InvalidCodeError,
    ExpiredError,
    LockedError,
    SandboxError,
    InvalidKeyError,
)
from .types import (
    MailGuardConfig,
    OtpSendOptions,
    OtpSendResult,
    OtpVerifyOptions,
    OtpVerifyResult,
    MagicLinkSendOptions,
    MagicLinkSendResult,
    MagicLinkVerifyResult,
)

__version__ = "1.0.0"
__all__ = [
    # Main facade classes
    "MailGuard",
    "AsyncMailGuard",
    # Exceptions
    "MailGuardError",
    "RateLimitError",
    "InvalidCodeError",
    "ExpiredError",
    "LockedError",
    "SandboxError",
    "InvalidKeyError",
    # Types
    "MailGuardConfig",
    "OtpSendOptions",
    "OtpSendResult",
    "OtpVerifyOptions",
    "OtpVerifyResult",
    "MagicLinkSendOptions",
    "MagicLinkSendResult",
    "MagicLinkVerifyResult",
]

_DEFAULT_BASE_URL = "https://api.mailguard.dev"
_DEFAULT_TIMEOUT = 10


class MailGuard:
    """
    Main synchronous SDK class.

    Instantiate once and reuse across your application.

    Example::

        mg = MailGuard(api_key="mg_live_...")
        result = mg.otp.send({"email": "user@example.com"})
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        """
        :param api_key:  Your MailGuard API key (starts with mg_live_ or mg_test_).
        :param base_url: Base URL of your MailGuard instance.
                         Defaults to 'https://api.mailguard.dev'.
        :param timeout:  Request timeout in seconds. Defaults to 10.
        """
        self.otp = OtpClient(api_key=api_key, base_url=base_url, timeout=timeout)
        self.magic = MagicLinkClient(api_key=api_key, base_url=base_url, timeout=timeout)


class AsyncMailGuard:
    """
    Main asynchronous SDK class.

    Requires ``aiohttp``::

        pip install mailguard-sdk[async]

    Example::

        mg = AsyncMailGuard(api_key="mg_live_...")
        result = await mg.otp.send({"email": "user@example.com"})
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        """
        :param api_key:  Your MailGuard API key (starts with mg_live_ or mg_test_).
        :param base_url: Base URL of your MailGuard instance.
                         Defaults to 'https://api.mailguard.dev'.
        :param timeout:  Request timeout in seconds. Defaults to 10.
        """
        self.otp = AsyncOtpClient(api_key=api_key, base_url=base_url, timeout=timeout)
        self.magic = AsyncMagicLinkClient(api_key=api_key, base_url=base_url, timeout=timeout)
