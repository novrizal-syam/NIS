import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import Principal, require, scope_filter
from app.contract import service
from app.contract.models import Contract
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.crm.models import Opportunity, Quotation
from app.project.models import Project
from app.services import audit
from app.services.audit import AuditAction
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta

router = APIRouter(prefix="/contracts", tags=["contract"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("contract", "view"))]
Editor = Annotated[Principal, Depends(require("contract", "edit"))]
Exporter = Annotated[Principal, Depends(require("contract", "export"))]


def may(principal: Principal, action: str, owner_id: uuid.UUID) -> bool:
    scope = principal.scope_for("contract", action)
    return scope is not None and (scope == Scope.ALL or owner_id == principal.id)


async def _check(
    session: AsyncSession, principal: Principal, entity_id: str, mode: access.Mode
) -> bool:
    try:
        c = await session.get(Contract, uuid.UUID(entity_id))
    except ValueError:
        return False
    return c is not None and may(principal, "view" if mode == "read" else "edit", c.owner_id)


access.register("contract", _check)


def usage_pct(c: Contract) -> Decimal | None:
    if c.value <= 0:
        return None
    return (c.used_value / c.value * 100).quantize(Decimal("0.1"))


def _row(c: Contract, owner: str | None, project: tuple[Any, str] | None) -> dict[str, Any]:
    pct = usage_pct(c)
    return {
        "id": str(c.id),
        "number": c.number,
        "title": c.title,
        "company_name": c.company_name,
        "client_code": c.client_code,
        "status": c.status,
        "value": format(c.value, "f"),
        "used_value": format(c.used_value, "f"),
        "usage_pct": str(pct) if pct is not None else None,
        "po_number": c.po_number,
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None,
        "payment_term_days": c.payment_term_days,
        "owner_name": owner,
        "project_id": str(project[0]) if project else None,
        "project_number": project[1] if project else None,
        "created_at": c.created_at.isoformat(),
        "is_demo": c.is_demo,
    }


async def _rows(session: AsyncSession, items: list[Contract]) -> list[dict[str, Any]]:
    if not items:
        return []
    names = dict(
        (
            await session.execute(
                select(User.id, User.full_name).where(User.id.in_({c.owner_id for c in items}))
            )
        )
        .tuples()
        .all()
    )
    projects = {
        cid: (pid, num)
        for cid, pid, num in (
            await session.execute(
                select(Project.contract_id, Project.id, Project.number).where(
                    Project.contract_id.in_([c.id for c in items])
                )
            )
        ).tuples()
    }
    return [_row(c, names.get(c.owner_id), projects.get(c.id)) for c in items]


def _query(principal: Principal, action: str, q: str | None, status: str | None) -> Select[Any]:
    stmt = select(Contract).where(
        scope_filter(principal, "contract", action, owner_col=Contract.owner_id)
    )
    if status:
        stmt = stmt.where(Contract.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Contract.number.ilike(like),
                Contract.title.ilike(like),
                Contract.company_name.ilike(like),
                Contract.po_number.ilike(like),
            )
        )
    return stmt


