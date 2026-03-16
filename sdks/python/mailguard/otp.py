"""
OTP client — wraps the /api/v1/otp/send and /api/v1/otp/verify endpoints.

All API response fields are kept in snake_case, matching Python conventions.
Returns TypedDicts for IDE autocompletion without external type stubs.
"""

from .client import MailGuardClient
from .async_client import AsyncMailGuardClient
from .types import OtpSendOptions, OtpSendResult, OtpVerifyOptions, OtpVerifyResult


class OtpClient(MailGuardClient):
    """Synchronous OTP client."""

    def send(self, options: OtpSendOptions) -> OtpSendResult:
        """
        Send an OTP to the given email address.

        :param options: OtpSendOptions with ``email``, optional ``purpose``
                        (defaults to 'login'), and optional ``template_id``.
        :returns: OtpSendResult TypedDict with ``status``, ``expires_in``,
                  and ``masked_email``.
        :raises RateLimitError:  on HTTP 429
        :raises SandboxError:    on HTTP 403 with sandbox_key_in_production
        :raises InvalidKeyError: on HTTP 401
        :raises MailGuardError:  for all other errors
        """
        body: dict = {
            "email": options["email"],
            "purpose": options.get("purpose", "login"),
        }
        if "template_id" in options:
            body["template_id"] = options["template_id"]

        raw = self._request("POST", "/api/v1/otp/send", body)
        return OtpSendResult(
            status=raw["status"],
            expires_in=raw["expires_in"],
            masked_email=raw["masked_email"],
        )

    def verify(self, options: OtpVerifyOptions) -> OtpVerifyResult:
        """
        Verify an OTP code submitted by the user.

        :param options: OtpVerifyOptions with ``email`` and ``code``.
        :returns: OtpVerifyResult TypedDict with ``verified``, ``token``,
                  and ``expires_at``.
        :raises InvalidCodeError: on HTTP 400 (wrong code); exposes
                                  ``attempts_remaining``
        :raises ExpiredError:     on HTTP 410 (OTP expired)
        :raises LockedError:      on HTTP 423 (account locked)
        :raises RateLimitError:   on HTTP 429
        :raises InvalidKeyError:  on HTTP 401
        :raises MailGuardError:   for all other errors
        """
        raw = self._request(
            "POST",
            "/api/v1/otp/verify",
            {"email": options["email"], "code": options["code"]},
        )
        return OtpVerifyResult(
            verified=raw["verified"],
            token=raw["token"],
            expires_at=raw["expires_at"],
        )


class AsyncOtpClient(AsyncMailGuardClient):
    """Asynchronous OTP client."""

    async def send(self, options: OtpSendOptions) -> OtpSendResult:
        """
        Async version of OtpClient.send().

        :param options: OtpSendOptions with ``email``, optional ``purpose``
                        (defaults to 'login'), and optional ``template_id``.
        :returns: OtpSendResult TypedDict.
        """
        body: dict = {
            "email": options["email"],
            "purpose": options.get("purpose", "login"),
        }
        if "template_id" in options:
            body["template_id"] = options["template_id"]

        raw = await self._request("POST", "/api/v1/otp/send", body)
        return OtpSendResult(
            status=raw["status"],
            expires_in=raw["expires_in"],
            masked_email=raw["masked_email"],
        )

    async def verify(self, options: OtpVerifyOptions) -> OtpVerifyResult:
        """
        Async version of OtpClient.verify().

        :param options: OtpVerifyOptions with ``email`` and ``code``.
        :returns: OtpVerifyResult TypedDict.
        """
        raw = await self._request(
            "POST",
            "/api/v1/otp/verify",
            {"email": options["email"], "code": options["code"]},
        )
        return OtpVerifyResult(
            verified=raw["verified"],
            token=raw["token"],
            expires_at=raw["expires_at"],
        )
