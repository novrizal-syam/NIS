"""Payroll API (07c). Amounts per employee are salary data (UU 27/2022 PDP): only users with
the sensitive `salary` permission get them; payslip PDFs and 1721-A1 only for the employee
themself and HCBP (payroll edit + salary)."""

import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import CurrentUser, Principal, require
from app.core.db import get_session
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.master.models import Employee
from app.payroll import documents
from app.payroll import service as svc
from app.payroll.models import PayrollRun, Payslip, Pph21TerRate
from app.payroll.seed import DEFAULT_RULES
from app.project.models import Project
from app.services import audit, letterhead
from app.services.export import Column, build_xlsx
from app.services.storage import Storage, get_storage
from app.setup import service as settings_store
from app.treasury.lookup import by_code

router = APIRouter(prefix="/payroll", tags=["payroll"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("payroll", "view"))]
Editor = Annotated[Principal, Depends(require("payroll", "edit"))]
Creator = Annotated[Principal, Depends(require("payroll", "create"))]
Submitter = Annotated[Principal, Depends(require("payroll", "submit"))]
Store = Annotated[Storage, Depends(get_storage)]

MONEY = (
    "basic",
    "fixed_allowance",
    "field_allowance",
    "overtime_pay",
    "other_allowances",
    "gross",
    "kes_er",
    "kes_ee",
    "jht_er",
    "jht_ee",
    "jp_er",
    "jp_ee",
    "jkk_er",
    "jkm_er",
    "taxable",
    "pph21",
    "deductions",
    "net",
    "employer_cost",
)


def _m(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


def _hcbp(p: Principal) -> bool:
    return p.can("payroll", "edit") and p.can_see("salary")


def _may_see_slip(p: Principal, ps: Payslip) -> bool:
    return _hcbp(p) or (
        p.user.employee_code is not None and p.user.employee_code == ps.employee_code
    )


def _run_out(run: PayrollRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "year": run.year,
        "month": run.month,
        "label": svc.label(run),
        "period_start": run.period_start.isoformat(),
        "period_end": run.period_end.isoformat(),
        "pay_date": run.pay_date.isoformat(),
        "status": run.status,
        "status_label": svc.STATUS_LABELS.get(run.status, run.status),
        "request_id": str(run.request_id) if run.request_id else None,
        "reject_reason": run.reject_reason,
        "calculated_by": str(run.calculated_by) if run.calculated_by else None,
        "journal_id": str(run.journal_id) if run.journal_id else None,
        "payment_run_id": str(run.payment_run_id) if run.payment_run_id else None,
        "employees": run.employees,
        **{
            k: _m(getattr(run, k))
            for k in (
                "gross",
                "employer_bpjs",
                "employee_bpjs",
                "pph21",
                "deductions",
                "net",
                "employer_cost",
            )
        },
    }


def _slip_out(ps: Payslip, sensitive: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(ps.id),
        "employee_code": ps.employee_code,
        "employee_name": ps.employee_name,
        "position": ps.position,
        "is_field": ps.is_field,
        "ptkp_status": ps.ptkp_status,
        "ter_category": ps.ter_category,
        "site_days": ps.site_days,
        "overtime_hours": _m(ps.overtime_hours),
    }
    if sensitive:
        out.update({k: _m(getattr(ps, k)) for k in MONEY})
        out["ter_rate"] = _m(ps.ter_rate)
        out["overtime_factor_hours"] = _m(ps.overtime_factor_hours)
        out["annual"] = ps.annual
        out["allocation"] = ps.allocation
    return out


async def _run(session: AsyncSession, rid: uuid.UUID, lock: bool = False) -> PayrollRun:
    run = await session.get(PayrollRun, rid, with_for_update=lock)
    if run is None:
        raise NotFoundError("NOT_FOUND", "Penggajian tidak ditemukan.")
    return run


async def _slip(session: AsyncSession, sid: uuid.UUID) -> Payslip:
    ps = await session.get(Payslip, sid)
    if ps is None:
        raise NotFoundError("NOT_FOUND", "Slip gaji tidak ditemukan.")
    return ps


# ---------------------------------------------------------------- runs


class CalcIn(BaseModel):
    year: int = Field(ge=2024, le=2100)
    month: int = Field(ge=1, le=12)


class RecalcIn(BaseModel):
    reload: bool = False


@router.get("/runs")
async def list_runs(_: Viewer, session: Session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(PayrollRun).order_by(PayrollRun.year.desc(), PayrollRun.month.desc())
        )
    ).scalars()
    return [_run_out(r) for r in rows]


