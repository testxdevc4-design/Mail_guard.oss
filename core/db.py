"""
Supabase database helpers for MailGuard OSS.

Every public function is typed and operates exclusively through the
SERVICE ROLE KEY client — the anon key is never used here.

Tables covered
--------------
  sender_emails  projects  api_keys  otp_records
  magic_links    webhooks  email_logs
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from supabase import Client, create_client

from core.config import settings
from core.models import (
    ApiKey,
    EmailLog,
    MagicLink,
    OtpRecord,
    Project,
    SenderEmail,
    Webhook,
)

# ---------------------------------------------------------------------------
# Singleton Supabase client (service-role key only)
# ---------------------------------------------------------------------------

_client: Optional[Client] = None


def get_client() -> Client:
    """Return the shared Supabase service-role client."""
    global _client
    if _client is None:
        _client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY,  # NEVER the anon key
        )
    return _client


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: Any) -> datetime:
    """Parse an ISO-8601 string returned by Supabase into a datetime."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _parse_dt_opt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    return _parse_dt(value)


# ---------------------------------------------------------------------------
# sender_emails
# ---------------------------------------------------------------------------

def _row_to_sender_email(row: Dict[str, Any]) -> SenderEmail:
    return SenderEmail(
        id=row["id"],
        email_address=row["email_address"],
        display_name=row["display_name"],
        provider=row["provider"],
        smtp_host=row["smtp_host"],
        smtp_port=int(row["smtp_port"]),
        app_password_enc=row["app_password_enc"],
        daily_limit=int(row["daily_limit"]),
        daily_sent=int(row["daily_sent"]),
        last_reset_at=_parse_dt(row["last_reset_at"]),
        is_active=bool(row["is_active"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


def insert_sender_email(data: Dict[str, Any]) -> SenderEmail:
    """Insert a row into *sender_emails* and return the created record."""
    res = get_client().table("sender_emails").insert(data).execute()
    return _row_to_sender_email(res.data[0])


def get_sender_email(sender_id: str) -> Optional[SenderEmail]:
    """Fetch a single sender_email by primary key."""
    res = (
        get_client()
        .table("sender_emails")
        .select("*")
        .eq("id", sender_id)
        .maybe_single()
        .execute()
    )
    if res.data is None:
        return None
    return _row_to_sender_email(res.data)


def list_sender_emails(is_active: Optional[bool] = None) -> List[SenderEmail]:
    """Return all sender_emails, optionally filtered by is_active."""
    q = get_client().table("sender_emails").select("*")
    if is_active is not None:
        q = q.eq("is_active", is_active)
    res = q.execute()
    return [_row_to_sender_email(r) for r in res.data]


def update_sender_email(sender_id: str, data: Dict[str, Any]) -> SenderEmail:
    """Update fields on a sender_email row and return the updated record."""
    res = (
        get_client()
        .table("sender_emails")
        .update(data)
        .eq("id", sender_id)
        .execute()
    )
    return _row_to_sender_email(res.data[0])


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

def _row_to_project(row: Dict[str, Any]) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        sender_email_id=row.get("sender_email_id"),
        otp_length=int(row["otp_length"]),
        otp_expiry_seconds=int(row["otp_expiry_seconds"]),
        otp_max_attempts=int(row["otp_max_attempts"]),
        rate_limit_per_hour=int(row["rate_limit_per_hour"]),
        template_subject=row["template_subject"],
        template_body_text=row["template_body_text"],
        template_body_html=row["template_body_html"],
        is_active=bool(row["is_active"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


def insert_project(data: Dict[str, Any]) -> Project:
    res = get_client().table("projects").insert(data).execute()
    return _row_to_project(res.data[0])


def get_project(project_id: str) -> Optional[Project]:
    res = (
        get_client()
        .table("projects")
        .select("*")
        .eq("id", project_id)
        .maybe_single()
        .execute()
    )
    if res.data is None:
        return None
    return _row_to_project(res.data)


def get_project_by_slug(slug: str) -> Optional[Project]:
    res = (
        get_client()
        .table("projects")
        .select("*")
        .eq("slug", slug)
        .maybe_single()
        .execute()
    )
    if res.data is None:
        return None
    return _row_to_project(res.data)


def list_projects(is_active: Optional[bool] = None) -> List[Project]:
    q = get_client().table("projects").select("*")
    if is_active is not None:
        q = q.eq("is_active", is_active)
    res = q.execute()
    return [_row_to_project(r) for r in res.data]


def update_project(project_id: str, data: Dict[str, Any]) -> Project:
    res = (
        get_client()
        .table("projects")
        .update(data)
        .eq("id", project_id)
        .execute()
    )
    return _row_to_project(res.data[0])


# ---------------------------------------------------------------------------
# api_keys
# ---------------------------------------------------------------------------

def _row_to_api_key(row: Dict[str, Any]) -> ApiKey:
    return ApiKey(
        id=row["id"],
        project_id=row["project_id"],
        key_hash=row["key_hash"],
        key_prefix=row["key_prefix"],
        label=row["label"],
        is_sandbox=bool(row["is_sandbox"]),
        is_active=bool(row["is_active"]),
        last_used_at=_parse_dt_opt(row.get("last_used_at")),
        created_at=_parse_dt(row["created_at"]),
    )


def insert_api_key(data: Dict[str, Any]) -> ApiKey:
    res = get_client().table("api_keys").insert(data).execute()
    return _row_to_api_key(res.data[0])


def get_api_key(key_id: str) -> Optional[ApiKey]:
    res = (
        get_client()
        .table("api_keys")
        .select("*")
        .eq("id", key_id)
        .maybe_single()
        .execute()
    )
    if res.data is None:
        return None
    return _row_to_api_key(res.data)


def get_api_key_by_hash(key_hash: str) -> Optional[ApiKey]:
    res = (
        get_client()
        .table("api_keys")
        .select("*")
        .eq("key_hash", key_hash)
        .maybe_single()
        .execute()
    )
    if res.data is None:
        return None
    return _row_to_api_key(res.data)


def list_api_keys(project_id: str) -> List[ApiKey]:
    res = (
        get_client()
        .table("api_keys")
        .select("*")
        .eq("project_id", project_id)
        .execute()
    )
    return [_row_to_api_key(r) for r in res.data]


def update_api_key(key_id: str, data: Dict[str, Any]) -> ApiKey:
    res = (
        get_client()
        .table("api_keys")
        .update(data)
        .eq("id", key_id)
        .execute()
    )
    return _row_to_api_key(res.data[0])


# ---------------------------------------------------------------------------
# otp_records
# ---------------------------------------------------------------------------

def _row_to_otp_record(row: Dict[str, Any]) -> OtpRecord:
    return OtpRecord(
        id=row["id"],
        project_id=row["project_id"],
        email_hash=row["email_hash"],
        otp_hash=row["otp_hash"],
        purpose=row["purpose"],
        attempt_count=int(row["attempt_count"]),
        otp_max_attempts=int(row["otp_max_attempts"]),
        is_verified=bool(row["is_verified"]),
        is_invalidated=bool(row["is_invalidated"]),
        expires_at=_parse_dt(row["expires_at"]),
        created_at=_parse_dt(row["created_at"]),
    )


def insert_otp_record(data: Dict[str, Any]) -> OtpRecord:
    res = get_client().table("otp_records").insert(data).execute()
    return _row_to_otp_record(res.data[0])


def get_otp_record(record_id: str) -> Optional[OtpRecord]:
    res = (
        get_client()
        .table("otp_records")
        .select("*")
        .eq("id", record_id)
        .maybe_single()
        .execute()
    )
    if res.data is None:
        return None
    return _row_to_otp_record(res.data)


def get_active_otp(project_id: str, email_hash: str) -> Optional[OtpRecord]:
    """Return the most recent non-expired, non-invalidated OTP for a project+email."""
    res = (
        get_client()
        .table("otp_records")
        .select("*")
        .eq("project_id", project_id)
        .eq("email_hash", email_hash)
        .eq("is_invalidated", False)
        .eq("is_verified", False)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return _row_to_otp_record(res.data[0])


def update_otp_record(record_id: str, data: Dict[str, Any]) -> OtpRecord:
    res = (
        get_client()
        .table("otp_records")
        .update(data)
        .eq("id", record_id)
        .execute()
    )
    return _row_to_otp_record(res.data[0])


# ---------------------------------------------------------------------------
# magic_links
# ---------------------------------------------------------------------------

def _row_to_magic_link(row: Dict[str, Any]) -> MagicLink:
    return MagicLink(
        id=row["id"],
        project_id=row["project_id"],
        email_hash=row["email_hash"],
        token_hash=row["token_hash"],
        purpose=row["purpose"],
        redirect_url=row["redirect_url"],
        is_used=bool(row["is_used"]),
        expires_at=_parse_dt(row["expires_at"]),
        created_at=_parse_dt(row["created_at"]),
    )


def insert_magic_link(data: Dict[str, Any]) -> MagicLink:
    res = get_client().table("magic_links").insert(data).execute()
    return _row_to_magic_link(res.data[0])


def get_magic_link_by_token_hash(token_hash: str) -> Optional[MagicLink]:
    res = (
        get_client()
        .table("magic_links")
        .select("*")
        .eq("token_hash", token_hash)
        .maybe_single()
        .execute()
    )
    if res.data is None:
        return None
    return _row_to_magic_link(res.data)


def update_magic_link(link_id: str, data: Dict[str, Any]) -> MagicLink:
    res = (
        get_client()
        .table("magic_links")
        .update(data)
        .eq("id", link_id)
        .execute()
    )
    return _row_to_magic_link(res.data[0])


# ---------------------------------------------------------------------------
# webhooks
# ---------------------------------------------------------------------------

def _row_to_webhook(row: Dict[str, Any]) -> Webhook:
    return Webhook(
        id=row["id"],
        project_id=row["project_id"],
        url=row["url"],
        secret_enc=row["secret_enc"],
        events=list(row.get("events") or []),
        is_active=bool(row["is_active"]),
        failure_count=int(row["failure_count"]),
        last_triggered_at=_parse_dt_opt(row.get("last_triggered_at")),
        created_at=_parse_dt(row["created_at"]),
    )


def insert_webhook(data: Dict[str, Any]) -> Webhook:
    res = get_client().table("webhooks").insert(data).execute()
    return _row_to_webhook(res.data[0])


def get_webhook(webhook_id: str) -> Optional[Webhook]:
    res = (
        get_client()
        .table("webhooks")
        .select("*")
        .eq("id", webhook_id)
        .maybe_single()
        .execute()
    )
    if res.data is None:
        return None
    return _row_to_webhook(res.data)


def list_webhooks(project_id: str) -> List[Webhook]:
    res = (
        get_client()
        .table("webhooks")
        .select("*")
        .eq("project_id", project_id)
        .execute()
    )
    return [_row_to_webhook(r) for r in res.data]


def update_webhook(webhook_id: str, data: Dict[str, Any]) -> Webhook:
    res = (
        get_client()
        .table("webhooks")
        .update(data)
        .eq("id", webhook_id)
        .execute()
    )
    return _row_to_webhook(res.data[0])


# ---------------------------------------------------------------------------
# email_logs
# ---------------------------------------------------------------------------

def _row_to_email_log(row: Dict[str, Any]) -> EmailLog:
    return EmailLog(
        id=row["id"],
        project_id=row.get("project_id"),
        sender_id=row.get("sender_id"),
        recipient_hash=row["recipient_hash"],
        purpose=row["purpose"],
        type=row["type"],
        status=row["status"],
        error_detail=row.get("error_detail"),
        sent_at=_parse_dt(row["sent_at"]),
    )


def insert_email_log(data: Dict[str, Any]) -> EmailLog:
    res = get_client().table("email_logs").insert(data).execute()
    return _row_to_email_log(res.data[0])


def get_email_log(log_id: str) -> Optional[EmailLog]:
    res = (
        get_client()
        .table("email_logs")
        .select("*")
        .eq("id", log_id)
        .maybe_single()
        .execute()
    )
    if res.data is None:
        return None
    return _row_to_email_log(res.data)


def list_email_logs(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[EmailLog]:
    q = get_client().table("email_logs").select("*")
    if project_id is not None:
        q = q.eq("project_id", project_id)
    if status is not None:
        q = q.eq("status", status)
    res = q.execute()
    return [_row_to_email_log(r) for r in res.data]


def list_email_logs_paged(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 20,
) -> List[EmailLog]:
    """Return email_logs ordered newest-first with optional filters.

    Parameters
    ----------
    project_id:
        Filter to a specific project UUID.
    status:
        Filter by delivery status (e.g. ``"sent"`` or ``"failed"``).
    since:
        Only return rows with ``sent_at >= since``.
    limit:
        Maximum number of rows to return (default 20).
    """
    q = (
        get_client()
        .table("email_logs")
        .select("*")
        .order("sent_at", desc=True)
        .limit(limit)
    )
    if project_id is not None:
        q = q.eq("project_id", project_id)
    if status is not None:
        q = q.eq("status", status)
    if since is not None:
        q = q.gte("sent_at", since.isoformat())
    res = q.execute()
    return [_row_to_email_log(r) for r in res.data]


def update_email_log(log_id: str, data: Dict[str, Any]) -> EmailLog:
    res = (
        get_client()
        .table("email_logs")
        .update(data)
        .eq("id", log_id)
        .execute()
    )
    return _row_to_email_log(res.data[0])
