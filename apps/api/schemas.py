"""
Pydantic request/response models for the MailGuard OSS API.

All route function signatures must reference these models; plain dicts in
route signatures are not permitted.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# OTP send
# ---------------------------------------------------------------------------

class OtpSendRequest(BaseModel):
    """POST /api/v1/otp/send — request body."""

    email: str
    purpose: str = "login"


class OtpSendResponse(BaseModel):
    """200 response for POST /api/v1/otp/send."""

    sent: bool
    masked_email: str


# ---------------------------------------------------------------------------
# OTP verify
# ---------------------------------------------------------------------------

class OtpVerifyRequest(BaseModel):
    """POST /api/v1/otp/verify — request body."""

    email: str
    code: str


class OtpVerifyResponse(BaseModel):
    """200 response for POST /api/v1/otp/verify."""

    verified: bool
    token: str
    otp_id: str


# ---------------------------------------------------------------------------
# Magic link send
# ---------------------------------------------------------------------------

class MagicLinkSendRequest(BaseModel):
    """POST /api/v1/magic/send — request body."""

    email: str
    purpose: str = "login"
    redirect_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Magic link verify (embedded in HTML response)
# ---------------------------------------------------------------------------

class MagicLinkVerifyResponse(BaseModel):
    """Context returned on successful magic link verification.

    This model is not returned as JSON — it describes the data embedded
    in the ``magic_verified.html`` response page.
    """

    verified: bool
    token: str
    link_id: str
