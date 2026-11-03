"""Outgoing email through SMTP or Resend (EMAIL_PROVIDER). Never raises: every attempt
returns sent / failed / not_configured so callers can log it and carry on. Credentials come
only from the environment."""

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Literal

import httpx

from app.core.config import get_settings

Status = Literal["sent", "failed", "not_configured"]
RESEND_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class Result:
    status: Status
    error: str | None = None


def provider() -> str | None:
    """The configured provider, or None when email is not set up."""
    s = get_settings()
    p = s.email_provider.strip().lower()
    if p == "smtp" and s.smtp_host:
        return "smtp"
    if p == "resend" and s.resend_api_key:
        return "resend"
    return None


def _sender() -> str:
    s = get_settings()
    return formataddr((s.email_from_name, s.email_from))


def build_message(to: str, subject: str, html: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _sender()
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(
        domain=get_settings().email_from.split("@")[-1] or "nustrad.local"
    )
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def _smtp_send(msg: EmailMessage) -> None:
    s = get_settings()
    if s.smtp_port == 465:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(
            s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context()
        )
    else:
        smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
    with smtp:
        if s.smtp_tls and s.smtp_port != 465:
            smtp.starttls(context=ssl.create_default_context())
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def _resend_send(to: str, subject: str, html: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {get_settings().resend_api_key}"},
            json={"from": _sender(), "to": [to], "subject": subject, "html": html, "text": text},
        )
    if res.status_code >= 300:
        raise RuntimeError(f"Resend {res.status_code}: {res.text[:200]}")


async def send_email(to: str, subject: str, html: str, text: str) -> Result:
    p = provider()
    if p is None:
        return Result("not_configured")
    try:
        if p == "smtp":
            await asyncio.to_thread(_smtp_send, build_message(to, subject, html, text))
        else:
            await _resend_send(to, subject, html, text)
    except Exception as exc:  # network, auth, provider errors: logged, never raised
        return Result("failed", f"{type(exc).__name__}: {exc}"[:500])
    return Result("sent")
