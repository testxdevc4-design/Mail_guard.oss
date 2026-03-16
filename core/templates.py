"""
core/templates.py — Jinja2 email template rendering for MailGuard OSS.

Provides:
  render_otp_email(otp_code, expiry_minutes, project_name, purpose)
      → (subject, text_body, html_body)

  render_magic_link_email(magic_link_url, expiry_minutes, project_name)
      → (subject, text_body, html_body)

Templates live in the top-level ``templates/`` directory relative to the
repository root.  The Jinja2 Environment is created once at module import
time and is shared for all subsequent calls.
"""
from __future__ import annotations

import os
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

# ---------------------------------------------------------------------------
# Jinja2 Environment — module-level singleton
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

_env = Environment(
    loader=FileSystemLoader(os.path.abspath(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


# ---------------------------------------------------------------------------
# Public rendering functions
# ---------------------------------------------------------------------------

def render_otp_email(
    otp_code: str,
    expiry_minutes: int,
    project_name: str,
    purpose: str = "",
) -> tuple[str, str, str]:
    """Render OTP email templates.

    Returns a 3-tuple of ``(subject, text_body, html_body)``.

    Parameters
    ----------
    otp_code:
        The plaintext OTP code (e.g. ``"483920"``).
    expiry_minutes:
        Number of minutes until the code expires.
    project_name:
        Human-readable project name shown in the email header.
    purpose:
        Optional human-readable purpose string (e.g. ``"login"``).
    """
    ctx = {
        "otp_code": otp_code,
        "expiry_minutes": expiry_minutes,
        "project_name": project_name,
        "purpose": purpose,
    }
    subject = f"Your {project_name} verification code"
    text_body = _env.get_template("otp_email.txt").render(**ctx)
    html_body = _env.get_template("otp_email.html").render(**ctx)
    return subject, text_body, html_body


def render_magic_link_email(
    magic_link_url: str,
    expiry_minutes: int,
    project_name: str,
) -> tuple[str, str, str]:
    """Render magic-link email templates.

    Returns a 3-tuple of ``(subject, text_body, html_body)``.

    Parameters
    ----------
    magic_link_url:
        The full URL the user should click to authenticate.
    expiry_minutes:
        Number of minutes until the link expires.
    project_name:
        Human-readable project name shown in the email header.
    """
    ctx = {
        "magic_link_url": magic_link_url,
        "expiry_minutes": expiry_minutes,
        "project_name": project_name,
    }
    subject = f"Your {project_name} sign-in link"
    text_body = _env.get_template("magic_link_email.txt").render(**ctx)
    html_body = _env.get_template("magic_link_email.html").render(**ctx)
    return subject, text_body, html_body


def render_magic_verified_page(
    jwt_token: str,
    redirect_url: Optional[str] = None,
) -> str:
    """Render the magic_verified.html page for a successful verification.

    Parameters
    ----------
    jwt_token:
        The signed JWT issued after successful verification.
    redirect_url:
        Optional URL to redirect the user to after 2 seconds.
        If ``None``, no redirect is shown.
    """
    return _env.get_template("magic_verified.html").render(
        jwt_token=jwt_token,
        redirect_url=redirect_url,
    )


def render_magic_expired_page() -> str:
    """Render the magic_expired.html page for invalid/expired/used tokens."""
    return _env.get_template("magic_expired.html").render()
