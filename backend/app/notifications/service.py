"""Creates notifications from workflow events and expiry checks; delivers the email
outbox."""

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.master.models import Asset, Employee, Vendor
from app.notifications.models import Notification
from app.services import email
from app.services.numbering import today_jakarta
from app.workflow import engine
from app.workflow.models import ApprovalRequest
from app.workflow.rules_seed import DOC_TYPES

log = logging.getLogger("app.notifications")
MAX_EMAIL_ATTEMPTS = 5


async def notify(
    session: AsyncSession,
    user_ids: list[uuid.UUID],
    *,
    kind: str,
    title: str,
    body: str = "",
    link: str | None = None,
    dedupe_key: str | None = None,
    send_email: bool = True,
) -> int:
    """Insert one notification per user (skipped when the dedupe key was already sent)."""
    if not user_ids:
        return 0
    rows = [
        {
            "user_id": uid,
            "kind": kind,
            "title": title[:200],
            "body": body[:1000],
            "link": link,
            "dedupe_key": dedupe_key,
            "email_status": "pending" if send_email else "none",
        }
        for uid in dict.fromkeys(user_ids)
    ]
    stmt = insert(Notification).values(rows)
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
    result = await session.execute(stmt)
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# --- workflow events --------------------------------------------------------------------------


def _money(req: ApprovalRequest) -> str:
    if req.amount is None:
        return ""
    return " · Rp " + f"{int(req.amount):,}".replace(",", ".")


async def _on_workflow_event(
    session: AsyncSession, event: str, req: ApprovalRequest, recipients: list[uuid.UUID]
) -> None:
    label = DOC_TYPES[req.doc_type][0]
    link = f"/persetujuan/{req.id}"
    if event in ("submitted", "step_activated"):
        requester = await session.get(User, req.requester_id)
        by = requester.full_name if requester else "-"
        await notify(
            session,
            recipients,
            kind="approval_incoming",
            title=f"Persetujuan baru: {req.doc_number}",
            body=f"{label}: {req.title}{_money(req)}. Diajukan oleh {by}.",
            link=link,
            dedupe_key=f"wf:{req.id}:{event}:{req.current_seq}",
        )
    elif event == "approved":
        await notify(
            session,
            recipients,
            kind="approval_approved",
            title=f"{req.doc_number} disetujui",
            body=f"{label}: {req.title}.",
            link=link,
        )
    elif event == "rejected":
        reason = next((s.comment for s in req.steps if s.status == "rejected"), "") or ""
        await notify(
            session,
            recipients,
            kind="approval_returned",
            title=f"{req.doc_number} dikembalikan",
            body=f"{label}: {req.title}. Alasan: {reason}",
            link=link,
        )
    elif event == "escalated":
        await notify(
            session,
            recipients,
            kind="approval_escalated",
            title=f"Eskalasi: {req.doc_number} melewati batas waktu",
            body=f"{label}: {req.title}{_money(req)} belum diputuskan.",
            link=link,
            dedupe_key=f"wf:{req.id}:escalated:{req.current_seq}",
        )


engine.on_event(_on_workflow_event)


# --- expiry alerts ----------------------------------------------------------------------------

THRESHOLDS = (0, 30, 60, 90)
# entity, docs attribute, who is alerted, link, label
EXPIRY_SOURCES: tuple[tuple[Any, str, tuple[str, ...], str, str], ...] = (
    (Vendor, "legal_docs", ("procurement_officer",), "/master/vendors", "Dokumen vendor"),
    (
        Employee,
        "certificates",
        ("hcbp_officer", "head_of_operation"),
        "/master/employees",
        "Sertifikat karyawan",
    ),
    (
        Asset,
        "certificates",
        ("asset_inventory_coordinator", "head_of_operation"),
        "/master/assets",
        "Sertifikat aset",
    ),
)


def bucket(days_left: int) -> int | None:
    """Alert bucket: 90, 60, 30 days before, or 0 (expired). None when > 90 days."""
    for t in THRESHOLDS:
        if days_left <= t:
            return t
    return None


async def run_expiry_alerts(session: AsyncSession, today: date | None = None) -> int:
    today = today or today_jakarta()
    sent = 0
    for model, attr, roles, link, label in EXPIRY_SOURCES:
        recipients: list[uuid.UUID] = []
        for role in roles:
            recipients += await engine.holders_of_role(session, role)
        if not recipients:
            continue
        rows = (await session.execute(select(model).where(model.is_active.is_(True)))).scalars()
        for row in rows:
            name = getattr(row, "name", None) or getattr(row, "full_name", "")
            for doc in getattr(row, attr) or []:
                if not doc.get("expiry_date"):
                    continue
                expiry = date.fromisoformat(doc["expiry_date"])
                days_left = (expiry - today).days
                b = bucket(days_left)
                if b is None:
                    continue
                when = (
                    "sudah kedaluwarsa"
                    if days_left < 0
                    else (
                        "berakhir hari ini"
                        if days_left == 0
                        else f"berakhir dalam {days_left} hari"
                    )
                )
                sent += await notify(
                    session,
                    recipients,
                    kind="expiry_alert",
                    title=f"{doc['name']} {row.code} {when}",
                    body=(
                        f"{label}: {name} ({row.code}), {doc['name']} berlaku sampai "
                        f"{expiry:%d/%m/%Y}."
                        + (
                            " Tidak boleh dialokasikan sampai diperpanjang."
                            if days_left < 0
                            else ""
                        )
                    ),
                    link=link,
                    dedupe_key=f"expiry:{model.__tablename__}:{row.code}:{doc['name']}:{expiry}:{b}",
                )
    return sent


# --- email outbox -----------------------------------------------------------------------------


async def deliver_email_outbox(session: AsyncSession, limit: int = 50) -> int:
    rows = (
        await session.execute(
            select(Notification, User)
            .join(User, User.id == Notification.user_id)
            .where(Notification.email_status == "pending")
            .order_by(Notification.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True, of=Notification)
        )
    ).all()
    delivered = 0
    for n, user in rows:
        if not user.is_active:
            n.email_status = "none"
            continue
        try:
            await email.send(email.Mail(user.email, user.full_name, n.title, n.body, n.link))
        except Exception as exc:  # network/SMTP problems: retry later
            n.email_attempts += 1
            n.email_error = str(exc)[:500]
            if n.email_attempts >= MAX_EMAIL_ATTEMPTS:
                n.email_status = "failed"
            log.warning("email_failed", extra={"notification": str(n.id), "error": n.email_error})
            continue
        n.email_status, n.email_sent_at, n.email_error = "sent", datetime.now(UTC), None
        delivered += 1
    return delivered
