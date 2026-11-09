"""Order-to-cash API (06): service tickets, signing (tablet / client link), disputes, invoices,
faktur + Coretax XML, invoice pack e-mail, receipts, bank import, AR aging and cash KPIs."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Scope
from app.auth.principal import CurrentUser, Principal, require
from app.billing import invoice_service as inv_svc
from app.billing import receipt_service as rcp_svc
from app.billing import ticket_service as tk_svc
from app.billing.models import (
    BankLine,
    CustomerInvoice,
    InvoiceTicket,
    Receipt,
    ReceiptAllocation,
    ServiceTicket,
    TicketDor,
    TicketLine,
)
from app.contract.models import Contract
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, NotFoundError
from app.master.models import Client
from app.operations.models import Dor
from app.project.models import Project
from app.services.numbering import today_jakarta
from app.services.storage import Storage, get_storage

router = APIRouter(prefix="/billing", tags=["billing"])
Session = Annotated[AsyncSession, Depends(get_session)]
Store = Annotated[Storage, Depends(get_storage)]
Viewer = Annotated[Principal, Depends(require("billing", "view"))]
Creator = Annotated[Principal, Depends(require("billing", "create"))]
Editor = Annotated[Principal, Depends(require("billing", "edit"))]
Exporter = Annotated[Principal, Depends(require("billing", "export"))]


def _m(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


def _scope_projects(p: Principal) -> set[uuid.UUID] | None:
    """None = all projects; otherwise the user's projects (client representatives)."""
    return None if p.scope_for("billing", "view") == Scope.ALL else set(p.project_ids)


async def _ticket(
    session: AsyncSession, p: Principal, tid: uuid.UUID, lock: bool = False
) -> ServiceTicket:
    t = await session.get(ServiceTicket, tid, with_for_update=lock)
    scope = _scope_projects(p)
    if t is None or (scope is not None and t.project_id not in scope):
        raise NotFoundError("NOT_FOUND", "Service ticket tidak ditemukan.")
    return t


async def _invoice(session: AsyncSession, iid: uuid.UUID, lock: bool = False) -> CustomerInvoice:
    inv = await session.get(CustomerInvoice, iid, with_for_update=lock)
    if inv is None:
        raise NotFoundError("NOT_FOUND", "Invoice tidak ditemukan.")
    return inv


async def _ticket_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    if not p.can("billing", "view"):
        return False
    try:
        await _ticket(session, p, uuid.UUID(eid))
    except (ValueError, NotFoundError):
        return False
    return mode == "read" or p.can("billing", "edit") or "client_rep" in p.role_codes


async def _invoice_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    return (
        p.can("billing", "view" if mode == "read" else "edit")
        and p.scope_for("billing", "view") == Scope.ALL
    )


access.register(tk_svc.DOC, _ticket_access)
access.register(inv_svc.DOC, _invoice_access)


# ---------------------------------------------------------------- tickets


@router.get("/projects")
async def projects(_: Creator, session: Session) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Project, Contract.number)
        .join(Contract, Contract.id == Project.contract_id)
        .where(Project.status.in_(("locked", "closed")))
        .order_by(Project.number)
    )
    return [
        {"id": str(p.id), "number": p.number, "name": p.name, "contract_number": c}
        for p, c in rows.tuples()
    ]


@router.get("/billable-dors")
async def billable_dors(
    project_id: uuid.UUID, _: Creator, session: Session
) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Dor)
        .where(
            Dor.project_id == project_id,
            Dor.status == "approved",
            Dor.id.not_in(select(TicketDor.dor_id)),
        )
        .order_by(Dor.report_date)
    )
    return [
        {
            "id": str(d.id),
            "number": d.number,
            "report_date": d.report_date.isoformat(),
            "revenue": _m(d.revenue),
        }
        for d in rows.scalars()
    ]


class TicketBody(BaseModel):
    project_id: uuid.UUID
    date_from: date
    date_to: date
    dor_ids: list[uuid.UUID] | None = None


