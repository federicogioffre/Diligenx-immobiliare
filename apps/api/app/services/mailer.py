"""Outbound email, gated on SMTP configuration.

When ``SMTP_HOST`` is configured (e.g. Hostinger Titan:
``smtp.titan.email`` on port 465/SSL) messages are sent for real.
When it is empty — local dev, tests, deploys that haven't set up
mailboxes yet — the message is logged instead, so flows that send
email (password reset) remain fully testable end-to-end: the reset
link is readable in the API logs.

Sending is best-effort by design: callers that must not reveal
whether an email exists (forgot-password) ignore the return value.
"""
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(settings.SMTP_HOST)


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if handed to the SMTP server.

    Falls back to logging the full message when SMTP is not configured,
    and logs (without raising) on SMTP errors — email failures must never
    turn into user-facing 500s on auth flows.
    """
    if not smtp_configured():
        logger.info(
            "[mailer] SMTP not configured — email to %s NOT sent.\n"
            "Subject: %s\n%s",
            to, subject, body,
        )
        return False

    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
        logger.info("[mailer] Sent '%s' to %s", subject, to)
        return True
    except Exception:
        logger.exception("[mailer] Failed to send '%s' to %s", subject, to)
        return False