@router.post("/runs")
async def calculate(body: CalcIn, actor: Creator, session: Session) -> dict[str, Any]:
    run = await svc.calculate(session, actor, body.year, body.month)
    await session.commit()
    return _run_out(run)


@router.get("/runs/{rid}")
async def get_run(rid: uuid.UUID, p: Viewer, session: Session) -> dict[str, Any]:
    run = await _run(session, rid)
    slips = await svc.payslips_of(session, run.id)
    sensitive = p.can_see("salary")
    # Field cost per project (aggregate, not personal data) for the approver.
    per_project: dict[str, Decimal] = {}
    for s in slips:
        for a in s.allocation:
            per_project[a["project_id"]] = per_project.get(a["project_id"], Decimal(0)) + Decimal(
                a["amount"]
            )
    names = dict(
        (
            await session.execute(
                select(Project.id, Project.number).where(
                    Project.id.in_([uuid.UUID(k) for k in per_project])
                )
            )
        )
        .tuples()
        .all()
    )
    return {
        **_run_out(run),
        "allocation": [
            {"project_id": k, "project": names.get(uuid.UUID(k)), "amount": _m(v)}
            for k, v in per_project.items()
        ],
        "office_cost": _m(sum((s.employer_cost for s in slips if not s.allocation), Decimal(0))),
        "payslips": [_slip_out(s, sensitive) for s in slips],
    }


@router.post("/runs/{rid}/recalculate")
async def recalculate(
    rid: uuid.UUID, body: RecalcIn, actor: Creator, session: Session
) -> dict[str, Any]:
    run = await _run(session, rid, lock=True)
    run = await svc.calculate(session, actor, run.year, run.month, reload=body.reload)
    await session.commit()
    return _run_out(run)


@router.post("/runs/{rid}/submit")
async def submit(rid: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    run = await _run(session, rid, lock=True)
    req = await svc.submit(session, actor, run)
    await session.commit()
    return {**_run_out(run), "request_id": str(req.id)}


@router.get("/runs/{rid}/export")
async def export_run(rid: uuid.UUID, p: Viewer, session: Session) -> StreamingResponse:
    """Excel: per employee with amounts only for users allowed to see salaries."""
    run = await _run(session, rid)
    sensitive = p.can_see("salary")
    cols = [
        Column("NIP", "employee_code", width=12),
        Column("Nama", "employee_name", width=28),
        Column("PTKP", "ptkp_status", width=8),
        Column("Hari lokasi", "site_days", "number", 10),
        Column("Lembur (jam)", "overtime_hours", "number", 10),
    ]
    if sensitive:
        cols += [Column(k.replace("_", " ").title(), k, "idr", 14) for k in MONEY]
    rows = [_slip_out(s, sensitive) for s in await svc.payslips_of(session, run.id)]
    await audit.record(
        session,
        action="export",
        entity_type=svc.DOC,
        entity_id=run.id,
        actor_id=p.id,
        after={"sensitive": sensitive, "rows": len(rows)},
    )
    await session.commit()
    data = build_xlsx(f"Gaji {run.month:02d}-{run.year}", cols, rows)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="gaji-{run.year}-{run.month:02d}.xlsx"'
        },
    )


# ---------------------------------------------------------------- payslips


class DayIn(BaseModel):
    work_date: date
    project_id: uuid.UUID
    wbs_id: uuid.UUID | None = None
    overtime_hours: Decimal = Field(default=Decimal(0), ge=0, le=24)


class DaysIn(BaseModel):
    days: list[DayIn] = Field(max_length=62)
    reason: str = Field(min_length=5, max_length=300)