def _line(x: TicketLine) -> dict[str, Any]:
    return {
        "id": str(x.id),
        "seq": x.seq,
        "work_date": x.work_date.isoformat(),
        "kind": x.kind,
        "description": x.description,
        "qty": format(x.qty.normalize(), "f"),
        "unit": x.unit,
        "amount": _m(x.amount),
        "disputed": x.disputed,
        "dispute_reason": x.dispute_reason,
    }


async def _ticket_detail(session: AsyncSession, p: Principal, t: ServiceTicket) -> dict[str, Any]:
    project = await session.get(Project, t.project_id)
    contract = await session.get(Contract, t.contract_id)
    assert project is not None and contract is not None
    client = (
        await session.execute(select(Client.name).where(Client.code == contract.client_code))
    ).scalar_one_or_none()
    inv = await session.get(CustomerInvoice, t.invoice_id) if t.invoice_id else None
    dors = (
        await session.execute(
            select(Dor.id, Dor.number, Dor.report_date)
            .join(TicketDor, TicketDor.dor_id == Dor.id)
            .where(TicketDor.ticket_id == t.id)
            .order_by(Dor.report_date)
        )
    ).tuples()
    return {
        "id": str(t.id),
        "number": t.number,
        "status": t.status,
        "status_label": tk_svc.STATUS_LABELS.get(t.status, t.status),
        "project_id": str(project.id),
        "project_number": project.number,
        "project_name": project.name,
        "contract_number": contract.number,
        "client_name": client or contract.company_name,
        "period_from": t.period_from.isoformat(),
        "period_to": t.period_to.isoformat(),
        "gross_value": _m(t.gross_value),
        "disputed_value": _m(t.disputed_value),
        "value": _m(t.value),
        "signer_name": t.signer_name,
        "sign_method": t.sign_method,
        "signed_at": t.signed_at.isoformat() if t.signed_at else None,
        "acceptance_no": t.acceptance_no,
        "psre_ref": t.psre_ref,
        "link_email": t.link_email,
        "link_expires_at": t.link_expires_at.isoformat() if t.link_expires_at else None,
        "signed_pdf_attachment_id": str(t.signed_pdf_attachment_id)
        if t.signed_pdf_attachment_id
        else None,
        "invoice": {"id": str(inv.id), "number": inv.number} if inv else None,
        "dors": [{"id": str(i), "number": n, "report_date": d.isoformat()} for i, n, d in dors],
        "can_sign": t.status == "awaiting_signature" and p.can("billing", "edit"),
        "lines": [_line(x) for x in await tk_svc.lines_of(session, t.id)],
    }


@router.post("/tickets", status_code=201)
async def create_ticket(body: TicketBody, actor: Creator, session: Session) -> dict[str, Any]:
    p = await session.get(Project, body.project_id)
    if p is None:
        raise NotFoundError("NOT_FOUND", "Proyek tidak ditemukan.")
    t = await tk_svc.create(
        session, actor, p, date_from=body.date_from, date_to=body.date_to, dor_ids=body.dor_ids
    )
    await session.commit()
    return await _ticket_detail(session, actor, t)


@router.get("/tickets")
async def list_tickets(
    principal: Viewer, session: Session, status: str | None = None
) -> list[dict[str, Any]]:
    stmt = (
        select(ServiceTicket, Project.number)
        .join(Project, Project.id == ServiceTicket.project_id)
        .order_by(ServiceTicket.created_at.desc())
        .limit(300)
    )
    if status:
        stmt = stmt.where(ServiceTicket.status == status)
    scope = _scope_projects(principal)
    if scope is not None:
        stmt = stmt.where(ServiceTicket.project_id.in_(scope or {uuid.uuid4()}))
    return [
        {
            "id": str(t.id),
            "number": t.number,
            "status": t.status,
            "status_label": tk_svc.STATUS_LABELS.get(t.status, t.status),
            "project_number": pn,
            "period_from": t.period_from.isoformat(),
            "period_to": t.period_to.isoformat(),
            "value": _m(t.value),
            "disputed_value": _m(t.disputed_value),
            "acceptance_no": t.acceptance_no,
        }
        for t, pn in (await session.execute(stmt)).tuples()
    ]


