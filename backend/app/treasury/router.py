"""Treasury API (07b): bank accounts and reconciliation, payment runs, cash forecast,
cash advances."""

import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Scope
from app.auth.principal import CurrentUser, Principal, require
from app.billing import receipt_service
from app.billing.documents import _start
from app.billing.models import BankLine
from app.core import access
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.crm.quotation_pdf import _t, id_date
from app.master.models import CostElement, Vendor
from app.project.models import Project, ProjectMember, ProjectWbs
from app.services import letterhead
from app.services.numbering import today_jakarta
from app.services.storage import Storage, get_storage
from app.setup import service as settings_store
from app.treasury import advance_service as adv
from app.treasury import bank_service, forecast
from app.treasury import payment_service as pay
from app.treasury.lookup import by_code
from app.treasury.models import BankAccount, CashAdvance, PaymentRun

router = APIRouter(prefix="/treasury", tags=["treasury"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("treasury", "view"))]
Creator = Annotated[Principal, Depends(require("treasury", "create"))]
Submitter = Annotated[Principal, Depends(require("treasury", "submit"))]
Poster = Annotated[Principal, Depends(require("treasury", "post"))]


async def _finance_admin(principal: CurrentUser) -> Principal:
    if not (principal.can("finance", "approve") or principal.can("treasury", "approve")):
        raise ForbiddenError(
            "PERMISSION_DENIED", "Hanya Lead Controller / Head of Finance yang mengelola rekening."
        )
    return principal


FinanceAdmin = Annotated[Principal, Depends(_finance_admin)]


def _all(p: Principal) -> bool:
    return p.scope_for("treasury", "view") == Scope.ALL


async def _ca_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    try:
        ca = await session.get(CashAdvance, uuid.UUID(eid))
    except ValueError:
        return False
    if ca is None or not p.can("treasury", "view"):
        return False
    if mode == "read":
        return _all(p) or ca.requester_id == p.id
    return ca.requester_id == p.id or p.can("treasury", "post")


async def _run_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    return p.can("treasury", "view" if mode == "read" else "create") and _all(p)


access.register(adv.DOC, _ca_access)
access.register(pay.DOC, _run_access)


# ---------------------------------------------------------------- bank accounts


class BankAccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    bank_name: str = Field(min_length=1, max_length=60)
    account_no: str = Field(min_length=1, max_length=40)
    currency: str = Field(default="IDR", pattern="^(IDR|USD)$")
    gl_account: str = Field(min_length=4, max_length=10)
    adapter: str = Field(default="csv", max_length=20)
    is_default: bool = False
    is_active: bool = True


@router.get("/bank-accounts")
async def list_accounts(_: Viewer, session: Session) -> list[dict[str, Any]]:
    return await bank_service.accounts(session)


@router.post("/bank-accounts")
async def create_account(
    body: BankAccountIn, actor: FinanceAdmin, session: Session
) -> dict[str, Any]:
    acc = await bank_service.save_account(session, actor, body.model_dump())
    await session.commit()
    return {"id": str(acc.id)}


@router.put("/bank-accounts/{aid}")
async def update_account(
    aid: uuid.UUID, body: BankAccountIn, actor: FinanceAdmin, session: Session
) -> dict[str, Any]:
    acc = await session.get(BankAccount, aid)
    if acc is None:
        raise NotFoundError("BANK_ACCOUNT_NOT_FOUND", "Rekening bank tidak ditemukan.")
    await bank_service.save_account(session, actor, body.model_dump(), acc)
    await session.commit()
    return {"id": str(acc.id)}


