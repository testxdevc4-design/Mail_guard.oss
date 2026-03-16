"""
Pydantic request/response models for the MailGuard OSS OTP API.

All route function signatures must reference these models; plain dicts in
route signatures are not permitted.
"""
from __future__ import annotations

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
    redirect_url: str = ""


# ---------------------------------------------------------------------------
# Magic link verify
# ---------------------------------------------------------------------------

class MagicLinkVerifyResponse(BaseModel):
    """Context passed to magic_verified.html on successful token verification."""

    verified: bool
    token: str
    magic_link_id: str
    redirect_url: str