@router.get("/tickets/{tid}")
async def get_ticket(tid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _ticket_detail(session, principal, await _ticket(session, principal, tid))


class Dispute(BaseModel):
    line_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=500)


class SignBody(BaseModel):
    signer_name: str = Field(min_length=3, max_length=120)
    signature: str = Field(min_length=20, max_length=800_000)  # PNG data URL from the pad
    acceptance_no: str | None = Field(default=None, max_length=60)
    disputes: list[Dispute] = Field(default_factory=list, max_length=500)

    def sig(self) -> tk_svc.Signature:
        return tk_svc.Signature(
            self.signer_name,
            tk_svc.decode_png(self.signature),
            self.acceptance_no,
            {d.line_id: d.reason for d in self.disputes},
        )


@router.post("/tickets/{tid}/sign")
async def sign_tablet(
    tid: uuid.UUID, body: SignBody, actor: Editor, session: Session, storage: Store
) -> dict[str, Any]:
    t = await _ticket(session, actor, tid, lock=True)
    await tk_svc.sign(session, storage, actor, t, body.sig(), method="tablet")
    await session.commit()
    return await _ticket_detail(session, actor, t)


class LinkBody(BaseModel):
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/tickets/{tid}/sign-link")
async def sign_link(
    tid: uuid.UUID, body: LinkBody, actor: Editor, session: Session
) -> dict[str, str]:
    t = await _ticket(session, actor, tid, lock=True)
    url = await tk_svc.create_link(session, actor, t, body.email)
    await session.commit()
    return {"url": url}


@router.get("/sign/{token}")
async def view_by_link(token: str, actor: CurrentUser, session: Session) -> dict[str, Any]:
    t = await tk_svc.by_token(session, actor, token)
    d = await _ticket_detail(session, actor, t)
    d["can_sign"] = t.status == "awaiting_signature"
    return d


@router.post("/sign/{token}")
async def sign_by_link(
    token: str, body: SignBody, actor: CurrentUser, session: Session, storage: Store
) -> dict[str, Any]:
    t = await tk_svc.by_token(session, actor, token, lock=True)
    await tk_svc.sign(session, storage, actor, t, body.sig(), method="link")
    await session.commit()
    d = await _ticket_detail(session, actor, t)
    d["can_sign"] = False
    return d


class ReasonBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/tickets/{tid}/cancel")
async def cancel_ticket(
    tid: uuid.UUID, body: ReasonBody, actor: Editor, session: Session
) -> dict[str, Any]:
    t = await _ticket(session, actor, tid, lock=True)
    await tk_svc.cancel(session, actor, t, body.reason)
    await session.commit()
    return await _ticket_detail(session, actor, t)


@router.get("/disputes")
async def dispute_register(_: Viewer, session: Session) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(TicketLine, ServiceTicket.number, Project.number)
        .join(ServiceTicket, ServiceTicket.id == TicketLine.ticket_id)
        .join(Project, Project.id == ServiceTicket.project_id)
        .where(TicketLine.disputed.is_(True))
        .order_by(TicketLine.disputed_at.desc())
    )
    return [
        {
            **_line(x),
            "ticket_number": tn,
            "project_number": pn,
            "disputed_at": x.disputed_at.isoformat() if x.disputed_at else None,
        }
        for x, tn, pn in rows.tuples()
    ]


# ---------------------------------------------------------------- invoices


