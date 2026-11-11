"""Outbox-first email.

Every message is written to the database. If SMTP is configured it is also sent;
if not, the admin console shows exactly what would have gone out, so password
reset and invites work on a laptop with no mail server.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MailMessage, utcnow


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user)


def deliver(db: Session, to_email: str, subject: str, body: str, kind: str = "notice") -> MailMessage:
    message = MailMessage(to_email=to_email.strip().lower(), subject=subject[:240], body=body, kind=kind)
    db.add(message)
    db.flush()

    if _smtp_configured():
        try:
            email = EmailMessage()
            email["From"] = settings.mail_from
            email["To"] = message.to_email
            email["Subject"] = message.subject
            email.set_content(message.body)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(email)
            message.status = "sent"
            message.sent_at = utcnow()
        except Exception as exc:  # pragma: no cover - network dependent
            message.status = "failed"
            message.error = str(exc)[:240]
    else:
        message.status = "queued"
    db.commit()
    return message


def outbox(db: Session, limit: int = 50) -> list[MailMessage]:
    return list(db.scalars(select(MailMessage).order_by(MailMessage.created_at.desc()).limit(limit)))


def invite_body(name: str, org_name: str, email: str, password: str, role: str) -> str:
    return (
        f"Hi {name},\n\n"
        f"{org_name} added you to their BrandSetGo workspace as {role}.\n\n"
        f"Sign in at {settings.public_base_url}\n"
        f"Email: {email}\n"
        f"Temporary password: {password}\n\n"
        "Change the password after your first sign-in.\n"
    )


def reset_body(name: str, link: str) -> str:
    return (
        f"Hi {name},\n\n"
        f"Use this link to set a new password (valid for 30 minutes):\n{link}\n\n"
        "If you did not ask for this, ignore the email — your password stays unchanged.\n"
    )
