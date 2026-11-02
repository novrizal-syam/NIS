"""Audit trail screen and the reusable "Riwayat" (history) of one record."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import CurrentUser, Principal, require
from app.core import access
from app.core.db import get_session
from app.core.pagination import PageParams, page_params
from app.services.audit import AuditLog
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta

router = APIRouter(prefix="/audit", tags=["audit"])
Session = Annotated[AsyncSession, Depends(get_session)]
Pages = Annotated[PageParams, Depends(page_params)]
JAKARTA = ZoneInfo("Asia/Jakarta")

ACTION_LABELS = {
    "create": "Buat",
    "update": "Ubah",
    "delete": "Hapus",
    "approve": "Setujui",
    "reject": "Tolak",
    "submit": "Ajukan",
    "cancel": "Tarik",
    "escalate": "Eskalasi",
    "post": "Posting",
    "reverse": "Balik",
    "login": "Masuk",
    "login_failed": "Gagal masuk",
    "logout": "Keluar",
    "password_change": "Ganti kata sandi",
    "totp_enabled": "Aktifkan 2FA",
    "totp_reset": "Reset 2FA",
    "unlock": "Buka kunci akun",
    "upload": "Unggah lampiran",
    "archive": "Arsipkan",
    "revoke": "Cabut",
    "refresh_reuse": "Token dipakai ulang",
}


class AuditOut(BaseModel):
    id: uuid.UUID
    at: datetime
    actor_name: str | None
    action: str
    action_label: str
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    changed: list[str] | None
    note: str | None
    request_id: str | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    page_size: int


def _out(row: AuditLog, actor: str | None) -> AuditOut:
    return AuditOut(
        id=row.id,
        at=row.at,
        actor_name=actor if row.actor_id else "Sistem",
        action=row.action,
        action_label=ACTION_LABELS.get(row.action, row.action),
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        before=row.before,
        after=row.after,
        changed=row.changed,
        note=row.note,
        request_id=row.request_id,
    )


def _query(
    *,
    entity_type: str | None,
    entity_id: str | None,
    action: str | None,
    actor_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
) -> Select[Any]:
    stmt = select(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.actor_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if date_from:
        stmt = stmt.where(AuditLog.at >= datetime.combine(date_from, time.min, JAKARTA))
    if date_to:
        stmt = stmt.where(
            AuditLog.at < datetime.combine(date_to + timedelta(days=1), time.min, JAKARTA)
        )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), AuditLog.entity_id.ilike(like)))
    return stmt.order_by(AuditLog.at.desc(), AuditLog.id.desc())


AuditViewer = Annotated[Principal, Depends(require("audit", "view"))]


@router.get("")
async def search(
    _: AuditViewer,
    session: Session,
    pages: Pages,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> AuditPage:
    stmt = _query(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
    )
    total = int(
        (
            await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
    )
    rows = (await session.execute(stmt.offset(pages.offset).limit(pages.page_size))).all()
    return AuditPage(
        items=[_out(r, n) for r, n in rows], total=total, page=pages.page, page_size=pages.page_size
    )


@router.get("/facets")
async def facets(_: AuditViewer, session: Session) -> dict[str, list[dict[str, str]]]:
    types = (await session.execute(select(AuditLog.entity_type).distinct())).scalars()
    actions = (await session.execute(select(AuditLog.action).distinct())).scalars()
    return {
        "entity_types": [{"value": t, "label": t} for t in sorted(types)],
        "actions": [{"value": a, "label": ACTION_LABELS.get(a, a)} for a in sorted(actions)],
    }


@router.get("/export")
async def export(
    principal: Annotated[Principal, Depends(require("audit", "export"))],
    session: Session,
    entity_type: str | None = None,
    action: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
) -> StreamingResponse:
    stmt = _query(
        entity_type=entity_type,
        entity_id=None,
        action=action,
        actor_id=None,
        date_from=date_from,
        date_to=date_to,
        q=q,
    ).limit(20_000)
    rows = [
        {
            "at": r.at,
            "actor": n or "Sistem",
            "action": ACTION_LABELS.get(r.action, r.action),
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "changed": ", ".join(r.changed or []),
            "note": r.note,
        }
        for r, n in (await session.execute(stmt)).all()
    ]
    columns = [
        Column("Waktu", "at", "datetime"),
        Column("Pengguna", "actor", width=24),
        Column("Aksi", "action", width=16),
        Column("Jenis", "entity_type", width=20),
        Column("ID dokumen", "entity_id", width=38),
        Column("Field berubah", "changed", width=40),
        Column("Catatan", "note", width=30),
    ]
    return xlsx_response(f"jejak-audit-{today_jakarta():%Y%m%d}.xlsx", "Jejak audit", columns, rows)


@router.get("/history/{entity_type}/{entity_id}")
async def history(
    entity_type: str, entity_id: str, principal: CurrentUser, session: Session, pages: Pages
) -> AuditPage:
    """'Riwayat' tab: changes of one record, for anyone who may read that record."""
    await access.require(session, principal, entity_type, entity_id, "read")
    stmt = _query(
        entity_type=entity_type,
        entity_id=entity_id,
        action=None,
        actor_id=None,
        date_from=None,
        date_to=None,
        q=None,
    )
    total = int(
        (
            await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
    )
    rows = (await session.execute(stmt.offset(pages.offset).limit(pages.page_size))).all()
    return AuditPage(
        items=[_out(r, n) for r, n in rows], total=total, page=pages.page, page_size=pages.page_size
    )