def _inv_row(i: CustomerInvoice, client: str | None) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "number": i.number,
        "status": i.status,
        "status_label": inv_svc.STATUS_LABELS.get(i.status, i.status),
        "client_code": i.client_code,
        "client_name": client,
        "invoice_date": i.invoice_date.isoformat(),
        "due_date": i.due_date.isoformat(),
        "faktur_number": i.faktur_number,
        "subtotal": _m(i.subtotal),
        "total": _m(i.total),
        "outstanding": _m(inv_svc.outstanding(i)) if i.status != "draft" else _m(i.total),
        "overdue": i.status in inv_svc.OPEN and i.due_date < today_jakarta(),
    }


async def _inv_detail(session: AsyncSession, i: CustomerInvoice) -> dict[str, Any]:
    client = (
        await session.execute(select(Client).where(Client.code == i.client_code))
    ).scalar_one_or_none()
    contract = await session.get(Contract, i.contract_id)
    receipts = (
        await session.execute(
            select(ReceiptAllocation, Receipt.number, Receipt.receipt_date)
            .join(Receipt, Receipt.id == ReceiptAllocation.receipt_id)
            .where(ReceiptAllocation.invoice_id == i.id)
            .order_by(Receipt.receipt_date)
        )
    ).tuples()
    return {
        **_inv_row(i, client.name if client else None),
        "client_email": client.email if client else None,
        "contract_number": contract.number if contract else None,
        "dpp_other": _m(i.dpp_other),
        "ppn_rate": format(i.ppn_rate.normalize(), "f"),
        "ppn": _m(i.ppn),
        "pph23_rate": format(i.pph23_rate.normalize(), "f"),
        "pph23_expected": _m(i.pph23_expected),
        "net_cash": _m(i.net_cash),
        "stamp_duty": _m(i.stamp_duty),
        "faktur_date": i.faktur_date.isoformat() if i.faktur_date else None,
        "sent_at": i.sent_at.isoformat() if i.sent_at else None,
        "sent_to": i.sent_to,
        "paid_amount": _m(i.paid_amount),
        "pph23_withheld": _m(i.pph23_withheld),
        "paid_at": i.paid_at.isoformat() if i.paid_at else None,
        "pack_attachment_id": str(i.pack_attachment_id) if i.pack_attachment_id else None,
        "note": i.note,
        "tickets": [
            {
                "id": str(t.id),
                "number": t.number,
                "value": _m(t.value),
                "acceptance_no": t.acceptance_no,
            }
            for t in await inv_svc.tickets_of(session, i.id)
        ],
        "receipts": [
            {
                "number": n,
                "receipt_date": d.isoformat(),
                "cash": _m(a.cash),
                "pph23": _m(a.pph23),
                "bukti_potong_no": a.bukti_potong_no,
            }
            for a, n, d in receipts
        ],
    }


@router.get("/signed-tickets")
async def signed_tickets(_: Creator, session: Session) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(ServiceTicket, Contract.number, Project.number)
        .join(Contract, Contract.id == ServiceTicket.contract_id)
        .join(Project, Project.id == ServiceTicket.project_id)
        .where(
            ServiceTicket.status == "signed",
            ServiceTicket.id.not_in(select(InvoiceTicket.ticket_id)),
        )
        .order_by(ServiceTicket.number)
    )
    return [
        {
            "id": str(t.id),
            "number": t.number,
            "contract_id": str(t.contract_id),
            "contract_number": cn,
            "project_number": pn,
            "value": _m(t.value),
            "period_to": t.period_to.isoformat(),
        }
        for t, cn, pn in rows.tuples()
    ]


class InvoiceBody(BaseModel):
    ticket_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    invoice_date: date
    note: str | None = Field(default=None, max_length=2000)


@router.post("/invoices", status_code=201)
async def create_invoice(body: InvoiceBody, actor: Creator, session: Session) -> dict[str, Any]:
    i = await inv_svc.create(session, actor, body.ticket_ids, body.invoice_date, body.note)
    await session.commit()
    return await _inv_detail(session, i)


