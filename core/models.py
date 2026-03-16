"""
Dataclass models for every MailGuard database table.
Field names match the Supabase column names exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class SenderEmail:
    id: str
    email_address: str
    display_name: str
    provider: str
    smtp_host: str
    smtp_port: int
    app_password_enc: str
    daily_limit: int
    daily_sent: int
    last_reset_at: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class Project:
    id: str
    name: str
    slug: str
    sender_email_id: Optional[str]
    otp_length: int
    otp_expiry_seconds: int
    otp_max_attempts: int
    rate_limit_per_hour: int
    template_subject: str
    template_body_text: str
    template_body_html: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class ApiKey:
    id: str
    project_id: str
    key_hash: str
    key_prefix: str
    label: str
    is_sandbox: bool
    is_active: bool
    last_used_at: Optional[datetime]
    created_at: datetime


@dataclass
class OtpRecord:
    id: str
    project_id: str
    email_hash: str
    otp_hash: str
    purpose: str
    attempt_count: int
    otp_max_attempts: int
    is_verified: bool
    is_invalidated: bool
    expires_at: datetime
    created_at: datetime


@dataclass
class MagicLink:
    id: str
    project_id: str
    email_hash: str
    token_hash: str
    purpose: str
    redirect_url: Optional[str]
    is_used: bool
    expires_at: datetime
    created_at: datetime


@dataclass
class Webhook:
    id: str
    project_id: str
    url: str
    secret_enc: str
    events: List[str]
    is_active: bool
    failure_count: int
    last_triggered_at: Optional[datetime]
    created_at: datetime


@dataclass
class EmailLog:
    id: str
    project_id: Optional[str]
    sender_id: Optional[str]
    recipient_hash: str
    purpose: str
    type: str
    status: str
    error_detail: Optional[str]
    sent_at: datetime
