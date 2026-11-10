"""Client and vendor portals (10c).

External users hold the `client_rep` or `vendor` role and are linked to one client or vendor
(`users.client_code` / `users.vendor_code`). Every portal endpoint filters by that link; the
roles carry no other internal rights except the client's view of its own projects' tickets.

Client: service tickets (sign with the signature pad), invoices with outstanding amount and
the invoice pack. Vendor: RFQ invitations (submit or decline a quote), invoice upload with the
PDF (AP registers it), invoices and payment status."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import CurrentUser, Principal, require
from app.billing import ticket_service as tk_svc
from app.billing.models import CustomerInvoice, ServiceTicket
from app.billing.router import SignBody
from app.contract.models import Contract
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.dms import service as dms
from app.dms.models import AccessLog, Attachment
from app.finance import ap_service as ap
from app.finance.models import VendorInvoice
from app.master.models import Client, Vendor
from app.notifications import service as notifications
from app.portal.models import VendorSubmission
from app.procurement import pr_service, rfq_service
from app.procurement.models import PurchaseOrder, Rfq, RfqQuote
from app.services import audit
from app.services.numbering import today_jakarta
from app.services.storage import Storage, get_storage
from app.treasury.lookup import by_code
from app.treasury.models import PaymentRun, PaymentRunItem
from app.workflow import engine

router = APIRouter(prefix="/portal", tags=["portal"])
Session = Annotated[AsyncSession, Depends(get_session)]
Store = Annotated[Storage, Depends(get_storage)]
SUB_DOC = "vendor_submission"


async def _client_user(p: CurrentUser) -> Principal:
    if "client_rep" not in p.role_codes or not p.user.client_code:
        raise ForbiddenError("NOT_CLIENT_PORTAL", "Akun ini tidak terhubung ke klien.")
    return p


async def _vendor_user(p: CurrentUser) -> Principal:
    if "vendor" not in p.role_codes or not p.user.vendor_code:
        raise ForbiddenError("NOT_VENDOR_PORTAL", "Akun ini tidak terhubung ke vendor.")
    return p


ClientUser = Annotated[Principal, Depends(_client_user)]
VendorUser = Annotated[Principal, Depends(_vendor_user)]


async def _sub_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    try:
        sub = await session.get(VendorSubmission, uuid.UUID(eid))
    except ValueError:
        return False
    if sub is None:
        return False
    if p.user.vendor_code == sub.vendor_code and "vendor" in p.role_codes:
        return mode == "read"
    return p.can("finance", "view" if mode == "read" else "create")


access.register(SUB_DOC, _sub_access)


def _m(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


@router.get("/me")
async def me(p: CurrentUser, session: Session) -> dict[str, Any]:
    client = await by_code(session, Client, p.user.client_code) if p.user.client_code else None
    vendor = await by_code(session, Vendor, p.user.vendor_code) if p.user.vendor_code else None
    return {
        "client": {"code": client.code, "name": client.name}
        if client and "client_rep" in p.role_codes
        else None,
        "vendor": {"code": vendor.code, "name": vendor.name}
        if vendor and "vendor" in p.role_codes
        else None,
    }


# ---------------------------------------------------------------- client


async def _client_ticket(
    session: AsyncSession, p: Principal, tid: uuid.UUID, lock: bool = False
) -> ServiceTicket:
    t = await session.get(ServiceTicket, tid, with_for_update=lock)
    contract = await session.get(Contract, t.contract_id) if t else None
    if t is None or contract is None or contract.client_code != p.user.client_code:
        raise NotFoundError("NOT_FOUND", "Tiket tidak ditemukan.")
    return t


@router.get("/client/tickets")
async def client_tickets(p: ClientUser, session: Session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ServiceTicket, Contract.number)
            .join(Contract, Contract.id == ServiceTicket.contract_id)
            .where(Contract.client_code == p.user.client_code, ServiceTicket.status != "cancelled")
            .order_by(ServiceTicket.period_to.desc())
        )
    ).tuples()
    return [
        {
            "id": str(t.id),
            "number": t.number,
            "contract": cn,
            "period_from": t.period_from.isoformat(),
            "period_to": t.period_to.isoformat(),
            "status": t.status,
            "status_label": tk_svc.STATUS_LABELS.get(t.status, t.status),
            "value": _m(t.value),
            "can_sign": t.status == "awaiting_signature",
        }
        for t, cn in rows
    ]


@router.get("/client/tickets/{tid}")
async def client_ticket(tid: uuid.UUID, p: ClientUser, session: Session) -> dict[str, Any]:
    t = await _client_ticket(session, p, tid)
    lines = await tk_svc.lines_of(session, t.id)
    return {
        "id": str(t.id),
        "number": t.number,
        "status": t.status,
        "period_from": t.period_from.isoformat(),
        "period_to": t.period_to.isoformat(),
        "value": _m(t.value),
        "can_sign": t.status == "awaiting_signature",
        "lines": [
            {
                "id": str(x.id),
                "description": x.description,
                "qty": format(x.qty, "f"),
                "unit": x.unit,
                "amount": _m(x.amount),
                "disputed": x.disputed,
            }
            for x in lines
        ],
    }


@router.post("/client/tickets/{tid}/sign")
async def client_sign(
    tid: uuid.UUID, body: SignBody, p: ClientUser, session: Session, storage: Store
) -> dict[str, Any]:
    t = await _client_ticket(session, p, tid, lock=True)
    await tk_svc.sign(session, storage, p, t, body.sig(), method="portal")
    await session.commit()
    return {"id": str(t.id), "status": t.status}


@router.get("/client/invoices")
async def client_invoices(p: ClientUser, session: Session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(CustomerInvoice)
            .where(
                CustomerInvoice.client_code == p.user.client_code,
                CustomerInvoice.status.in_(("faktur_issued", "sent", "paid")),
            )
            .order_by(CustomerInvoice.invoice_date.desc())
        )
    ).scalars()
    return [
        {
            "id": str(i.id),
            "number": i.number,
            "invoice_date": i.invoice_date.isoformat(),
            "due_date": i.due_date.isoformat(),
            "faktur_number": i.faktur_number,
            "total": _m(i.total),
            "net_cash": _m(i.net_cash),
            "outstanding": _m(i.net_cash - i.paid_amount) if i.status != "paid" else "0",
            "status": i.status,
            "has_pack": i.pack_attachment_id is not None,
        }
        for i in rows
    ]


@router.get("/client/invoices/{iid}/pack")
async def client_pack(iid: uuid.UUID, p: ClientUser, session: Session, storage: Store) -> Response:
    inv = await session.get(CustomerInvoice, iid)
    if inv is None or inv.client_code != p.user.client_code or inv.pack_attachment_id is None:
        raise NotFoundError("NOT_FOUND", "Paket invoice tidak tersedia.")
    att = await session.get(Attachment, inv.pack_attachment_id)
    assert att is not None
    obj = await storage.get(att.storage_key)
    session.add(
        AccessLog(attachment_id=att.id, user_id=p.id, action="download", detail="portal klien")
    )
    await session.commit()
    return Response(
        obj.data,
        media_type=att.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(att.filename)}",
            "Cache-Control": "private, no-store",
        },
    )


# ---------------------------------------------------------------- vendor


@router.get("/vendor/rfqs")
async def vendor_rfqs(p: VendorUser, session: Session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(RfqQuote, Rfq)
            .join(Rfq, Rfq.id == RfqQuote.rfq_id)
            .where(RfqQuote.vendor_code == p.user.vendor_code)
            .order_by(Rfq.created_at.desc())
        )
    ).tuples()
    out = []
    for q, rfq in rows:
        out.append(
            {
                "quote_id": str(q.id),
                "rfq": rfq.number,
                "due_date": rfq.due_date.isoformat() if rfq.due_date else None,
                "open": rfq.status == "open",
                "status": q.status,
                "total": _m(q.total),
                "awarded": rfq.awarded_vendor_code == q.vendor_code
                if rfq.awarded_vendor_code
                else None,
            }
        )
    return out


async def _vendor_quote(
    session: AsyncSession, p: Principal, qid: uuid.UUID
) -> tuple[RfqQuote, Rfq]:
    q = await session.get(RfqQuote, qid, with_for_update=True)
    if q is None or q.vendor_code != p.user.vendor_code:
        raise NotFoundError("NOT_FOUND", "Undangan RFQ tidak ditemukan.")
    rfq = await session.get(Rfq, q.rfq_id)
    assert rfq is not None
    return q, rfq


@router.get("/vendor/rfqs/{qid}")
async def vendor_rfq(qid: uuid.UUID, p: VendorUser, session: Session) -> dict[str, Any]:
    q, rfq = await _vendor_quote(session, p, qid)
    priced = {x.seq: x for x in await rfq_service.quote_lines(session, q.id)}
    return {
        "quote_id": str(q.id),
        "rfq": rfq.number,
        "due_date": rfq.due_date.isoformat() if rfq.due_date else None,
        "open": rfq.status == "open",
        "status": q.status,
        "delivery_days": q.delivery_days,
        "payment_terms": q.payment_terms,
        "valid_until": q.valid_until.isoformat() if q.valid_until else None,
        "lines": [
            {
                "seq": x.seq,
                "description": x.description,
                "qty": format(x.qty, "f"),
                "uom": x.uom,
                "unit_price": _m(priced[x.seq].unit_price) if x.seq in priced else None,
            }
            for x in await pr_service.lines_of(session, rfq.pr_id)
        ],
    }


class QuoteIn(BaseModel):
    unit_prices: dict[int, Decimal] = Field(default_factory=dict)
    delivery_days: int = Field(default=0, ge=0, le=365)
    payment_terms: str | None = Field(default=None, max_length=200)
    valid_until: date | None = None
    note: str | None = Field(default=None, max_length=1000)
    declined: bool = False


@router.put("/vendor/rfqs/{qid}")
async def vendor_quote(
    qid: uuid.UUID, body: QuoteIn, p: VendorUser, session: Session
) -> dict[str, Any]:
    q, rfq = await _vendor_quote(session, p, qid)
    if rfq.due_date and rfq.due_date < today_jakarta() and not body.declined:
        raise ConflictError("RFQ_DUE", "Batas waktu penawaran sudah lewat.")
    await rfq_service.record_quote(
        session,
        p,
        rfq,
        q,
        unit_prices=body.unit_prices,
        delivery_days=body.delivery_days,
        payment_terms=body.payment_terms,
        valid_until=body.valid_until,
        note=body.note,
        declined=body.declined,
    )
    await session.commit()
    return {"quote_id": str(q.id), "status": q.status, "total": _m(q.total)}


@router.post("/vendor/invoices")
async def vendor_upload(
    p: VendorUser,
    session: Session,
    storage: Store,
    po_number: Annotated[str, Form(min_length=3, max_length=30)],
    invoice_no: Annotated[str, Form(min_length=1, max_length=60)],
    invoice_date: Annotated[date, Form()],
    amount: Annotated[Decimal, Form(gt=0, max_digits=18, decimal_places=0)],
    file: Annotated[UploadFile, File()],
    tax_invoice_no: Annotated[str | None, Form(max_length=30)] = None,
) -> dict[str, Any]:
    po = (
        await session.execute(select(PurchaseOrder).where(PurchaseOrder.number == po_number))
    ).scalar_one_or_none()
    if po is None or po.vendor_code != p.user.vendor_code:
        raise AppError(
            "PO_INVALID", f"PO {po_number} tidak ditemukan untuk vendor Anda.", status_code=422
        )
    sub_id = uuid.uuid4()
    data = await file.read(dms.MAX_BYTES + 1)
    att = await dms.upload(
        session,
        storage,
        p,
        entity_type=SUB_DOC,
        entity_id=str(sub_id),
        filename=file.filename or "invoice.pdf",
        data=data,
        note=f"Invoice {invoice_no}",
    )
    sub = VendorSubmission(
        id=sub_id,
        vendor_code=p.user.vendor_code,
        po_number=po.number,
        invoice_no=invoice_no.strip(),
        invoice_date=invoice_date,
        tax_invoice_no=tax_invoice_no,
        amount=amount,
        attachment_id=att.id,
        created_by=p.id,
    )
    session.add(sub)
    await session.flush()
    users = await engine.holders_of_role(session, "ap_accountant")
    await notifications.notify(
        session,
        users,
        kind="vendor_submission",
        title=f"Invoice vendor masuk lewat portal: {invoice_no} ({po.number})",
        body=f"{p.user.vendor_code} · Rp {int(amount):,}".replace(",", "."),
        link="/portal",
    )
    await audit.record(
        session,
        action="portal_upload",
        entity_type=SUB_DOC,
        entity_id=sub.id,
        actor_id=p.id,
        after={"po": po.number, "invoice_no": sub.invoice_no, "amount": amount},
    )
    await session.commit()
    return {"id": str(sub.id), "status": sub.status}


@router.get("/vendor/invoices")
async def vendor_invoices(p: VendorUser, session: Session) -> dict[str, Any]:
    subs = (
        await session.execute(
            select(VendorSubmission)
            .where(VendorSubmission.vendor_code == p.user.vendor_code)
            .order_by(VendorSubmission.created_at.desc())
        )
    ).scalars()
    vis = list(
        (
            await session.execute(
                select(VendorInvoice)
                .where(
                    VendorInvoice.vendor_code == p.user.vendor_code,
                    VendorInvoice.status != "cancelled",
                )
                .order_by(VendorInvoice.invoice_date.desc())
            )
        ).scalars()
    )
    paid_on: dict[uuid.UUID, str] = {}
    if vis:
        for vid, released in (
            await session.execute(
                select(PaymentRunItem.vendor_invoice_id, PaymentRun.released_at)
                .join(PaymentRun, PaymentRun.id == PaymentRunItem.run_id)
                .where(
                    PaymentRunItem.vendor_invoice_id.in_([v.id for v in vis]),
                    PaymentRun.status == "released",
                )
            )
        ).tuples():
            if vid and released:
                paid_on[vid] = released.date().isoformat()
    labels = {
        "draft": "Diverifikasi",
        "exception": "Perlu klarifikasi",
        "approved": "Disetujui, menunggu pembayaran",
        "paid": "Lunas",
    }
    return {
        "submissions": [
            {
                "id": str(s.id),
                "po_number": s.po_number,
                "invoice_no": s.invoice_no,
                "amount": _m(s.amount),
                "status": s.status,
                "reject_reason": s.reject_reason,
            }
            for s in subs
        ],
        "invoices": [
            {
                "number": v.number,
                "invoice_no": v.invoice_no,
                "invoice_date": v.invoice_date.isoformat(),
                "due_date": v.due_date.isoformat() if v.due_date else None,
                "payable": _m(v.payable),
                "paid": _m(v.paid_amount),
                "outstanding": _m(ap.outstanding(v)),
                "status": labels.get(v.status, v.status),
                "paid_on": paid_on.get(v.id),
            }
            for v in vis
        ],
    }


# ---------------------------------------------------------------- AP and admin side


@router.get("/submissions")
async def submissions(
    _: Annotated[Principal, Depends(require("finance", "view"))],
    session: Session,
    status: str | None = "submitted",
) -> list[dict[str, Any]]:
    stmt = select(VendorSubmission).order_by(VendorSubmission.created_at)
    if status:
        stmt = stmt.where(VendorSubmission.status == status)
    return [
        {
            "id": str(s.id),
            "vendor_code": s.vendor_code,
            "po_number": s.po_number,
            "invoice_no": s.invoice_no,
            "invoice_date": s.invoice_date.isoformat(),
            "tax_invoice_no": s.tax_invoice_no,
            "amount": _m(s.amount),
            "attachment_id": str(s.attachment_id),
            "status": s.status,
        }
        for s in (await session.execute(stmt)).scalars()
    ]


class DecideIn(BaseModel):
    vendor_invoice_number: str | None = Field(default=None, max_length=20)
    reject_reason: str | None = Field(default=None, max_length=500)


@router.post("/submissions/{sid}/decide")
async def decide(
    sid: uuid.UUID,
    body: DecideIn,
    actor: Annotated[Principal, Depends(require("finance", "create"))],
    session: Session,
) -> dict[str, Any]:
    """AP links the vendor invoice it registered, or rejects with a reason the vendor sees."""
    s = await session.get(VendorSubmission, sid, with_for_update=True)
    if s is None:
        raise NotFoundError("NOT_FOUND", "Kiriman tidak ditemukan.")
    if s.status != "submitted":
        raise ConflictError("ALREADY_DECIDED", "Kiriman sudah diproses.")
    if body.vendor_invoice_number:
        vi = (
            await session.execute(
                select(VendorInvoice).where(VendorInvoice.number == body.vendor_invoice_number)
            )
        ).scalar_one_or_none()
        if vi is None or vi.vendor_code != s.vendor_code:
            raise AppError(
                "VI_INVALID", "Invoice vendor tidak ditemukan untuk vendor ini.", status_code=422
            )
        s.status, s.vendor_invoice_id = "registered", vi.id
    elif body.reject_reason and len(body.reject_reason.strip()) >= 5:
        s.status, s.reject_reason = "rejected", body.reject_reason.strip()
    else:
        raise AppError(
            "DECISION_REQUIRED",
            "Tautkan invoice vendor atau tulis alasan penolakan.",
            status_code=422,
        )
    await audit.record(
        session,
        action="decide",
        entity_type=SUB_DOC,
        entity_id=s.id,
        actor_id=actor.id,
        after={"status": s.status, "reason": s.reject_reason},
    )
    await session.commit()
    return {"id": str(s.id), "status": s.status}


class LinkIn(BaseModel):
    client_code: str | None = Field(default=None, max_length=20)
    vendor_code: str | None = Field(default=None, max_length=20)


@router.put("/links/{user_id}")
async def link_user(
    user_id: uuid.UUID,
    body: LinkIn,
    actor: Annotated[Principal, Depends(require("users", "edit"))],
    session: Session,
) -> dict[str, Any]:
    u = await session.get(User, user_id, with_for_update=True)
    if u is None:
        raise NotFoundError("NOT_FOUND", "Pengguna tidak ditemukan.")
    if body.client_code and await by_code(session, Client, body.client_code) is None:
        raise AppError("CLIENT_INVALID", "Klien tidak ditemukan.", status_code=422)
    if body.vendor_code and await by_code(session, Vendor, body.vendor_code) is None:
        raise AppError("VENDOR_INVALID", "Vendor tidak ditemukan.", status_code=422)
    before = {"client_code": u.client_code, "vendor_code": u.vendor_code}
    u.client_code, u.vendor_code = body.client_code or None, body.vendor_code or None
    await audit.record(
        session,
        action="update",
        entity_type="user",
        entity_id=u.id,
        actor_id=actor.id,
        before=before,
        after=body.model_dump(),
    )
    await session.commit()
    return {"id": str(u.id), **body.model_dump()}