@router.get("")
async def list_contracts(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    q: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    stmt = _query(principal, "view", q, status)
    sub = stmt.subquery()
    total, value = (
        await session.execute(select(func.count(), func.coalesce(func.sum(sub.c.value), 0)))
    ).one()
    items = (
        await session.execute(
            stmt.order_by(Contract.created_at.desc()).offset(paging.offset).limit(paging.page_size)
        )
    ).scalars()
    return {
        "items": await _rows(session, list(items)),
        "total": total,
        "total_value": format(Decimal(value).quantize(Decimal(1)), "f"),
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/export")
async def export(
    principal: Exporter, session: Session, q: str | None = None, status: str | None = None
) -> StreamingResponse:
    stmt = _query(principal, "export", q, status).order_by(Contract.number)
    rows = await _rows(session, list((await session.execute(stmt)).scalars()))
    columns = [
        Column("Nomor", "number", width=14),
        Column("Judul", "title", width=36),
        Column("Klien", "company_name", width=30),
        Column("No. PO/SPK", "po_number", width=20),
        Column("Nilai", "value", "idr"),
        Column("Terpakai", "used_value", "idr"),
        Column("Pemakaian (%)", "usage_pct", width=10),
        Column("Mulai", "start", "date"),
        Column("Selesai", "end", "date"),
        Column("Termin (hari)", "payment_term_days", "number", width=10),
        Column("Proyek", "project_number", width=14),
    ]
    return xlsx_response(
        f"kontrak-{today_jakarta():%Y%m%d}.xlsx",
        "Kontrak",
        columns,
        (
            {
                **r,
                "start": date.fromisoformat(r["start_date"]) if r["start_date"] else None,
                "end": date.fromisoformat(r["end_date"]) if r["end_date"] else None,
            }
            for r in rows
        ),
    )


async def _get(session: AsyncSession, principal: Principal, cid: uuid.UUID) -> Contract:
    c = await session.get(Contract, cid, with_for_update=True)
    if c is None or not may(principal, "view", c.owner_id):
        raise NotFoundError("NOT_FOUND", "Kontrak tidak ditemukan atau Anda tidak berizin.")
    return c


async def _detail(session: AsyncSession, principal: Principal, c: Contract) -> dict[str, Any]:
    opp = await session.get(Opportunity, c.opportunity_id)
    q = await session.get(Quotation, c.quotation_id) if c.quotation_id else None
    rates = await service.rates_of(session, c.id)
    return {
        **(await _rows(session, [c]))[0],
        "opportunity_id": str(c.opportunity_id),
        "opportunity_number": opp.number if opp else None,
        "quotation_id": str(q.id) if q else None,
        "quotation_label": f"{q.number} Rev.{q.revision}" if q else None,
        "can_edit": may(principal, "edit", c.owner_id),
        "rates": [
            {
                "id": str(r.id),
                "seq": r.seq,
                "kind": r.kind,
                "price_item_code": r.price_item_code,
                "cost_element_code": r.cost_element_code,
                "description": r.description,
                "unit": r.unit,
                "rate": format(r.rate, "f"),
                "standby_rate": format(r.standby_rate, "f") if r.standby_rate is not None else None,
                "breakdown_rate": format(r.breakdown_rate, "f")
                if r.breakdown_rate is not None
                else None,
                "unit_cost": format(r.unit_cost, "f") if r.unit_cost is not None else None,
                "markup_pct": format(r.markup_pct, "f") if r.markup_pct is not None else None,
                "quoted_qty": format(r.quoted_qty.normalize(), "f")
                if r.quoted_qty is not None
                else None,
            }
            for r in rates
        ],
    }


@router.get("/{cid}")
async def get_contract(cid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _detail(session, principal, await _get(session, principal, cid))


class HeaderIn(BaseModel):
    po_number: str | None = Field(default=None, max_length=60)
    start_date: date | None = None
    end_date: date | None = None
    payment_term_days: int = Field(ge=0, le=365)
    status: Literal["active", "completed", "terminated"] = "active"

    @model_validator(mode="after")
    def _period(self) -> "HeaderIn":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Tanggal selesai sebelum tanggal mulai.")
        return self


@router.patch("/{cid}")
async def update_header(
    cid: uuid.UUID, body: HeaderIn, actor: Editor, session: Session
) -> dict[str, Any]:
    c = await _get(session, actor, cid)
    if not may(actor, "edit", c.owner_id):
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin mengubah kontrak ini.")
    before = {
        "po_number": c.po_number,
        "start_date": c.start_date,
        "end_date": c.end_date,
        "payment_term_days": c.payment_term_days,
        "status": c.status,
    }
    c.po_number = (body.po_number or "").strip() or None
    c.start_date, c.end_date = body.start_date, body.end_date
    c.payment_term_days, c.status = body.payment_term_days, body.status
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="contract",
        entity_id=c.id,
        actor_id=actor.id,
        before=before,
        after={
            "po_number": c.po_number,
            "start_date": c.start_date,
            "end_date": c.end_date,
            "payment_term_days": c.payment_term_days,
            "status": c.status,
        },
    )
    await session.commit()
    return await _detail(session, actor, c)


class RateIn(BaseModel):
    kind: Literal["service", "equipment", "personnel", "consumable", "mobilisation"]
    price_item_code: str | None = Field(default=None, max_length=30)
    cost_element_code: str | None = Field(default=None, max_length=20)
    description: str = Field(min_length=2, max_length=300)
    unit: str = Field(min_length=1, max_length=20)
    rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    standby_rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    breakdown_rate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    markup_pct: Decimal | None = Field(default=None, ge=0, le=1000, decimal_places=2)
    quoted_qty: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)


class RatesIn(BaseModel):
    rates: list[RateIn] = Field(max_length=300)


@router.put("/{cid}/rates")
async def put_rates(
    cid: uuid.UUID, body: RatesIn, actor: Editor, session: Session
) -> dict[str, Any]:
    c = await _get(session, actor, cid)
    if not may(actor, "edit", c.owner_id):
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin mengubah kontrak ini.")
    if c.status != "active":
        raise AppError("CONTRACT_CLOSED", "Kontrak sudah tidak aktif.", status_code=409)
    await service.replace_rates(session, actor, c, [r.model_dump() for r in body.rates])
    await session.commit()
    return await _detail(session, actor, c)
