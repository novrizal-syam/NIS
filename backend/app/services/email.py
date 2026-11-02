"""Outgoing email (SMTP; Mailpit in dev). Sending is done by the outbox job, never inside
a business transaction, so a rolled-back change never sends mail."""

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.core.config import get_settings

FOOTER = "\n\n--\nPesan otomatis dari Nustrad ERP untuk PT Global Energi KITA. Jangan dibalas."


@dataclass(frozen=True)
class Mail:
    to: str
    to_name: str
    subject: str
    text: str
    link: str | None = None


def build(mail: Mail) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.mail_from
    msg["To"] = formataddr((mail.to_name, mail.to))
    msg["Subject"] = mail.subject
    msg["Message-ID"] = make_msgid(domain="nustrad.local")
    body = mail.text
    if mail.link:
        body += f"\n\nBuka: {s.app_base_url.rstrip('/')}{mail.link}"
    msg.set_content(body + FOOTER)
    return msg


def _send_sync(msg: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
        if s.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def send(mail: Mail) -> None:
    await asyncio.to_thread(_send_sync, build(mail))