def _inv_query(status: str | None, q: str | None) -> Any:
    stmt = select(CustomerInvoice, Client.name).outerjoin(
        Client, Client.code == CustomerInvoice.client_code
    )
    if status == "overdue":
        stmt = stmt.where(
            CustomerInvoice.status.in_(inv_svc.OPEN), CustomerInvoice.due_date < today_jakarta()
        )
    elif status:
        stmt = stmt.where(CustomerInvoice.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                CustomerInvoice.number.ilike(like),
                CustomerInvoice.faktur_number.ilike(like),
                Client.name.ilike(like),
            )
        )
    return stmt


@router.get("/invoices")
async def list_invoices(
    _: Viewer, session: Session, status: str | None = None, q: str | None = None
) -> dict[str, Any]:
    rows = (
        await session.execute(
            _inv_query(status, q).order_by(CustomerInvoice.invoice_date.desc()).limit(300)
        )
    ).tuples()
    counts = dict(
        (
            await session.execute(
                select(CustomerInvoice.status, func.count()).group_by(CustomerInvoice.status)
            )
        )
        .tuples()
        .all()
    )
    return {"items": [_inv_row(i, c) for i, c in rows], "counts": counts}


@router.get("/invoices/{iid}")
async def get_invoice(iid: uuid.UUID, _: Viewer, session: Session) -> dict[str, Any]:
    return await _inv_detail(session, await _invoice(session, iid))


class FakturBody(BaseModel):
    faktur_number: str = Field(min_length=10, max_length=30)
    faktur_date: date


@router.post("/invoices/{iid}/faktur")
async def issue_faktur(
    iid: uuid.UUID, body: FakturBody, actor: Editor, session: Session
) -> dict[str, Any]:
    i = await _invoice(session, iid, lock=True)
    await inv_svc.issue_faktur(session, actor, i, body.faktur_number, body.faktur_date)
    await session.commit()
    return await _inv_detail(session, i)


@router.post("/invoices/{iid}/send")
async def send_invoice(
    iid: uuid.UUID, body: LinkBody, actor: Editor, session: Session, storage: Store
) -> dict[str, Any]:
    i = await _invoice(session, iid, lock=True)
    res = await inv_svc.send(session, storage, actor, i, body.email)
    await session.commit()
    return {**(await _inv_detail(session, i)), "email_status": res.status}


@router.post("/invoices/{iid}/pack")
async def build_pack(
    iid: uuid.UUID, actor: Editor, session: Session, storage: Store
) -> dict[str, Any]:
    i = await _invoice(session, iid, lock=True)
    await inv_svc.build_pack(session, storage, actor, i)
    await session.commit()
    return await _inv_detail(session, i)


@router.post("/invoices/{iid}/cancel")
async def cancel_invoice(iid: uuid.UUID, actor: Editor, session: Session) -> dict[str, Any]:
    i = await _invoice(session, iid, lock=True)
    await inv_svc.cancel_draft(session, actor, i)
    await session.commit()
    return await _inv_detail(session, i)


@router.get("/coretax.xml")
async def coretax(
    _: Exporter, session: Session, ids: Annotated[list[uuid.UUID], Query()]
) -> Response:
    invs = [await _invoice(session, i) for i in ids]
    data = await inv_svc.coretax_xml(session, invs)
    name = invs[0].number if len(invs) == 1 else f"coretax-{today_jakarta():%Y%m%d}"
    return Response(
        data,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{name}.xml"'},
    )


# ---------------------------------------------------------------- receipts & bank


class AllocationBody(BaseModel):
    invoice_id: uuid.UUID
    cash: Decimal = Field(ge=0, max_digits=18, decimal_places=0)
    pph23: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=0)
    bukti_potong_no: str | None = Field(default=None, max_length=60)


class ReceiptBody(BaseModel):
    receipt_date: date
    bank_ref: str | None = Field(default=None, max_length=120)
    allocations: list[AllocationBody] = Field(min_length=1, max_length=100)