class ItemIn(BaseModel):
    kind: Literal["allowance", "deduction"]
    name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    taxable: bool = True


class ItemsIn(BaseModel):
    items: list[ItemIn] = Field(max_length=30)


async def _slip_detail(session: AsyncSession, ps: Payslip) -> dict[str, Any]:
    days = await svc.days_of(session, ps.id)
    items = await svc.items_of(session, ps.id)
    projects = dict(
        (
            await session.execute(
                select(Project.id, Project.number).where(
                    Project.id.in_({x.project_id for x in days})
                )
            )
        )
        .tuples()
        .all()
    )
    run = await session.get(PayrollRun, ps.run_id)
    assert run is not None
    return {
        **_slip_out(ps, True),
        "run": _run_out(run),
        "days": [
            {
                "work_date": x.work_date.isoformat(),
                "project_id": str(x.project_id),
                "project": projects.get(x.project_id),
                "wbs_id": str(x.wbs_id) if x.wbs_id else None,
                "overtime_hours": _m(x.overtime_hours),
                "source": x.source,
                "note": x.note,
            }
            for x in days
        ],
        "items": [
            {"kind": x.kind, "name": x.name, "amount": _m(x.amount), "taxable": x.taxable}
            for x in items
        ],
    }


@router.get("/payslips/{sid}")
async def get_payslip(sid: uuid.UUID, p: CurrentUser, session: Session) -> dict[str, Any]:
    ps = await _slip(session, sid)
    if not _may_see_slip(p, ps):
        raise NotFoundError("NOT_FOUND", "Slip gaji tidak ditemukan.")
    return await _slip_detail(session, ps)


@router.put("/payslips/{sid}/days")
async def set_days(sid: uuid.UUID, body: DaysIn, actor: Editor, session: Session) -> dict[str, Any]:
    if not _hcbp(actor):
        raise ForbiddenError("PERMISSION_DENIED", "Hanya HCBP yang dapat mengubah timesheet.")
    ps = await _slip(session, sid)
    await svc.set_days(session, actor, ps, [d.model_dump() for d in body.days], body.reason)
    await session.commit()
    return await _slip_detail(session, ps)


@router.put("/payslips/{sid}/items")
async def set_items(
    sid: uuid.UUID, body: ItemsIn, actor: Editor, session: Session
) -> dict[str, Any]:
    if not _hcbp(actor):
        raise ForbiddenError("PERMISSION_DENIED", "Hanya HCBP yang dapat mengubah slip gaji.")
    ps = await _slip(session, sid)
    await svc.set_items(session, actor, ps, [i.model_dump() for i in body.items])
    await session.commit()
    return await _slip_detail(session, ps)


@router.get("/payslips/{sid}/pdf")
async def payslip_pdf(
    sid: uuid.UUID, p: CurrentUser, session: Session, storage: Store
) -> StreamingResponse:
    ps = await _slip(session, sid)
    if not _may_see_slip(p, ps):
        raise NotFoundError("NOT_FOUND", "Slip gaji tidak ditemukan.")
    run = await session.get(PayrollRun, ps.run_id)
    assert run is not None
    if not _hcbp(p) and run.status not in svc.DONE:
        raise NotFoundError("NOT_FOUND", "Slip gaji belum tersedia.")
    items = [(x.kind, x.name, x.amount) for x in await svc.items_of(session, ps.id)]
    data = documents.payslip_pdf(await letterhead.load(session, storage), run, ps, items)
    await audit.record(
        session,
        action="download",
        entity_type="payslip",
        entity_id=ps.id,
        actor_id=p.id,
    )
    await session.commit()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="slip-{ps.employee_code}-{run.year}-{run.month:02d}.pdf"'
            )
        },
    )


@router.get("/my-payslips")
async def my_payslips(p: CurrentUser, session: Session) -> list[dict[str, Any]]:
    code = p.user.employee_code
    if not code:
        return []
    rows = (
        await session.execute(
            select(Payslip, PayrollRun)
            .join(PayrollRun, PayrollRun.id == Payslip.run_id)
            .where(Payslip.employee_code == code, PayrollRun.status.in_(svc.DONE))
            .order_by(PayrollRun.year.desc(), PayrollRun.month.desc())
        )
    ).tuples()
    return [
        {
            "id": str(ps.id),
            "label": svc.label(run),
            "year": run.year,
            "month": run.month,
            "net": _m(ps.net),
            "status": run.status,
        }
        for ps, run in rows
    ]


