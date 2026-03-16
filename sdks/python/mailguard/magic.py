"""
Magic link client — wraps the /api/v1/magic/send and
/api/v1/magic/verify endpoints.

All API response fields are kept in snake_case, matching Python conventions.
Returns TypedDicts for IDE autocompletion without external type stubs.
"""

from .client import MailGuardClient
from .async_client import AsyncMailGuardClient
from .types import (
    MagicLinkSendOptions,
    MagicLinkSendResult,
    MagicLinkVerifyResult,
)


class MagicLinkClient(MailGuardClient):
    """Synchronous magic link client."""

    def send(self, options: MagicLinkSendOptions) -> MagicLinkSendResult:
        """
        Send a magic link to the given email address.

        :param options: MagicLinkSendOptions with ``email``, ``purpose``,
                        and ``redirect_url``.
        :returns: MagicLinkSendResult TypedDict with ``status: 'sent'``.
        :raises RateLimitError:  on HTTP 429
        :raises SandboxError:    on HTTP 403 with sandbox_key_in_production
        :raises InvalidKeyError: on HTTP 401
        :raises MailGuardError:  for all other errors
        """
        raw = self._request(
            "POST",
            "/api/v1/magic/send",
            {
                "email": options["email"],
                "purpose": options["purpose"],
                "redirect_url": options["redirect_url"],
            },
        )
        return MagicLinkSendResult(status=raw["status"])

    def verify(self, token: str) -> MagicLinkVerifyResult:
        """
        Verify a magic link token.

        :param token: Raw magic link token extracted from the URL.
        :returns: MagicLinkVerifyResult TypedDict with ``valid``,
                  ``email_hash``, ``project_id``, ``purpose``,
                  and ``redirect_url``.
        :raises ExpiredError:    on HTTP 410 (token expired or already used)
        :raises InvalidKeyError: on HTTP 401
        :raises MailGuardError:  for all other errors
        """
        import urllib.parse

        raw = self._request(
            "GET",
            f"/api/v1/magic/verify/{urllib.parse.quote(token, safe='')}",
        )
        return MagicLinkVerifyResult(
            valid=raw["valid"],
            email_hash=raw["email_hash"],
            project_id=raw["project_id"],
            purpose=raw["purpose"],
            redirect_url=raw["redirect_url"],
        )


class AsyncMagicLinkClient(AsyncMailGuardClient):
    """Asynchronous magic link client."""

    async def send(self, options: MagicLinkSendOptions) -> MagicLinkSendResult:
        """
        Async version of MagicLinkClient.send().

        :param options: MagicLinkSendOptions with ``email``, ``purpose``,
                        and ``redirect_url``.
        :returns: MagicLinkSendResult TypedDict.
        """
        raw = await self._request(
            "POST",
            "/api/v1/magic/send",
            {
                "email": options["email"],
                "purpose": options["purpose"],
                "redirect_url": options["redirect_url"],
            },
        )
        return MagicLinkSendResult(status=raw["status"])

    async def verify(self, token: str) -> MagicLinkVerifyResult:
        """
        Async version of MagicLinkClient.verify().

        :param token: Raw magic link token extracted from the URL.
        :returns: MagicLinkVerifyResult TypedDict.
        """
        import urllib.parse

        raw = await self._request(
            "GET",
            f"/api/v1/magic/verify/{urllib.parse.quote(token, safe='')}",
        )
        return MagicLinkVerifyResult(
            valid=raw["valid"],
            email_hash=raw["email_hash"],
            project_id=raw["project_id"],
            purpose=raw["purpose"],
            redirect_url=raw["redirect_url"],
        )
