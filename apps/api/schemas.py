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
