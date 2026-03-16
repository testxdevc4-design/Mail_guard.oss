"""
AsyncMailGuardClient — async base HTTP client for the MailGuard SDK.

Uses aiohttp, which must be installed separately::

    pip install mailguard-sdk[async]

The import of aiohttp is deferred to inside each method so that
``from mailguard import AsyncMailGuard`` succeeds even when aiohttp
is not installed (the sync client still works normally).
"""

from typing import Any, Optional

from .exceptions import (
    ExpiredError,
    InvalidKeyError,
    LockedError,
    MailGuardError,
    RateLimitError,
    InvalidCodeError,
    SandboxError,
)

_USER_AGENT = "mailguard-sdk-python/1.0.0"
_DEFAULT_BASE_URL = "https://api.mailguard.dev"
_DEFAULT_TIMEOUT = 10


class AsyncMailGuardClient:
    """
    Asynchronous base HTTP client.

    Makes authenticated requests to the MailGuard API using aiohttp.
    aiohttp is imported lazily inside each request method so that
    importing this class does not fail when aiohttp is not installed.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        body: Optional[Any] = None,
    ) -> Any:
        """
        Execute an async HTTP request and return the parsed JSON response.

        :param method: HTTP method (GET, POST, …)
        :param path:   URL path relative to base_url
        :param body:   Optional request body, serialised to JSON
        :returns:      Parsed JSON response body
        :raises MailGuardError: (or a subclass) on any non-2xx response,
                                timeout, or network failure
        """
        # Lazy import — keeps the module importable without aiohttp installed
        try:
            import aiohttp
        except ImportError as exc:
            raise MailGuardError(
                "aiohttp is not installed. "
                "Run: pip install mailguard-sdk[async]",
                0,
            ) from exc

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": _USER_AGENT,
        }
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        url = f"{self._base_url}{path}"

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if method == "GET":
                    resp_ctx = session.get(url, headers=headers)
                else:
                    resp_ctx = session.request(
                        method, url, json=body, headers=headers
                    )

                async with resp_ctx as response:
                    if response.status < 300:
                        return await response.json(content_type=None)
                    await self._throw_typed(response)
        except MailGuardError:
            raise
        except aiohttp.ServerTimeoutError as exc:
            raise MailGuardError(
                f"Request timed out after {self._timeout}s", 0
            ) from exc
        except aiohttp.ClientError as exc:
            raise MailGuardError(str(exc) or "Network request failed", 0) from exc

    async def _throw_typed(self, response: Any) -> None:
        """
        Read the HTTP error response and raise the appropriate typed exception.
        """
        status = response.status
        raw_body: dict = {}
        try:
            raw_body = await response.json(content_type=None)
        except Exception:
            pass

        detail = raw_body.get("detail", {})
        error_key = ""
        message = f"Request failed with status {status}"
        retry_after = 60
        attempts_remaining = 0

        if isinstance(detail, str):
            message = detail
        elif isinstance(detail, dict):
            error_key = detail.get("error", "")
            message = detail.get("message", error_key or message)
            retry_after = int(detail.get("retry_after", 60))
            attempts_remaining = int(detail.get("attempts_remaining", 0))

        if status == 429:
            raise RateLimitError(message, retry_after)
        if status == 400:
            raise InvalidCodeError(message, attempts_remaining)
        if status == 410:
            raise ExpiredError(message)
        if status == 423:
            raise LockedError(message)
        if status == 403:
            if error_key == "sandbox_key_in_production":
                raise SandboxError(message)
            raise MailGuardError(message, status)
        if status == 401:
            raise InvalidKeyError(message)
        raise MailGuardError(message, status)
