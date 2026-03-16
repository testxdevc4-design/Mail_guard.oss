"""
core/smtp.py — Async email dispatch for MailGuard OSS.

Security contract
-----------------
* The SMTP password is decrypted inside a ``try/finally`` block.
* The ``password`` variable is set to ``None`` in the ``finally`` clause.
* The password is **never** logged, printed, or included in any exception
  message under any circumstances.

MIME layout
-----------
Every message is sent as ``MIMEMultipart('alternative')`` with:
  1. Plain-text part (added first)
  2. HTML part (added second — clients prefer the last part they support)

TLS
---
``use_tls=True`` is always passed to ``aiosmtplib.send()``.  StartTLS and
unencrypted connections are never used.
"""
from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from core.crypto import decrypt
from core.models import SenderEmail

logger = logging.getLogger(__name__)


async def send_email(
    sender: SenderEmail,
    to_address: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    """Send an email via the given *sender* SMTP configuration.

    The SMTP app password is decrypted from ``sender.app_password_enc``
    immediately before use and zeroed in the ``finally`` block.

    Parameters
    ----------
    sender:
        A :class:`~core.models.SenderEmail` row containing SMTP credentials.
    to_address:
        Recipient email address.
    subject:
        Email subject line.
    text_body:
        Plain-text email body.
    html_body:
        HTML email body.

    Raises
    ------
    Exception
        Any exception raised by ``aiosmtplib.send()`` is re-raised after
        the password has been zeroed.  The exception message will never
        contain the password value.
    """
    # Build the MIME message *before* decrypting the password so that any
    # MIME construction error cannot occur while the password is in scope.
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"{sender.display_name} <{sender.email_address}>"
    message["To"] = to_address

    # Plain text must come first; HTML second (clients prefer the last part
    # they can render, so HTML wins when supported).
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    password: Optional[str] = None
    try:
        password = decrypt(sender.app_password_enc)
        await aiosmtplib.send(
            message,
            hostname=sender.smtp_host,
            port=sender.smtp_port,
            username=sender.email_address,
            password=password,
            use_tls=True,
        )
        logger.info(
            "Email sent: to=%s subject=%r sender=%s",
            to_address,
            subject,
            sender.email_address,
        )
    except Exception as exc:
        # Log the error without including the password or decrypted value.
        logger.error(
            "SMTP send failed: to=%s sender=%s error=%s",
            to_address,
            sender.email_address,
            type(exc).__name__,
        )
        raise
    finally:
        password = None
