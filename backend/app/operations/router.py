"""Operations API (05a): DOR form options, offline-safe save, preview, submit, list."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import Principal, require
from app.contract.models import Contract, ContractRate
from app.core import access
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.inventory import stock_service as stock
from app.inventory.models import StockBalance
from app.master.models import Asset, Employee, Item, PriceItem, Warehouse
from app.operations import dor_service as svc
from app.operations.models import Dor, DorConsumable, DorCrew, DorEquipment
from app.project.models import Project, ProjectWbs
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta
from app.setup import service as settings_store

router = APIRouter(prefix="/operations", tags=["operations"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("operations", "view"))]
Creator = Annotated[Principal, Depends(require("operations", "create"))]
Submitter = Annotated[Principal, Depends(require("operations", "submit"))]
Exporter = Annotated[Principal, Depends(require("operations", "export"))]
Approver = Annotated[Principal, Depends(require("operations", "approve"))]


def _m(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


def _q(v: Decimal) -> str:
    return format(v.normalize(), "f") if v else "0"


def _may(principal: Principal, action: str, project_id: uuid.UUID, owner: uuid.UUID | None) -> bool:
    scope = principal.scope_for("operations", action)
    if scope is None:
        return False
    if scope == Scope.ALL or project_id in principal.project_ids:
        return True
    return owner == principal.id


async def _project(
    session: AsyncSession, principal: Principal, pid: uuid.UUID, action: str
) -> Project:
    p = await session.get(Project, pid)
    if p is None or not _may(principal, action, p.id, None):
        raise NotFoundError(
            "NOT_FOUND", "Proyek tidak ditemukan atau Anda belum terdaftar di tim proyek ini."
        )
    return p


async def _dor(
    session: AsyncSession, principal: Principal, did: uuid.UUID, action: str = "view"
) -> Dor:
    dor = await session.get(Dor, did)
    if dor is None or not _may(principal, action, dor.project_id, dor.created_by):
        raise NotFoundError("NOT_FOUND", "DOR tidak ditemukan atau Anda tidak berizin.")
    return dor


async def _dor_access(
    session: AsyncSession, principal: Principal, eid: str, mode: access.Mode
) -> bool:
    try:
        await _dor(session, principal, uuid.UUID(eid), "view" if mode == "read" else "edit")
    except (ValueError, NotFoundError):
        return False
    return True


access.register(svc.DOC, _dor_access)


# ---------------------------------------------------------------- input models


class EquipmentBody(BaseModel):
    asset_code: str = Field(min_length=1, max_length=30)
    rate_id: uuid.UUID | None = None
    operating: Decimal = Field(default=Decimal(0), ge=0, le=24, decimal_places=2)
    standby: Decimal = Field(default=Decimal(0), ge=0, le=24, decimal_places=2)
    breakdown: Decimal = Field(default=Decimal(0), ge=0, le=24, decimal_places=2)
    rig: Decimal = Field(default=Decimal(0), ge=0, le=24, decimal_places=2)
    remark: str | None = Field(default=None, max_length=300)


class CrewBody(BaseModel):
    employee_code: str = Field(min_length=1, max_length=20)
    rate_id: uuid.UUID | None = None
    hours: Decimal = Field(default=Decimal(12), ge=0, le=24, decimal_places=2)
    overtime_hours: Decimal = Field(default=Decimal(0), ge=0, le=24, decimal_places=2)


class ConsumableBody(BaseModel):
    item_code: str = Field(min_length=1, max_length=30)
    rate_id: uuid.UUID | None = None
    qty: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class DorBody(BaseModel):
    report_date: date
    wbs_code: str = Field(default="EXEC", max_length=20)
    site_warehouse: str | None = Field(default=None, max_length=20)
    activities: str | None = Field(default=None, max_length=5000)
    npt_hours: Decimal = Field(default=Decimal(0), ge=0, le=24, decimal_places=2)
    npt_reason: str | None = Field(default=None, max_length=500)
    technical: dict[str, Any] = Field(default_factory=dict)
    hse: dict[str, Any] = Field(default_factory=dict)
    equipment: list[EquipmentBody] = Field(default_factory=list, max_length=60)
    crew: list[CrewBody] = Field(default_factory=list, max_length=200)
    consumables: list[ConsumableBody] = Field(default_factory=list, max_length=200)

    def data(self) -> svc.DorIn:
        return svc.DorIn(
            report_date=self.report_date,
            wbs_code=self.wbs_code.upper(),
            site_warehouse=self.site_warehouse or None,
            activities=self.activities,
            npt_hours=self.npt_hours,
            npt_reason=self.npt_reason,
            technical=self.technical,
            hse=self.hse,
            equipment=[
                svc.EquipmentIn(
                    x.asset_code, x.rate_id, x.operating, x.standby, x.breakdown, x.rig, x.remark
                )
                for x in self.equipment
            ],
            crew=[
                svc.CrewIn(c.employee_code, c.rate_id, c.hours, c.overtime_hours) for c in self.crew
            ],
            consumables=[svc.ConsumableIn(k.item_code, k.rate_id, k.qty) for k in self.consumables],
        )


class SyncBody(BaseModel):
    project_id: uuid.UUID
    client_id: uuid.UUID
    base_version: int | None = None
    dor: DorBody


class PreviewBody(BaseModel):
    project_id: uuid.UUID
    dor: DorBody
    dor_id: uuid.UUID | None = None


# ---------------------------------------------------------------- options


@router.get("/dor-templates")
async def get_templates(_: Viewer, session: Session) -> dict[str, Any]:
    return await svc.templates(session)


class TemplateField(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    unit: str = Field(default="", max_length=20)
    type: str = Field(default="number", pattern="^(number|text)$")


class Template(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    fields: list[TemplateField] = Field(min_length=1, max_length=30)


@router.put("/dor-templates")
async def put_templates(
    body: dict[str, Template], actor: Approver, session: Session
) -> dict[str, Any]:
    if actor.scope_for("operations", "approve") != Scope.ALL:
        raise ForbiddenError("PERMISSION_DENIED", "Template DOR diatur oleh Head of Operation.")
    value = {k: v.model_dump() for k, v in body.items()}
    await settings_store.put(session, svc.TEMPLATES_KEY, value, actor.id)
    await session.commit()
    return value


@router.get("/projects")
async def dor_projects(principal: Creator, session: Session) -> list[dict[str, Any]]:
    """Locked projects the user can report on."""
    stmt = select(Project).where(Project.status == "locked").order_by(Project.number)
    if principal.scope_for("operations", "create") != Scope.ALL:
        stmt = stmt.where(Project.id.in_(principal.project_ids or {uuid.uuid4()}))
    return [
        {"id": str(p.id), "number": p.number, "name": p.name, "service_type": p.service_type}
        for p in (await session.execute(stmt)).scalars()
    ]


@router.get("/dors/form-options")
async def form_options(
    project_id: uuid.UUID, principal: Creator, session: Session, on: date | None = None
) -> dict[str, Any]:
    """Everything the DOR form needs, cached by the PWA for offline use."""
    p = await _project(session, principal, project_id, "create")
    on = on or today_jakarta()
    tpl = await svc.templates(session)
    wbs = (
        await session.execute(
            select(ProjectWbs).where(ProjectWbs.project_id == p.id).order_by(ProjectWbs.seq)
        )
    ).scalars()
    sites = list(
        (
            await session.execute(
                select(Warehouse)
                .where(Warehouse.kind == "site", Warehouse.is_active)
                .order_by(Warehouse.code)
            )
        ).scalars()
    )
    contract = await session.get(Contract, p.contract_id) if p.contract_id else None
    rates = []
    if contract:
        rows = await session.execute(
            select(ContractRate, PriceItem.unit_cost)
            .outerjoin(PriceItem, PriceItem.code == ContractRate.price_item_code)
            .where(ContractRate.contract_id == contract.id)
            .order_by(ContractRate.seq)
        )
        for r, cost in rows.tuples():
            if r.kind in ("equipment", "personnel", "consumable"):
                rates.append(
                    {
                        "id": str(r.id),
                        "kind": r.kind,
                        "description": r.description,
                        "unit": r.unit,
                        "rate": _m(r.rate),
                        "standby_rate": _m(r.standby_rate),
                        "breakdown_rate": _m(r.breakdown_rate),
                        "unit_cost": _m(r.unit_cost),
                        "markup_pct": _m(r.markup_pct),
                        "internal_cost": _m(cost),
                    }
                )
    assets = []
    for a in (
        await session.execute(select(Asset).where(Asset.is_active).order_by(Asset.code))
    ).scalars():
        block, warn = svc.cert_status(a.certificates, on)
        assets.append(
            {
                "code": a.code,
                "name": a.name,
                "internal_day_rate": _m(a.internal_day_rate),
                "blocked": block,
                "warning": warn,
            }
        )
    crew = []
    for e in (
        await session.execute(
            select(Employee)
            .where(Employee.is_active, Employee.is_field)
            .order_by(Employee.full_name)
        )
    ).scalars():
        block, warn = svc.cert_status(e.certificates, on)
        crew.append(
            {
                "code": e.code,
                "full_name": e.full_name,
                "position": e.position,
                "blocked": block,
                "warning": warn,
            }
        )
    site_codes = [w.code for w in sites]
    stock_rows = (
        await session.execute(
            select(StockBalance).where(
                StockBalance.warehouse_code.in_(site_codes or ["-"]), StockBalance.qty > 0
            )
        )
    ).scalars()
    items = {
        i.code: i for i in (await session.execute(select(Item).where(Item.is_active))).scalars()
    }
    return {
        "project": {
            "id": str(p.id),
            "number": p.number,
            "name": p.name,
            "service_line": p.service_line,
            "service_type": p.service_type,
            "contract_number": contract.number if contract else None,
        },
        "template": tpl.get(p.service_type or "") if p.service_type else None,
        "wbs": [{"code": w.code, "name": w.name} for w in wbs],
        "sites": [{"code": w.code, "name": w.name, "project_code": w.project_code} for w in sites],
        "default_site": next((w.code for w in sites if w.project_code == p.number), None),
        "rates": rates,
        "assets": assets,
        "crew": crew,
        "stock": [
            {
                "warehouse_code": b.warehouse_code,
                "item_code": b.item_code,
                "name": items[b.item_code].name if b.item_code in items else b.item_code,
                "uom": items[b.item_code].uom if b.item_code in items else "",
                "qty": _q(b.qty),
                "avg_cost": _m(stock.avg_cost(b)),
            }
            for b in stock_rows
        ],
    }


# ---------------------------------------------------------------- detail and list


async def _detail(session: AsyncSession, principal: Principal, dor: Dor) -> dict[str, Any]:
    p = await session.get(Project, dor.project_id)
    wbs = await session.get(ProjectWbs, dor.wbs_id)
    assert p is not None and wbs is not None
    creator = await session.get(User, dor.created_by) if dor.created_by else None

    async def rows(model: Any) -> list[Any]:
        return list((await session.execute(select(model).where(model.dor_id == dor.id))).scalars())

    editable = dor.status in svc.EDITABLE and _may(
        principal, "edit", dor.project_id, dor.created_by
    )
    return {
        "id": str(dor.id),
        "client_id": str(dor.client_id),
        "version": dor.version,
        "number": dor.number,
        "status": dor.status,
        "status_label": svc.STATUS_LABELS.get(dor.status, dor.status),
        "project_id": str(p.id),
        "project_number": p.number,
        "project_name": p.name,
        "report_date": dor.report_date.isoformat(),
        "wbs_code": wbs.code,
        "site_warehouse": dor.site_warehouse,
        "activities": dor.activities,
        "npt_hours": _q(dor.npt_hours),
        "npt_reason": dor.npt_reason,
        "technical": dor.technical,
        "hse": dor.hse,
        "revenue": _m(dor.revenue),
        "internal_cost": _m(dor.internal_cost),
        "late": dor.late,
        "submitted_at": dor.submitted_at.isoformat() if dor.submitted_at else None,
        "approved_at": dor.approved_at.isoformat() if dor.approved_at else None,
        "deadline": svc.deadline(dor.report_date).isoformat(),
        "return_reason": dor.return_reason,
        "request_id": str(dor.request_id) if dor.request_id else None,
        "created_by_name": creator.full_name if creator else None,
        "can_edit": editable,
        "can_submit": editable and principal.can("operations", "submit"),
        "equipment": [
            {
                "asset_code": x.asset_code,
                "rate_id": str(x.rate_id) if x.rate_id else None,
                "operating": _q(x.operating),
                "standby": _q(x.standby),
                "breakdown": _q(x.breakdown),
                "rig": _q(x.rig),
                "remark": x.remark,
                "revenue": _m(x.revenue),
                "internal_cost": _m(x.internal_cost),
            }
            for x in await rows(DorEquipment)
        ],
        "crew": [
            {
                "employee_code": c.employee_code,
                "rate_id": str(c.rate_id) if c.rate_id else None,
                "hours": _q(c.hours),
                "overtime_hours": _q(c.overtime_hours),
                "revenue": _m(c.revenue),
                "internal_cost": _m(c.internal_cost),
            }
            for c in await rows(DorCrew)
        ],
        "consumables": [
            {
                "item_code": k.item_code,
                "rate_id": str(k.rate_id) if k.rate_id else None,
                "qty": _q(k.qty),
                "revenue": _m(k.revenue),
                "internal_cost": _m(k.internal_cost),
            }
            for k in await rows(DorConsumable)
        ],
    }


def _list_query(
    principal: Principal,
    status: str | None,
    project_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> Select[Any]:
    stmt = select(Dor, Project.number).join(Project, Project.id == Dor.project_id)
    scope = principal.scope_for("operations", "view")
    if scope != Scope.ALL:
        stmt = stmt.where(
            or_(
                Dor.created_by == principal.id,
                Dor.project_id.in_(principal.project_ids or {uuid.uuid4()}),
            )
        )
    if status:
        stmt = stmt.where(Dor.status == status)
    if project_id:
        stmt = stmt.where(Dor.project_id == project_id)
    if date_from:
        stmt = stmt.where(Dor.report_date >= date_from)
    if date_to:
        stmt = stmt.where(Dor.report_date <= date_to)
    return stmt


def _row(d: Dor, project_number: str) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "number": d.number,
        "status": d.status,
        "status_label": svc.STATUS_LABELS.get(d.status, d.status),
        "project_number": project_number,
        "report_date": d.report_date.isoformat(),
        "revenue": _m(d.revenue),
        "internal_cost": _m(d.internal_cost),
        "late": d.late,
    }


@router.get("/dors")
async def list_dors(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    status: str | None = None,
    project_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    base = _list_query(principal, None, project_id, date_from, date_to).subquery()
    counts = dict.fromkeys(svc.STATUS_LABELS, 0)
    counts.update(
        dict(
            (await session.execute(select(base.c.status, func.count()).group_by(base.c.status)))
            .tuples()
            .all()
        )
    )
    stmt = _list_query(principal, status, project_id, date_from, date_to)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(Dor.report_date.desc(), Dor.number.desc())
            .offset(paging.offset)
            .limit(paging.page_size)
        )
    ).tuples()
    return {
        "items": [_row(d, n) for d, n in rows],
        "total": total,
        "counts": counts,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/dors/export")
async def export_dors(
    principal: Exporter, session: Session, status: str | None = None
) -> StreamingResponse:
    rows = [
        _row(d, n)
        for d, n in (
            await session.execute(
                _list_query(principal, status, None, None, None).order_by(
                    Dor.report_date, Dor.number
                )
            )
        ).tuples()
    ]
    columns = [
        Column("Nomor", "number", width=14),
        Column("Proyek", "project_number", width=14),
        Column("Tanggal", "day", "date"),
        Column("Status", "status_label", width=20),
        Column("Pendapatan", "revenue", "idr"),
        Column("Biaya internal", "internal_cost", "idr"),
        Column("Terlambat", "late_label", width=10),
    ]
    return xlsx_response(
        f"dor-{today_jakarta():%Y%m%d}.xlsx",
        "DOR",
        columns,
        (
            {
                **r,
                "day": date.fromisoformat(r["report_date"]),
                "late_label": "Ya" if r["late"] else "",
            }
            for r in rows
        ),
    )


@router.get("/dors/by-client/{client_id}")
async def get_by_client(
    client_id: uuid.UUID, principal: Viewer, session: Session
) -> dict[str, Any]:
    dor = (
        await session.execute(select(Dor).where(Dor.client_id == client_id))
    ).scalar_one_or_none()
    if dor is None or not _may(principal, "view", dor.project_id, dor.created_by):
        raise NotFoundError("NOT_FOUND", "DOR tidak ditemukan.")
    return await _detail(session, principal, dor)


@router.get("/dors/{did}")
async def get_dor(did: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _detail(session, principal, await _dor(session, principal, did))


@router.post("/dors/sync")
async def sync_dor(
    body: SyncBody, actor: Creator, session: Session, response: Response
) -> dict[str, Any]:
    """Create or update a draft (from the form or the offline queue)."""
    p = await _project(session, actor, body.project_id, "create")
    existing = (
        await session.execute(select(Dor.id).where(Dor.client_id == body.client_id))
    ).scalar_one_or_none()
    dor = await svc.save(session, actor, p, body.client_id, body.base_version, body.dor.data())
    await session.commit()
    response.status_code = 200 if existing else 201
    return await _detail(session, actor, dor)


@router.post("/dors/preview")
async def preview(body: PreviewBody, actor: Creator, session: Session) -> dict[str, Any]:
    """Live pricing and validation without saving."""
    p = await _project(session, actor, body.project_id, "create")
    data = body.dor.data()
    priced = await svc.price(session, p, data, data.site_warehouse)
    errors, warnings = await svc.validate(session, p, data, exclude_dor=body.dor_id)
    return {
        "revenue": _m(priced.revenue),
        "internal_cost": _m(priced.cost),
        "cost_by_element": {k: _m(v) for k, v in priced.cost_by_element().items()},
        "equipment": [[_m(a), _m(b)] for a, b in priced.equipment],
        "crew": [[_m(a), _m(b)] for a, b in priced.crew],
        "consumables": [[_m(a), _m(b)] for a, b in priced.consumables],
        "errors": errors,
        "warnings": warnings,
    }


@router.post("/dors/{did}/submit")
async def submit_dor(did: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    dor = await _dor(session, actor, did, "submit")
    await session.refresh(dor, with_for_update=True)
    await svc.submit(session, actor, dor)
    await session.commit()
    return await _detail(session, actor, dor)