@router.get("/a1/{year}/{employee_code}")
async def a1_pdf(
    year: int, employee_code: str, p: CurrentUser, session: Session, storage: Store
) -> StreamingResponse:
    if employee_code == "me":
        employee_code = p.user.employee_code or ""
    if not employee_code or not (_hcbp(p) or p.user.employee_code == employee_code):
        raise NotFoundError("NOT_FOUND", "Bukti potong tidak ditemukan.")
    a = await svc.a1(session, year, employee_code)
    emp = await by_code(session, Employee, employee_code)
    data = documents.a1_pdf(
        await letterhead.load(session, storage),
        year,
        {
            "code": employee_code,
            "name": a["name"],
            "ptkp_status": a["ptkp_status"],
            "tax_id": (emp.npwp or emp.nik) if emp else None,
        },
        a,
    )
    await audit.record(
        session,
        action="download",
        entity_type="a1",
        entity_id=f"{year}-{employee_code}",
        actor_id=p.id,
    )
    await session.commit()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="1721A1-{year}-{employee_code}.pdf"'
        },
    )


# ---------------------------------------------------------------- reference data


class TerBand(BaseModel):
    upper: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class TerIn(BaseModel):
    category: Literal["A", "B", "C"]
    bands: list[TerBand] = Field(min_length=1, max_length=80)


@router.get("/settings")
async def get_settings(_: Viewer, session: Session) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Pph21TerRate).order_by(Pph21TerRate.category, Pph21TerRate.seq)
        )
    ).scalars()
    ter: dict[str, list[dict[str, str | None]]] = {}
    for r in rows:
        ter.setdefault(r.category, []).append({"upper": _m(r.upper), "rate": _m(r.rate)})
    return {"rules": await svc.rules(session), "ter": ter}


@router.put("/settings/rules")
async def put_rules(body: dict[str, Any], actor: Editor, session: Session) -> dict[str, Any]:
    allowed = set(DEFAULT_RULES)
    clean = {k: v for k, v in body.items() if k in allowed}
    before = await settings_store.get(session, svc.RULES_KEY, {})
    await settings_store.put(session, svc.RULES_KEY, clean, actor.id)
    await audit.record(
        session,
        action="update",
        entity_type="payroll_rules",
        entity_id=svc.RULES_KEY,
        actor_id=actor.id,
        before=before,
        after=clean,
    )
    await session.commit()
    return await svc.rules(session)


@router.put("/settings/ter")
async def put_ter(body: TerIn, actor: Editor, session: Session) -> dict[str, Any]:
    if body.bands[-1].upper is not None or any(b.upper is None for b in body.bands[:-1]):
        raise AppError(
            "TER_BANDS_INVALID", "Hanya lapisan terakhir yang tanpa batas atas.", status_code=422
        )
    uppers = [b.upper or Decimal(0) for b in body.bands[:-1]]
    if uppers != sorted(uppers) or len(set(uppers)) != len(uppers):
        raise AppError("TER_BANDS_INVALID", "Batas atas harus naik berurutan.", status_code=422)
    old = list(
        (
            await session.execute(
                select(Pph21TerRate).where(Pph21TerRate.category == body.category)
            )
        ).scalars()
    )
    for r in old:
        await session.delete(r)
    await session.flush()
    for i, b in enumerate(body.bands, start=1):
        session.add(Pph21TerRate(category=body.category, seq=i, upper=b.upper, rate=b.rate))
    await audit.record(
        session,
        action="update",
        entity_type="pph21_ter",
        entity_id=body.category,
        actor_id=actor.id,
        before={"bands": len(old)},
        after={"bands": [b.model_dump(mode="json") for b in body.bands]},
    )
    await session.commit()
    return {"category": body.category, "bands": len(body.bands)}
