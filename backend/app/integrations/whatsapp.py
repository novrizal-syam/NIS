"""WhatsApp Business (10b).

Live mode (WHATSAPP_PHONE_NUMBER_ID + WHATSAPP_TOKEN set): messages are queued and delivered by
job `whatsapp` through the WhatsApp Business Cloud API (text messages; outside the 24-hour
window Meta requires approved templates, which the API will reject until they are set up).
Manual mode: the outbox keeps the message with a wa.me link that staff open and mark as sent.
Which notification kinds also go to WhatsApp is setting `whatsapp.notify_kinds`."""

import logging
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.models import WhatsAppMessage
from app.setup import service as settings_store

log = logging.getLogger("app.whatsapp")
KINDS_KEY = "whatsapp.notify_kinds"
MAX_ATTEMPTS = 5

_transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport


def use_transport(t: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = t


def live() -> bool:
    s = get_settings()
    return bool(s.whatsapp_phone_number_id and s.whatsapp_token)


def normalise(phone: str) -> str | None:
    """Indonesian numbers to E.164 digits: 0812..., +62812..., 62812... -> 62812..."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits if 9 <= len(digits) <= 15 else None


def wa_link(msg: WhatsAppMessage) -> str:
    return f"https://wa.me/{msg.to_phone}?text={quote(msg.body)}"


async def queue(
    session: AsyncSession,
    phone: str,
    body: str,
    *,
    kind: str | None = None,
    link: str | None = None,
) -> WhatsAppMessage | None:
    to = normalise(phone)
    if to is None:
        return None
    msg = WhatsAppMessage(
        to_phone=to,
        body=body[:4000],
        kind=kind,
        link=link,
        status="queued" if live() else "manual",
    )
    session.add(msg)
    await session.flush()
    return msg


async def notify_kinds(session: AsyncSession) -> set[str]:
    return set(await settings_store.get(session, KINDS_KEY, []) or [])


async def deliver(session: AsyncSession) -> int:
    """Send queued messages (live mode only)."""
    if not live():
        return 0
    s = get_settings()
    rows = list(
        (
            await session.execute(
                select(WhatsAppMessage)
                .where(WhatsAppMessage.status == "queued", WhatsAppMessage.attempts < MAX_ATTEMPTS)
                .order_by(WhatsAppMessage.created_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    sent = 0
    async with httpx.AsyncClient(timeout=15, transport=_transport) as client:
        for m in rows:
            m.attempts += 1
            try:
                r = await client.post(
                    f"{s.whatsapp_api_url}/{s.whatsapp_phone_number_id}/messages",
                    headers={"Authorization": f"Bearer {s.whatsapp_token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "to": m.to_phone,
                        "type": "text",
                        "text": {"body": m.body},
                    },
                )
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
                data = r.json()
                m.provider_ref = (data.get("messages") or [{}])[0].get("id")
                m.status, m.sent_at, m.error = "sent", datetime.now(UTC), None
                sent += 1
            except Exception as exc:  # retried by the next run, failed after MAX_ATTEMPTS
                m.error = str(exc)[:500]
                if m.attempts >= MAX_ATTEMPTS:
                    m.status = "failed"
                log.warning("whatsapp_send_failed", extra={"id": str(m.id)})
    await session.flush()
    return sent


async def mark_sent(session: AsyncSession, msg_id: uuid.UUID) -> WhatsAppMessage | None:
    m = await session.get(WhatsAppMessage, msg_id, with_for_update=True)
    if m is None or m.status not in ("manual", "failed"):
        return m
    m.status, m.sent_at = "sent", datetime.now(UTC)
    await session.flush()
    return m
