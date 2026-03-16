"""
MailGuardClient — synchronous base HTTP client for the MailGuard SDK.

Uses only Python standard library modules (urllib.request, urllib.error,
json) so it works in any Python 3.9+ environment with zero installed
dependencies.
"""

import json
import urllib.error
import urllib.request
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


class MailGuardClient:
    """
    Synchronous base HTTP client.

    Makes authenticated requests to the MailGuard API using only the
    Python standard library — no third-party packages required.
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

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Any] = None,
    ) -> Any:
        """
        Execute an HTTP request and return the parsed JSON response.

        :param method: HTTP method (GET, POST, …)
        :param path:   URL path relative to base_url
        :param body:   Optional request body, serialised to JSON
        :returns:      Parsed JSON response body
        :raises MailGuardError: (or a subclass) on any non-2xx response,
                                timeout, or network failure
        """
        url = f"{self._base_url}{path}"
        data: Optional[bytes] = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": _USER_AGENT,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            self._throw_typed(exc)
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            if "timed out" in reason.lower():
                raise MailGuardError(
                    f"Request timed out after {self._timeout}s", 0
                ) from exc
            raise MailGuardError(reason or "Network request failed", 0) from exc
        except TimeoutError as exc:
            raise MailGuardError(
                f"Request timed out after {self._timeout}s", 0
            ) from exc

    def _throw_typed(self, exc: urllib.error.HTTPError) -> None:
        """
        Read the HTTP error response and raise the appropriate typed exception.
        """
        status = exc.code
        raw_body: dict = {}
        try:
            raw = exc.read()
            raw_body = json.loads(raw)
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
