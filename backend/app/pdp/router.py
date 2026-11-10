"""PDP API (10d): breach log with the 72-hour notification clock, consent register."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import PRIVACY_VERSION, CurrentUser, Principal
from app.core.db import get_session
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.notifications import service as notifications
from app.pdp.models import DataBreach
from app.services import audit
from app.workflow import engine

router = APIRouter(prefix="/pdp", tags=["admin"])
Session = Annotated[AsyncSession, Depends(get_session)]
DEADLINE = timedelta(hours=72)
OFFICERS = {"super_admin", "director"}
CATEGORIES = ("nik", "salary", "bank_account", "tax_id", "contact", "health", "other")


async def _officer(p: CurrentUser) -> Principal:
    if not p.role_codes & OFFICERS:
        raise ForbiddenError("PERMISSION_DENIED", "Hanya Direktur / Super Admin (pejabat PDP).")
    return p


Officer = Annotated[Principal, Depends(_officer)]


def _out(b: DataBreach) -> dict[str, Any]:
    due = b.detected_at + DEADLINE
    pending = b.subjects_notified_at is None or b.authority_notified_at is None
    return {
        "id": str(b.id),
        "number": b.number,
        "detected_at": b.detected_at.isoformat(),
        "notify_by": due.isoformat(),
        "overdue": pending and datetime.now(UTC) > due,
        "description": b.description,
        "data_categories": b.data_categories,
        "affected_count": b.affected_count,
        "severity": b.severity,
        "status": b.status,
        "containment": b.containment,
        "subjects_notified_at": b.subjects_notified_at.isoformat()
        if b.subjects_notified_at
        else None,
        "authority_notified_at": b.authority_notified_at.isoformat()
        if b.authority_notified_at
        else None,
        "authority_reference": b.authority_reference,
        "lessons": b.lessons,
    }


class ReportIn(BaseModel):
    detected_at: datetime
    description: str = Field(min_length=10, max_length=5000)
    data_categories: list[str] = Field(min_length=1, max_length=7)
    affected_count: int | None = Field(default=None, ge=0)
    severity: Literal["low", "medium", "high"] = "medium"


@router.post("/breaches", status_code=201)
async def report(body: ReportIn, p: CurrentUser, session: Session) -> dict[str, Any]:
    """Anyone can report a suspected breach; the PDP officers are alerted at once."""
    bad = set(body.data_categories) - set(CATEGORIES)
    if bad:
        raise AppError(
            "CATEGORY_INVALID",
            f"Kategori data tidak dikenal: {', '.join(sorted(bad))}.",
            status_code=422,
        )
    if body.detected_at > datetime.now(UTC) + timedelta(minutes=5):
        raise AppError(
            "DETECTED_FUTURE", "Waktu diketahui tidak boleh di masa depan.", status_code=422
        )
    n = (await session.execute(select(func.count()).select_from(DataBreach))).scalar_one()
    b = DataBreach(
        number=f"PDP-{datetime.now(UTC):%y}-{n + 1:03d}",
        detected_at=body.detected_at,
        description=body.description.strip(),
        data_categories=sorted(set(body.data_categories)),
        affected_count=body.affected_count,
        severity=body.severity,
        created_by=p.id,
    )
    session.add(b)
    await session.flush()
    officers = [u for role in OFFICERS for u in await engine.holders_of_role(session, role)]
    await notifications.notify(
        session,
        officers,
        kind="pdp_breach",
        title=f"Dugaan kebocoran data pribadi {b.number}",
        body=f"Wajib diberitahukan paling lambat {(b.detected_at + DEADLINE):%d/%m/%Y %H:%M} UTC.",
        link="/pengaturan/pdp",
    )
    await audit.record(
        session,
        action="report",
        entity_type="data_breach",
        entity_id=b.id,
        actor_id=p.id,
        after={"number": b.number, "severity": b.severity},
    )
    await session.commit()
    return _out(b)


@router.get("/breaches")
async def breaches(_: Officer, session: Session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(DataBreach).order_by(DataBreach.detected_at.desc()))
    ).scalars()
    return [_out(b) for b in rows]


class UpdateIn(BaseModel):
    status: Literal["reported", "investigating", "notified", "closed"] | None = None
    containment: str | None = Field(default=None, max_length=5000)
    subjects_notified: bool | None = None
    authority_notified: bool | None = None
    authority_reference: str | None = Field(default=None, max_length=120)
    lessons: str | None = Field(default=None, max_length=5000)


@router.put("/breaches/{bid}")
async def update(bid: uuid.UUID, body: UpdateIn, p: Officer, session: Session) -> dict[str, Any]:
    b = await session.get(DataBreach, bid, with_for_update=True)
    if b is None:
        raise NotFoundError("NOT_FOUND", "Laporan tidak ditemukan.")
    if b.status == "closed":
        raise ConflictError("BREACH_CLOSED", "Laporan sudah ditutup.")
    before = _out(b)
    now = datetime.now(UTC)
    if body.containment is not None:
        b.containment = body.containment
    if body.subjects_notified and b.subjects_notified_at is None:
        b.subjects_notified_at = now
    if body.authority_notified and b.authority_notified_at is None:
        b.authority_notified_at = now
    if body.authority_reference is not None:
        b.authority_reference = body.authority_reference
    if body.lessons is not None:
        b.lessons = body.lessons
    if body.status == "closed":
        if not (b.containment and b.lessons):
            raise AppError(
                "CLOSE_INCOMPLETE", "Isi penanganan dan pelajaran sebelum menutup.", status_code=422
            )
        b.closed_at = now
    if body.status:
        b.status = body.status
    await audit.record(
        session,
        action="update",
        entity_type="data_breach",
        entity_id=b.id,
        actor_id=p.id,
        before=before,
        after=_out(b),
    )
    await session.commit()
    return _out(b)


@router.get("/consents")
async def consents(_: Officer, session: Session) -> dict[str, Any]:
    """Who accepted which privacy notice version and when (accepted at first sign-in)."""
    rows = (
        await session.execute(
            select(
                User.email, User.full_name, User.privacy_version, User.privacy_accepted_at
            ).order_by(User.full_name)
        )
    ).all()
    return {
        "current_version": PRIVACY_VERSION,
        "users": [
            {
                "email": e,
                "name": n,
                "version": v,
                "accepted_at": a.isoformat() if a else None,
                "current": v == PRIVACY_VERSION,
            }
            for e, n, v, a in rows
        ],
    }


async def deadline_alerts(session: AsyncSession) -> int:
    """Breaches whose subjects/authority notification is due within 12 hours or overdue."""
    now = datetime.now(UTC)
    officers = [u for role in OFFICERS for u in await engine.holders_of_role(session, role)]
    sent = 0
    for b in (
        await session.execute(
            select(DataBreach).where(
                DataBreach.status != "closed",
                (DataBreach.subjects_notified_at.is_(None))
                | (DataBreach.authority_notified_at.is_(None)),
            )
        )
    ).scalars():
        due = b.detected_at + DEADLINE
        if now < due - timedelta(hours=12):
            continue
        stage = "late" if now > due else "12h"
        sent += await notifications.notify(
            session,
            officers,
            kind="pdp_deadline",
            title=f"{b.number}: batas pemberitahuan PDP "
            + ("terlewati" if stage == "late" else "12 jam lagi"),
            body=f"Batas {due:%d/%m/%Y %H:%M} UTC.",
            link="/pengaturan/pdp",
            dedupe_key=f"pdp-{b.id}-{stage}",
        )
    return sent
