"""Maintenance API (05b): equipment register, allocation, PM library and import, scheduler,
work orders, downtime, KPIs."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import CurrentUser, Principal, require
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.maintenance import importer
from app.maintenance import service as svc
from app.maintenance.models import (
    FREQUENCIES,
    AssetAllocation,
    Downtime,
    PmSchedule,
    PmTask,
    WorkOrder,
    WorkOrderPart,
)
from app.master.models import Asset, EquipmentType
from app.operations import dor_service
from app.project.models import Project
from app.services.numbering import today_jakarta

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("maintenance", "view"))]
Creator = Annotated[Principal, Depends(require("maintenance", "create"))]
Editor = Annotated[Principal, Depends(require("maintenance", "edit"))]
Paging = Annotated[PageParams, Depends(page_params)]


def _m(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


def _q(v: Decimal | None) -> str | None:
    return (format(v.normalize(), "f") if v else "0") if v is not None else None


def _may_allocate(p: Principal) -> None:
    if not (p.can("maintenance", "edit") or p.can("maintenance", "approve")):
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin mengalokasikan aset.")


async def _asset(session: AsyncSession, code: str) -> Asset:
    a = (await session.execute(select(Asset).where(Asset.code == code))).scalar_one_or_none()
    if a is None:
        raise NotFoundError("NOT_FOUND", f"Aset {code} tidak ditemukan.")
    return a


async def _wo(session: AsyncSession, wid: uuid.UUID, lock: bool = False) -> WorkOrder:
    wo = await session.get(WorkOrder, wid, with_for_update=lock)
    if wo is None:
        raise NotFoundError("NOT_FOUND", "Work order tidak ditemukan.")
    return wo


async def _wo_access(
    session: AsyncSession, principal: Principal, eid: str, mode: access.Mode
) -> bool:
    return principal.can("maintenance", "view" if mode == "read" else "edit")


access.register(svc.DOC, _wo_access)


# ---------------------------------------------------------------- register


@router.get("/assets")
async def register(_: Viewer, session: Session, q: str | None = None) -> list[dict[str, Any]]:
    stmt = select(Asset, EquipmentType.name, EquipmentType.category).outerjoin(
        EquipmentType, EquipmentType.code == Asset.equipment_type_code
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Asset.code.ilike(like) | Asset.name.ilike(like))
    rows = (await session.execute(stmt.order_by(Asset.code))).tuples().all()
    allocs = {
        a.asset_code: a
        for a in (
            await session.execute(
                select(AssetAllocation).where(AssetAllocation.released_at.is_(None))
            )
        ).scalars()
    }
    projects = dict((await session.execute(select(Project.id, Project.number))).tuples().all())
    open_wo = dict(
        (
            await session.execute(
                select(WorkOrder.asset_code, func.count())
                .where(WorkOrder.status.in_(svc.OPEN))
                .group_by(WorkOrder.asset_code)
            )
        )
        .tuples()
        .all()
    )
    today = today_jakarta()
    out = []
    for a, tname, cat in rows:
        block, warn = dor_service.cert_status(a.certificates, today)
        al = allocs.get(a.code)
        out.append(
            {
                "code": a.code,
                "name": a.name,
                "equipment_type_code": a.equipment_type_code,
                "equipment_type": tname,
                "category": cat,
                "criticality": a.criticality,
                "location": a.location,
                "is_active": a.is_active,
                "cert_blocked": block,
                "cert_warning": warn,
                "allocated_to": projects.get(al.project_id) if al else None,
                "open_work_orders": int(open_wo.get(a.code, 0)),
                "operating_hours": _q(await svc.meter(session, a.code)),
            }
        )
    return out


@router.get("/assets/{code}")
async def asset_detail(code: str, _: Viewer, session: Session) -> dict[str, Any]:
    a = await _asset(session, code)
    today = today_jakarta()
    block, warn = dor_service.cert_status(a.certificates, today)
    projects = dict((await session.execute(select(Project.id, Project.number))).tuples().all())
    allocs = (
        await session.execute(
            select(AssetAllocation)
            .where(AssetAllocation.asset_code == code)
            .order_by(AssetAllocation.start_date.desc())
        )
    ).scalars()
    sched = (
        await session.execute(
            select(PmSchedule, PmTask)
            .join(PmTask, PmTask.code == PmSchedule.task_code)
            .where(PmSchedule.asset_code == code)
            .order_by(PmTask.code)
        )
    ).tuples()
    wos = (
        await session.execute(
            select(WorkOrder)
            .where(WorkOrder.asset_code == code)
            .order_by(WorkOrder.created_at.desc())
            .limit(50)
        )
    ).scalars()
    downs = (
        await session.execute(
            select(Downtime)
            .where(Downtime.asset_code == code)
            .order_by(Downtime.start_date.desc())
            .limit(50)
        )
    ).scalars()
    return {
        "code": a.code,
        "name": a.name,
        "equipment_type_code": a.equipment_type_code,
        "criticality": a.criticality,
        "serial_no": a.serial_no,
        "location": a.location,
        "internal_day_rate": _m(a.internal_day_rate),
        "certificates": [{**c, "status": _cert_one(c, today)} for c in (a.certificates or [])],
        "cert_blocked": block,
        "cert_warning": warn,
        "operating_hours": _q(await svc.meter(session, code)),
        "allocations": [
            {
                "project_number": projects.get(x.project_id),
                "start_date": x.start_date.isoformat(),
                "released_at": x.released_at.isoformat() if x.released_at else None,
            }
            for x in allocs
        ],
        "schedules": [
            {
                "task_code": t.code,
                "title": t.title,
                "frequency": t.frequency,
                "interval_hours": t.interval_hours,
                "last_done_date": s.last_done_date.isoformat(),
                "last_done_hours": _q(s.last_done_hours),
                "next_due_date": s.next_due_date.isoformat() if s.next_due_date else None,
                "next_due_hours": _q(s.next_due_hours),
            }
            for s, t in sched
        ],
        "work_orders": [_wo_row(w) for w in wos],
        "downtime": [
            {
                "start_date": d.start_date.isoformat(),
                "hours": _q(d.hours),
                "reason": d.reason,
            }
            for d in downs
        ],
    }


def _cert_one(c: dict[str, Any], today: date) -> str:
    if not c.get("expiry_date"):
        return "no_expiry"
    exp = date.fromisoformat(str(c["expiry_date"]))
    if exp < today:
        return "expired"
    return "warning" if (exp - today).days <= 90 else "valid"


class AllocateBody(BaseModel):
    project_id: uuid.UUID
    start_date: date
    note: str | None = Field(default=None, max_length=300)


@router.post("/assets/{code}/allocate", status_code=201)
async def allocate(
    code: str, body: AllocateBody, actor: CurrentUser, session: Session
) -> dict[str, Any]:
    _may_allocate(actor)
    a = await _asset(session, code)
    p = await session.get(Project, body.project_id)
    if p is None:
        raise NotFoundError("NOT_FOUND", "Proyek tidak ditemukan.")
    _, wo = await svc.allocate(session, actor, a, p, body.start_date, body.note)
    await session.commit()
    return {"asset_code": code, "project_number": p.number, "inspection": _wo_row(wo)}


class ReleaseBody(BaseModel):
    release_date: date


@router.post("/assets/{code}/release")
async def release(
    code: str, body: ReleaseBody, actor: CurrentUser, session: Session
) -> dict[str, Any]:
    _may_allocate(actor)
    wo = await svc.release(session, actor, await _asset(session, code), body.release_date)
    await session.commit()
    return {"asset_code": code, "inspection": _wo_row(wo)}


# ---------------------------------------------------------------- PM library


def _task(t: PmTask) -> dict[str, Any]:
    return {
        "code": t.code,
        "equipment_type_code": t.equipment_type_code,
        "title": t.title,
        "frequency": t.frequency,
        "interval_hours": t.interval_hours,
        "form_code": t.form_code,
        "checklist": t.checklist,
        "est_hours": _q(t.est_hours),
        "is_active": t.is_active,
    }


@router.get("/pm-tasks")
async def pm_tasks(
    _: Viewer, session: Session, equipment_type: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(PmTask).order_by(PmTask.equipment_type_code, PmTask.code)
    if equipment_type:
        stmt = stmt.where(PmTask.equipment_type_code == equipment_type)
    return [_task(t) for t in (await session.execute(stmt)).scalars()]


class TaskBody(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    equipment_type_code: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=3, max_length=200)
    frequency: str
    interval_hours: int | None = Field(default=None, ge=1, le=100_000)
    form_code: str | None = Field(default=None, max_length=30)
    checklist: list[str] = Field(default_factory=list, max_length=60)
    est_hours: Decimal | None = Field(default=None, ge=0, le=1000)
    is_active: bool = True


@router.put("/pm-tasks/{code}")
async def put_task(code: str, body: TaskBody, actor: Editor, session: Session) -> dict[str, Any]:
    if body.frequency not in FREQUENCIES:
        raise AppError("FREQUENCY_INVALID", "Frekuensi tidak dikenal.", status_code=422)
    if body.frequency == "hours" and not body.interval_hours:
        raise AppError("INTERVAL_REQUIRED", "Isi interval jam operasi.", status_code=422)
    if not (
        await session.execute(
            select(EquipmentType.code).where(EquipmentType.code == body.equipment_type_code)
        )
    ).first():
        raise AppError("TYPE_INVALID", "Jenis peralatan tidak dikenal.", status_code=422)
    t = (await session.execute(select(PmTask).where(PmTask.code == code))).scalar_one_or_none()
    if t is None:
        t = PmTask(code=code, created_by=actor.id)
        session.add(t)
    t.equipment_type_code, t.title, t.frequency = (
        body.equipment_type_code,
        body.title,
        body.frequency,
    )
    t.interval_hours = body.interval_hours if body.frequency == "hours" else None
    t.form_code, t.est_hours, t.is_active = body.form_code, body.est_hours, body.is_active
    t.checklist = [x.strip() for x in body.checklist if x.strip()]
    await session.commit()
    return _task(t)


@router.post("/pm-import")
async def pm_import(
    actor: Editor, session: Session, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", "Berkas maksimal 10 MB.", status_code=413)
    res = await importer.run(session, actor, data)
    if res.errors:
        await session.rollback()
        raise AppError(
            "IMPORT_INVALID",
            f"{len(res.errors)} baris bermasalah; tidak ada yang disimpan.",
            status_code=422,
            details={"errors": res.errors[:200]},
        )
    await session.commit()
    return res.__dict__


@router.post("/pm-run")
async def pm_run(_: Editor, session: Session) -> dict[str, int]:
    """Run the PM scheduler now (it also runs as a background job)."""
    n = await svc.run_pm(session)
    await session.commit()
    return {"created": n}


# ---------------------------------------------------------------- work orders


def _wo_row(w: WorkOrder) -> dict[str, Any]:
    return {
        "id": str(w.id),
        "number": w.number,
        "asset_code": w.asset_code,
        "kind": w.kind,
        "status": w.status,
        "title": w.title,
        "task_code": w.task_code,
        "trigger": w.trigger,
        "due_date": w.due_date.isoformat() if w.due_date else None,
        "due_hours": _q(w.due_hours),
        "completed_date": w.completed_date.isoformat() if w.completed_date else None,
        "overdue": w.status in svc.OPEN and w.due_date is not None and w.due_date < today_jakarta(),
    }


@router.get("/work-orders")
async def list_wos(
    _: Viewer,
    session: Session,
    paging: Paging,
    status: str | None = None,
    kind: str | None = None,
    asset: str | None = None,
) -> dict[str, Any]:
    stmt = select(WorkOrder)
    if status == "open":
        stmt = stmt.where(WorkOrder.status.in_(svc.OPEN))
    elif status:
        stmt = stmt.where(WorkOrder.status == status)
    if kind:
        stmt = stmt.where(WorkOrder.kind == kind)
    if asset:
        stmt = stmt.where(WorkOrder.asset_code == asset)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(WorkOrder.created_at.desc()).offset(paging.offset).limit(paging.page_size)
        )
    ).scalars()
    counts = dict(
        (await session.execute(select(WorkOrder.status, func.count()).group_by(WorkOrder.status)))
        .tuples()
        .all()
    )
    return {"items": [_wo_row(w) for w in rows], "total": total, "counts": counts}


async def _wo_detail(session: AsyncSession, principal: Principal, w: WorkOrder) -> dict[str, Any]:
    parts = (
        await session.execute(
            select(WorkOrderPart)
            .where(WorkOrderPart.wo_id == w.id)
            .order_by(WorkOrderPart.issued_at)
        )
    ).scalars()
    project = await session.get(Project, w.project_id) if w.project_id else None
    asset = await _asset(session, w.asset_code)
    return {
        **_wo_row(w),
        "asset_name": asset.name,
        "form_code": w.form_code,
        "project_number": project.number if project else None,
        "checklist": w.checklist,
        "labour_hours": _q(w.labour_hours),
        "result": w.result,
        "signature_name": w.signature_name,
        "parts_value": _m(w.parts_value),
        "parts": [
            {
                "item_code": p.item_code,
                "warehouse_code": p.warehouse_code,
                "qty": _q(p.qty),
                "value": _m(p.value),
            }
            for p in parts
        ],
        "can_edit": w.status in svc.OPEN and principal.can("maintenance", "edit"),
    }


class CorrectiveBody(BaseModel):
    asset_code: str
    title: str = Field(min_length=5, max_length=200)
    checklist: list[str] = Field(default_factory=list, max_length=60)


@router.post("/work-orders", status_code=201)
async def create_wo(body: CorrectiveBody, actor: Creator, session: Session) -> dict[str, Any]:
    wo = await svc.create_corrective(
        session, actor, await _asset(session, body.asset_code), body.title, body.checklist
    )
    await session.commit()
    return await _wo_detail(session, actor, wo)


@router.get("/work-orders/{wid}")
async def get_wo(wid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _wo_detail(session, principal, await _wo(session, wid))


class WoBody(BaseModel):
    checklist: list[dict[str, Any]]
    labour_hours: Decimal = Field(default=Decimal(0), ge=0, le=10_000)
    result: str | None = Field(default=None, max_length=5000)


@router.put("/work-orders/{wid}")
async def update_wo(
    wid: uuid.UUID, body: WoBody, actor: Editor, session: Session
) -> dict[str, Any]:
    wo = await _wo(session, wid, lock=True)
    await svc.update(
        session, actor, wo, svc.WoUpdate(body.checklist, body.labour_hours, body.result)
    )
    await session.commit()
    return await _wo_detail(session, actor, wo)


class PartBody(BaseModel):
    item_code: str
    warehouse_code: str
    qty: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


@router.post("/work-orders/{wid}/parts")
async def add_part(
    wid: uuid.UUID, body: PartBody, actor: Editor, session: Session
) -> dict[str, Any]:
    wo = await _wo(session, wid, lock=True)
    await svc.issue_part(session, actor, wo, body.item_code, body.warehouse_code, body.qty)
    await session.commit()
    return await _wo_detail(session, actor, wo)


class CompleteBody(BaseModel):
    completed_date: date | None = None


@router.post("/work-orders/{wid}/complete")
async def complete_wo(
    wid: uuid.UUID, body: CompleteBody, actor: Editor, session: Session
) -> dict[str, Any]:
    wo = await _wo(session, wid, lock=True)
    await svc.complete(session, actor, wo, body.completed_date or today_jakarta())
    await session.commit()
    return await _wo_detail(session, actor, wo)


class CancelBody(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


@router.post("/work-orders/{wid}/cancel")
async def cancel_wo(
    wid: uuid.UUID, body: CancelBody, actor: Editor, session: Session
) -> dict[str, Any]:
    wo = await _wo(session, wid, lock=True)
    await svc.cancel(session, actor, wo, body.reason)
    await session.commit()
    return await _wo_detail(session, actor, wo)


# ---------------------------------------------------------------- downtime & KPIs


class DowntimeBody(BaseModel):
    asset_code: str
    start_date: date
    end_date: date | None = None
    hours: Decimal = Field(gt=0, le=10_000)
    reason: str = Field(min_length=3, max_length=500)


@router.get("/downtime")
async def list_downtime(
    _: Viewer, session: Session, asset: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(Downtime).order_by(Downtime.start_date.desc()).limit(200)
    if asset:
        stmt = stmt.where(Downtime.asset_code == asset)
    return [
        {
            "asset_code": d.asset_code,
            "start_date": d.start_date.isoformat(),
            "end_date": d.end_date.isoformat() if d.end_date else None,
            "hours": _q(d.hours),
            "reason": d.reason,
            "from_dor": d.dor_id is not None,
        }
        for d in (await session.execute(stmt)).scalars()
    ]


@router.post("/downtime", status_code=201)
async def add_downtime(body: DowntimeBody, actor: Creator, session: Session) -> dict[str, str]:
    await _asset(session, body.asset_code)
    if body.end_date and body.end_date < body.start_date:
        raise AppError("DATE_INVALID", "Tanggal selesai sebelum tanggal mulai.", status_code=422)
    session.add(
        Downtime(
            asset_code=body.asset_code,
            start_date=body.start_date,
            end_date=body.end_date,
            hours=body.hours,
            reason=body.reason,
            created_by=actor.id,
        )
    )
    await session.commit()
    return {"status": "ok"}


@router.get("/kpis")
async def kpis(
    _: Viewer, session: Session, date_from: date | None = None, date_to: date | None = None
) -> dict[str, Any]:
    to = date_to or today_jakarta()
    frm = date_from or (to - timedelta(days=29))
    k = await svc.kpis(session, frm, to)

    def conv(d: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (
                _q(v)
                if isinstance(v, Decimal)
                and key in ("days_used", "operating_hours", "downtime_hours")
                else format(v, "f")
                if isinstance(v, Decimal)
                else v.isoformat()
                if isinstance(v, date)
                else v
            )
            for key, v in d.items()
        }

    return {
        "date_from": frm.isoformat(),
        "date_to": to.isoformat(),
        "rows": [conv(r) for r in k["rows"]],
        "totals": conv(k["totals"]),
        "targets": k["targets"],
    }


@router.get("/projects")
async def projects(_: Viewer, session: Session) -> list[dict[str, str]]:
    rows = await session.execute(
        select(Project.id, Project.number, Project.name)
        .where(Project.status == "locked")
        .order_by(Project.number)
    )
    return [{"id": str(i), "number": n, "name": nm} for i, n, nm in rows.tuples()]