@router.post("/bank-accounts/{aid}/statements")
async def import_statement(
    aid: uuid.UUID,
    actor: Annotated[Principal, Depends(require("treasury", "edit"))],
    session: Session,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    acc = await bank_service.account_or_default(session, aid)
    out = await receipt_service.import_statement(
        session, actor, file.filename or "mutasi", await file.read(), acc.id
    )
    out["reconciled"] = await bank_service.auto_match(session, actor, acc)
    await session.commit()
    return out


@router.post("/bank-accounts/{aid}/auto-match")
async def auto_match(
    aid: uuid.UUID,
    actor: Annotated[Principal, Depends(require("treasury", "edit"))],
    session: Session,
) -> dict[str, Any]:
    acc = await bank_service.account_or_default(session, aid)
    n = await bank_service.auto_match(session, actor, acc)
    await session.commit()
    return {"reconciled": n}


@router.get("/bank-accounts/{aid}/reconciliation")
async def reconciliation(
    aid: uuid.UUID, _: Viewer, session: Session, as_of: date | None = None
) -> dict[str, Any]:
    acc = await bank_service.account_or_default(session, aid)
    return await bank_service.reconciliation(session, acc, as_of)


class MatchIn(BaseModel):
    journal_line_id: uuid.UUID


async def _line(session: AsyncSession, lid: uuid.UUID) -> BankLine:
    line = await session.get(BankLine, lid, with_for_update=True)
    if line is None:
        raise NotFoundError("NOT_FOUND", "Baris mutasi tidak ditemukan.")
    return line


@router.post("/bank-lines/{lid}/match")
async def match_line(
    lid: uuid.UUID,
    body: MatchIn,
    actor: Annotated[Principal, Depends(require("treasury", "edit"))],
    session: Session,
) -> dict[str, Any]:
    line = await bank_service.match(session, actor, await _line(session, lid), body.journal_line_id)
    await session.commit()
    return {"id": str(line.id), "journal_line_id": str(line.journal_line_id)}


@router.post("/bank-lines/{lid}/unmatch")
async def unmatch_line(
    lid: uuid.UUID,
    actor: Annotated[Principal, Depends(require("treasury", "edit"))],
    session: Session,
) -> dict[str, Any]:
    line = await bank_service.unmatch(session, actor, await _line(session, lid))
    await session.commit()
    return {"id": str(line.id)}


# ---------------------------------------------------------------- payment runs


class ItemModel(BaseModel):
    kind: str = Field(pattern="^(vendor_invoice|payroll|salaries|bpjs|pph21|pph23)$")
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    vendor_invoice_id: uuid.UUID | None = None
    payroll_run_id: uuid.UUID | None = None
    reference: str | None = Field(default=None, max_length=120)


class RunIn(BaseModel):
    pay_date: date
    bank_account_id: uuid.UUID
    description: str | None = Field(default=None, max_length=300)
    items: list[ItemModel] = Field(min_length=1, max_length=500)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


def _items(body: RunIn) -> list[pay.ItemIn]:
    return [
        pay.ItemIn(i.kind, i.amount, i.vendor_invoice_id, i.reference, i.payroll_run_id)
        for i in body.items
    ]


async def _run(session: AsyncSession, rid: uuid.UUID, lock: bool = False) -> PaymentRun:
    run = await session.get(PaymentRun, rid, with_for_update=lock)
    if run is None:
        raise NotFoundError("NOT_FOUND", "Payment run tidak ditemukan.")
    return run


async def _run_out(session: AsyncSession, run: PaymentRun) -> dict[str, Any]:
    acc = await session.get(BankAccount, run.bank_account_id)
    out = pay.to_dict(run, await pay.items_of(session, run.id), acc)
    out["bukti_potong_vendors"] = sorted(await pay.bukti_potong(session, run))
    return out


@router.get("/payment-runs/due-items")
async def due_items(_: Viewer, session: Session, due_by: date | None = None) -> dict[str, Any]:
    return await pay.due_items(session, due_by or today_jakarta())


@router.get("/payment-runs")
async def list_runs(_: Viewer, session: Session, status: str | None = None) -> list[dict[str, Any]]:
    stmt = select(PaymentRun).order_by(PaymentRun.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(PaymentRun.status == status)
    accs = {a.id: a for a in (await session.execute(select(BankAccount))).scalars()}
    return [
        pay.to_dict(r, [], accs.get(r.bank_account_id))
        for r in (await session.execute(stmt)).scalars()
    ]


@router.get("/payment-runs/{rid}")
async def get_run(rid: uuid.UUID, _: Viewer, session: Session) -> dict[str, Any]:
    return await _run_out(session, await _run(session, rid))


@router.post("/payment-runs")
async def create_run(body: RunIn, actor: Creator, session: Session) -> dict[str, Any]:
    run = await pay.create(
        session,
        actor,
        pay_date=body.pay_date,
        bank_account_id=body.bank_account_id,
        description=body.description,
        items=_items(body),
    )
    await session.commit()
    return await _run_out(session, run)


@router.put("/payment-runs/{rid}")
async def update_run(
    rid: uuid.UUID,
    body: RunIn,
    actor: Annotated[Principal, Depends(require("treasury", "edit"))],
    session: Session,
) -> dict[str, Any]:
    run = await pay.update(
        session,
        actor,
        await _run(session, rid, lock=True),
        pay_date=body.pay_date,
        bank_account_id=body.bank_account_id,
        description=body.description,
        items=_items(body),
    )
    await session.commit()
    return await _run_out(session, run)


@router.post("/payment-runs/{rid}/submit")
async def submit_run(rid: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    run = await _run(session, rid, lock=True)
    req = await pay.submit(session, actor, run)
    await session.commit()
    return {"id": str(run.id), "status": run.status, "request_id": str(req.id)}


@router.post("/payment-runs/{rid}/cancel")
async def cancel_run(
    rid: uuid.UUID, body: ReasonIn, actor: Creator, session: Session
) -> dict[str, Any]:
    run = await _run(session, rid, lock=True)
    await pay.cancel(session, actor, run, body.reason)
    await session.commit()
    return {"id": str(run.id), "status": run.status}


@router.post("/payment-runs/{rid}/release")
async def release_run(rid: uuid.UUID, actor: Poster, session: Session) -> dict[str, Any]:
    run = await pay.release(session, actor, await _run(session, rid, lock=True))
    await session.commit()
    return await _run_out(session, run)


@router.get("/payment-runs/{rid}/bank-file")
async def bank_file(rid: uuid.UUID, _: Poster, session: Session) -> StreamingResponse:
    run = await _run(session, rid)
    if run.status != "released":
        raise NotFoundError("NOT_RELEASED", "File bank tersedia setelah payment run dirilis.")
    f = await pay.bank_file(session, run)
    return StreamingResponse(
        io.BytesIO(f.content),
        media_type=f.content_type,
        headers={"Content-Disposition": f'attachment; filename="{f.filename}"'},
    )


@router.get("/payment-runs/{rid}/bukti-potong/{vendor_code}")
async def bukti_potong_pdf(
    rid: uuid.UUID,
    vendor_code: str,
    _: Viewer,
    session: Session,
    storage: Annotated[Storage, Depends(get_storage)],
) -> StreamingResponse:
    run = await _run(session, rid)
    if run.status != "released":
        raise NotFoundError("NOT_RELEASED", "Bukti potong tersedia setelah payment run dirilis.")
    rows = (await pay.bukti_potong(session, run)).get(vendor_code)
    vendor = await by_code(session, Vendor, vendor_code)
    if not rows or vendor is None:
        raise NotFoundError("NOT_FOUND", "Tidak ada PPh 23 untuk vendor ini di payment run ini.")
    head = await letterhead.load(session, storage)
    company = head.company
    pdf = _start(head)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, _t("BUKTI PEMOTONGAN PPh PASAL 23"), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(
        0,
        5,
        _t(f"Nomor: BP23/{run.number}/{vendor.code} · Tanggal: {id_date(run.pay_date)}"),
        new_x="LMARGIN",
        new_y="NEXT",
        align="C",
    )
    pdf.ln(4)
    for label, value in (
        ("Pemotong", company.get("legal_name") or "-"),
        ("NPWP pemotong", company.get("npwp") or "-"),
        ("Dipotong (vendor)", vendor.name),
        ("NPWP vendor", vendor.npwp or "-"),
        ("Payment run", run.number),
    ):
        pdf.cell(45, 6, _t(label))
        pdf.cell(0, 6, _t(f": {value}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    widths = (30, 40, 25, 35, 20, 30)
    pdf.set_font("Helvetica", "B", 9)
    for w, h in zip(
        widths,
        ("No. VI", "No. invoice vendor", "Tanggal", "DPP (Rp)", "Tarif", "PPh 23 (Rp)"),
        strict=True,
    ):
        pdf.cell(w, 7, _t(h), border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    total_dpp = total_pph = Decimal(0)

    def idr(v: Decimal) -> str:
        return f"{int(v):,}".replace(",", ".")

    for r in rows:
        cells = (
            r["number"],
            r["invoice_no"][:24],
            id_date(r["invoice_date"]),
            idr(r["dpp"]),
            f"{r['rate']}%",
            idr(r["pph23"]),
        )
        for w, c in zip(widths, cells, strict=True):
            pdf.cell(w, 7, _t(str(c)), border=1)
        pdf.ln()
        total_dpp += r["dpp"]
        total_pph += r["pph23"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(95, 7, _t("Jumlah"), border=1)
    pdf.cell(35, 7, idr(total_dpp), border=1)
    pdf.cell(20, 7, "", border=1)
    pdf.cell(30, 7, idr(total_pph), border=1)
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(
        0,
        4,
        _t(
            "Dokumen ini adalah ringkasan pemotongan untuk vendor. Bukti potong resmi "
            "(e-Bupot Unifikasi) diterbitkan di Coretax DJP oleh Tax Specialist."
        ),
    )
    data = bytes(pdf.output())
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="BP23-{run.number}-{vendor.code}.pdf"'
        },
    )


# ---------------------------------------------------------------- forecast


@router.get("/forecast")
async def cash_forecast(_: Viewer, session: Session) -> dict[str, Any]:
    return await forecast.build(session)


@router.put("/forecast/settings")
async def forecast_settings(
    body: dict[str, Any], actor: FinanceAdmin, session: Session
) -> dict[str, Any]:
    allowed = {
        "payroll_monthly",
        "bpjs_monthly",
        "pph_monthly",
        "ppn_monthly",
        "wip_collection_days",
        "loans",
        "capex",
    }
    clean = {k: v for k, v in body.items() if k in allowed}
    await settings_store.put(session, forecast.KEY, clean, actor.id)
    await session.commit()
    return clean


# ---------------------------------------------------------------- cash advances


class AdvanceIn(BaseModel):
    purpose: str = Field(min_length=3, max_length=500)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    needed_date: date
    project_id: uuid.UUID | None = None


class SettlementLineIn(BaseModel):
    spent_on: date
    cost_element: str = Field(min_length=1, max_length=20)
    wbs_code: str | None = Field(default=None, max_length=30)
    description: str = Field(min_length=1, max_length=300)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    attachment_id: uuid.UUID | None = None


class SettlementIn(BaseModel):
    lines: list[SettlementLineIn] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class PayoutIn(BaseModel):
    on: date | None = None
    bank_account_id: uuid.UUID | None = None


async def _advance(
    session: AsyncSession, p: Principal, aid: uuid.UUID, lock: bool = False
) -> CashAdvance:
    ca = await session.get(CashAdvance, aid, with_for_update=lock)
    if ca is None or not (_all(p) or ca.requester_id == p.id):
        raise NotFoundError("NOT_FOUND", "Uang muka tidak ditemukan.")
    return ca


async def _check_project(session: AsyncSession, p: Principal, project_id: uuid.UUID | None) -> None:
    """Without all-scope treasury rights an advance is charged only to one's own projects."""
    if project_id is None or _all(p):
        return
    member = (
        await session.execute(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == p.id
            )
        )
    ).first()
    manager = (
        await session.execute(
            select(Project.id).where(Project.id == project_id, Project.manager_id == p.id)
        )
    ).first()
    if not (member or manager):
        raise ForbiddenError(
            "PROJECT_NOT_MEMBER", "Uang muka hanya untuk proyek tempat Anda menjadi anggota tim."
        )


def _own(p: Principal, ca: CashAdvance) -> None:
    if ca.requester_id != p.id:
        raise ForbiddenError("NOT_REQUESTER", "Hanya pemohon yang dapat mengubah uang muka ini.")


@router.get("/advance-options")
async def advance_options(p: Viewer, session: Session) -> dict[str, Any]:
    """Cost elements and the projects (with WBS) the user may charge an advance to."""
    ces = (
        await session.execute(
            select(CostElement.code, CostElement.name)
            .where(CostElement.is_active.is_(True), CostElement.account_code.is_not(None))
            .order_by(CostElement.code)
        )
    ).all()
    stmt = select(Project).where(Project.status == "locked").order_by(Project.number)
    if not _all(p):
        stmt = stmt.where(
            Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == p.id))
        )
    projects = list((await session.execute(stmt)).scalars())
    wbs = (
        await session.execute(
            select(ProjectWbs.project_id, ProjectWbs.code)
            .where(ProjectWbs.project_id.in_([x.id for x in projects]))
            .order_by(ProjectWbs.seq)
        )
    ).all()
    return {
        "cost_elements": [{"code": c, "name": n} for c, n in ces],
        "projects": [
            {
                "id": str(x.id),
                "number": x.number,
                "name": x.name,
                "wbs": [code for pid, code in wbs if pid == x.id],
            }
            for x in projects
        ],
    }


@router.get("/advances")
async def list_advances(
    p: Viewer, session: Session, status: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(CashAdvance).order_by(CashAdvance.created_at.desc()).limit(300)
    if not _all(p):
        stmt = stmt.where(CashAdvance.requester_id == p.id)
    if status:
        stmt = stmt.where(CashAdvance.status == status)
    return [adv.to_dict(ca) for ca in (await session.execute(stmt)).scalars()]


@router.get("/advances/{aid}")
async def get_advance(aid: uuid.UUID, p: Viewer, session: Session) -> dict[str, Any]:
    ca = await _advance(session, p, aid)
    return adv.to_dict(ca, await adv.lines_of(session, ca.id))


@router.post("/advances")
async def create_advance(body: AdvanceIn, actor: Creator, session: Session) -> dict[str, Any]:
    await _check_project(session, actor, body.project_id)
    ca = await adv.create(session, actor, **body.model_dump())
    await session.commit()
    return adv.to_dict(ca)


@router.put("/advances/{aid}")
async def update_advance(
    aid: uuid.UUID, body: AdvanceIn, actor: Creator, session: Session
) -> dict[str, Any]:
    ca = await _advance(session, actor, aid, lock=True)
    _own(actor, ca)
    await _check_project(session, actor, body.project_id)
    await adv.update(session, actor, ca, **body.model_dump())
    await session.commit()
    return adv.to_dict(ca)


@router.post("/advances/{aid}/submit")
async def submit_advance(aid: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    ca = await _advance(session, actor, aid, lock=True)
    _own(actor, ca)
    req = await adv.submit(session, actor, ca)
    await session.commit()
    return {"id": str(ca.id), "status": ca.status, "request_id": str(req.id)}


@router.post("/advances/{aid}/cancel")
async def cancel_advance(
    aid: uuid.UUID, body: ReasonIn, actor: Creator, session: Session
) -> dict[str, Any]:
    ca = await _advance(session, actor, aid, lock=True)
    if ca.requester_id != actor.id and not actor.can("treasury", "post"):
        raise ForbiddenError("NOT_REQUESTER", "Hanya pemohon atau Kasir yang dapat membatalkan.")
    await adv.cancel(session, actor, ca, body.reason)
    await session.commit()
    return adv.to_dict(ca)


@router.post("/advances/{aid}/disburse")
async def disburse_advance(
    aid: uuid.UUID, body: PayoutIn, actor: Poster, session: Session
) -> dict[str, Any]:
    ca = await _advance(session, actor, aid, lock=True)
    await adv.disburse(
        session, actor, ca, on=body.on or today_jakarta(), bank_account_id=body.bank_account_id
    )
    await session.commit()
    return adv.to_dict(ca)


@router.post("/advances/{aid}/settlement")
async def submit_settlement(
    aid: uuid.UUID, body: SettlementIn, actor: Viewer, session: Session
) -> dict[str, Any]:
    ca = await _advance(session, actor, aid, lock=True)
    await adv.submit_settlement(
        session,
        actor,
        ca,
        [
            adv.LineIn(
                x.spent_on, x.cost_element, x.description, x.amount, x.wbs_code, x.attachment_id
            )
            for x in body.lines
        ],
        body.note,
    )
    await session.commit()
    return adv.to_dict(ca, await adv.lines_of(session, ca.id))


@router.post("/advances/{aid}/settlement/return")
async def return_settlement(
    aid: uuid.UUID, body: ReasonIn, actor: Poster, session: Session
) -> dict[str, Any]:
    ca = await _advance(session, actor, aid, lock=True)
    await adv.return_settlement(session, actor, ca, body.reason)
    await session.commit()
    return adv.to_dict(ca, await adv.lines_of(session, ca.id))


@router.post("/advances/{aid}/settle")
async def settle_advance(
    aid: uuid.UUID, body: PayoutIn, actor: Poster, session: Session
) -> dict[str, Any]:
    ca = await _advance(session, actor, aid, lock=True)
    await adv.settle(session, actor, ca, on=body.on or today_jakarta())
    await session.commit()
    return adv.to_dict(ca, await adv.lines_of(session, ca.id))


@router.post("/advances/run-alerts")
async def run_alerts(_: Poster, session: Session) -> dict[str, Any]:
    n = await adv.overdue_alerts(session)
    await session.commit()
    return {"sent": n}