@router.post("/receipts", status_code=201)
async def create_receipt(body: ReceiptBody, actor: Creator, session: Session) -> dict[str, Any]:
    r = await rcp_svc.record(
        session,
        actor,
        receipt_date=body.receipt_date,
        allocations=[
            rcp_svc.AllocationIn(a.invoice_id, a.cash, a.pph23, a.bukti_potong_no)
            for a in body.allocations
        ],
        bank_ref=body.bank_ref,
    )
    await session.commit()
    return {"id": str(r.id), "number": r.number, "cash": _m(r.cash), "pph23": _m(r.pph23)}


@router.get("/receipts")
async def list_receipts(_: Viewer, session: Session) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Receipt, Client.name)
        .outerjoin(Client, Client.code == Receipt.client_code)
        .order_by(Receipt.receipt_date.desc())
        .limit(300)
    )
    return [
        {
            "id": str(r.id),
            "number": r.number,
            "client_name": c,
            "receipt_date": r.receipt_date.isoformat(),
            "cash": _m(r.cash),
            "pph23": _m(r.pph23),
            "source": r.source,
            "bank_ref": r.bank_ref,
        }
        for r, c in rows.tuples()
    ]


@router.post("/bank-import")
async def bank_import(
    actor: Creator, session: Session, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", "Berkas maksimal 5 MB.", status_code=413)
    res = await rcp_svc.import_statement(session, actor, file.filename or "mutasi", data)
    await session.commit()
    return res


@router.get("/bank-lines")
async def bank_lines(
    _: Viewer, session: Session, status: str = "unmatched"
) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(BankLine, CustomerInvoice.number)
        .outerjoin(CustomerInvoice, CustomerInvoice.id == BankLine.suggested_invoice_id)
        .where(BankLine.status == status)
        .order_by(BankLine.value_date.desc())
        .limit(500)
    )
    return [
        {
            "id": str(b.id),
            "value_date": b.value_date.isoformat(),
            "amount": _m(b.amount),
            "description": b.description,
            "reference": b.reference,
            "status": b.status,
            "suggested_invoice_id": str(b.suggested_invoice_id) if b.suggested_invoice_id else None,
            "suggested_invoice_number": n,
            "match_rule": b.match_rule,
        }
        for b, n in rows.tuples()
    ]


class ConfirmBody(BaseModel):
    invoice_id: uuid.UUID


@router.post("/bank-lines/{bid}/confirm")
async def confirm_bank_line(
    bid: uuid.UUID, body: ConfirmBody, actor: Creator, session: Session
) -> dict[str, Any]:
    line = await session.get(BankLine, bid, with_for_update=True)
    if line is None:
        raise NotFoundError("NOT_FOUND", "Baris mutasi tidak ditemukan.")
    r = await rcp_svc.confirm_line(session, actor, line, body.invoice_id)
    await session.commit()
    return {"receipt_number": r.number, "cash": _m(r.cash), "pph23": _m(r.pph23)}


@router.post("/bank-lines/{bid}/ignore")
async def ignore_bank_line(bid: uuid.UUID, _: Creator, session: Session) -> dict[str, str]:
    line = await session.get(BankLine, bid, with_for_update=True)
    if line is None or line.status != "unmatched":
        raise NotFoundError("NOT_FOUND", "Baris mutasi tidak ditemukan.")
    line.status = "ignored"
    await session.commit()
    return {"status": "ignored"}


def _conv(d: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (_m(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, date) else v)
        for k, v in d.items()
    }


@router.get("/ar-aging")
async def ar_aging(_: Viewer, session: Session) -> dict[str, Any]:
    a = await rcp_svc.ar_aging(session, today_jakarta())
    return {
        "as_of": a["as_of"].isoformat(),
        "rows": [_conv(r) for r in a["rows"]],
        "totals": _conv(a["totals"]),
    }


@router.get("/kpis")
async def kpis(_: Viewer, session: Session) -> dict[str, Any]:
    return _conv(await rcp_svc.cash_kpis(session, today_jakarta()))
