"""Finance API (04d): vendor invoices with 3-way match, payables, AP aging, vendor statement."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal, require
from app.core import access
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.core.pagination import PageParams, page_params
from app.finance import ap_service as ap
from app.finance.models import JournalEntry, VendorCreditNote, VendorInvoice
from app.inventory import gr_service
from app.master.models import Vendor
from app.procurement import po_service
from app.procurement.models import PurchaseOrder
from app.project.models import Project
from app.services import ledger
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta

router = APIRouter(prefix="/finance", tags=["finance"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("finance", "view"))]
Creator = Annotated[Principal, Depends(require("finance", "create"))]
Editor = Annotated[Principal, Depends(require("finance", "edit"))]
Submitter = Annotated[Principal, Depends(require("finance", "submit"))]
Exporter = Annotated[Principal, Depends(require("finance", "export"))]
Paging = Annotated[PageParams, Depends(page_params)]


def _m(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


def _q(v: Decimal) -> str:
    return format(v.normalize(), "f") if v else "0"


async def _access(session: AsyncSession, principal: Principal, eid: str, mode: access.Mode) -> bool:
    return principal.can("finance", "view" if mode == "read" else "edit")


access.register(ap.DOC, _access)


class LineBody(BaseModel):
    seq: int = Field(ge=1)
    qty: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=0)


class InvoiceBody(BaseModel):
    invoice_no: str = Field(min_length=1, max_length=60)
    tax_invoice_no: str | None = Field(default=None, max_length=30)
    invoice_date: date
    kind: str = Field(pattern="^(goods|service)$")
    dpp: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    ppn: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    term_days: int | None = Field(default=None, ge=0, le=365)
    note: str | None = Field(default=None, max_length=2000)
    lines: list[LineBody] = Field(min_length=1)

    def header(self) -> ap.Header:
        return ap.Header(
            invoice_no=self.invoice_no,
            tax_invoice_no=self.tax_invoice_no,
            invoice_date=self.invoice_date,
            kind=self.kind,
            dpp=self.dpp,
            ppn=self.ppn,
            term_days=self.term_days,
            note=self.note,
        )

    def line_list(self) -> list[ap.LineIn]:
        return [ap.LineIn(x.seq, x.qty, x.unit_price) for x in self.lines]


class CreateBody(InvoiceBody):
    po_id: uuid.UUID


class CreditNoteBody(BaseModel):
    credit_note_no: str = Field(min_length=1, max_length=60)
    note_date: date
    dpp: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    ppn: Decimal = Field(ge=0, max_digits=18, decimal_places=0)
    reason: str = Field(min_length=5, max_length=500)
    lines: list[LineBody] = Field(min_length=1)


class CancelBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


async def _journal(session: AsyncSession, jid: uuid.UUID | None) -> dict[str, Any] | None:
    if jid is None:
        return None
    entry = await session.get(JournalEntry, jid)
    assert entry is not None
    return {
        "number": entry.number,
        "entry_date": entry.entry_date.isoformat(),
        "total": _m(entry.total),
        "lines": [
            {
                "account_code": x.account_code,
                "debit": _m(x.debit),
                "credit": _m(x.credit),
                "cost_element_code": x.cost_element_code,
                "partner_code": x.partner_code,
            }
            for x in await ledger.lines_of(session, entry.id)
        ],
    }


async def _get(session: AsyncSession, vid: uuid.UUID, lock: bool = False) -> VendorInvoice:
    vi = await session.get(VendorInvoice, vid, with_for_update=lock)
    if vi is None:
        raise NotFoundError("NOT_FOUND", "Invoice vendor tidak ditemukan.")
    return vi


async def _detail(session: AsyncSession, principal: Principal, vi: VendorInvoice) -> dict[str, Any]:
    po = await session.get(PurchaseOrder, vi.po_id)
    assert po is not None
    project = await session.get(Project, po.project_id)
    vendor = (
        await session.execute(select(Vendor).where(Vendor.code == vi.vendor_code))
    ).scalar_one()
    notes = (
        await session.execute(
            select(VendorCreditNote)
            .where(VendorCreditNote.invoice_id == vi.id)
            .order_by(VendorCreditNote.created_at)
        )
    ).scalars()
    editable = vi.status in ap.EDITABLE and principal.can("finance", "edit")
    return {
        "id": str(vi.id),
        "number": vi.number,
        "status": vi.status,
        "status_label": ap.STATUS_LABELS.get(vi.status, vi.status),
        "vendor_code": vi.vendor_code,
        "vendor_name": vendor.name,
        "vendor_npwp": vendor.npwp,
        "po_id": str(po.id),
        "po_number": po.number,
        "project_number": project.number if project else None,
        "invoice_no": vi.invoice_no,
        "tax_invoice_no": vi.tax_invoice_no,
        "invoice_date": vi.invoice_date.isoformat(),
        "kind": vi.kind,
        "term_days": vi.term_days,
        "due_date": vi.due_date.isoformat() if vi.due_date else None,
        "dpp": _m(vi.dpp),
        "ppn": _m(vi.ppn),
        "pph23_pct": str(vi.pph23_pct.normalize()),
        "pph23": _m(vi.pph23),
        "payable": _m(vi.payable),
        "paid_amount": _m(vi.paid_amount),
        "outstanding": _m(ap.outstanding(vi)),
        "note": vi.note,
        "exception_reason": vi.exception_reason,
        "match_result": vi.match_result,
        "journal": await _journal(session, vi.journal_id),
        "credit_notes": [
            {
                "credit_note_no": c.credit_note_no,
                "note_date": c.note_date.isoformat(),
                "dpp": _m(c.dpp),
                "ppn": _m(c.ppn),
                "reason": c.reason,
            }
            for c in notes
        ],
        "can_edit": editable,
        "can_match": vi.status == "draft" and principal.can("finance", "submit"),
        "can_credit_note": vi.status == "exception" and principal.can("finance", "edit"),
        "lines": [
            {
                "seq": x.po_line_seq,
                "description": x.description,
                "qty": _q(x.qty),
                "unit_price": _m(x.unit_price),
                "amount": _m(x.amount),
            }
            for x in await ap.lines_of(session, vi.id)
        ],
    }


def _query(status: str | None, vendor: str | None, q: str | None) -> Select[Any]:
    stmt = (
        select(VendorInvoice, PurchaseOrder.number, Vendor.name)
        .join(PurchaseOrder, PurchaseOrder.id == VendorInvoice.po_id)
        .join(Vendor, Vendor.code == VendorInvoice.vendor_code)
    )
    if status:
        stmt = stmt.where(VendorInvoice.status == status)
    if vendor:
        stmt = stmt.where(VendorInvoice.vendor_code == vendor)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                VendorInvoice.number.ilike(like),
                VendorInvoice.invoice_no.ilike(like),
                VendorInvoice.tax_invoice_no.ilike(like),
                PurchaseOrder.number.ilike(like),
                Vendor.name.ilike(like),
            )
        )
    return stmt


def _row(vi: VendorInvoice, po_number: str, vendor_name: str) -> dict[str, Any]:
    return {
        "id": str(vi.id),
        "number": vi.number,
        "status": vi.status,
        "status_label": ap.STATUS_LABELS.get(vi.status, vi.status),
        "vendor_code": vi.vendor_code,
        "vendor_name": vendor_name,
        "po_number": po_number,
        "invoice_no": vi.invoice_no,
        "invoice_date": vi.invoice_date.isoformat(),
        "due_date": vi.due_date.isoformat() if vi.due_date else None,
        "dpp": _m(vi.dpp),
        "payable": _m(vi.payable),
        "outstanding": _m(ap.outstanding(vi)),
    }


@router.get("/vendor-invoices")
async def list_invoices(
    _: Viewer,
    session: Session,
    paging: Paging,
    status: str | None = None,
    vendor: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    base = _query(None, vendor, q).subquery()
    counts = dict.fromkeys(ap.STATUS_LABELS, 0)
    counts.update(
        dict(
            (await session.execute(select(base.c.status, func.count()).group_by(base.c.status)))
            .tuples()
            .all()
        )
    )
    stmt = _query(status, vendor, q)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(VendorInvoice.created_at.desc())
            .offset(paging.offset)
            .limit(paging.page_size)
        )
    ).tuples()
    return {
        "items": [_row(*r) for r in rows],
        "total": total,
        "counts": counts,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/vendor-invoices/export")
async def export_invoices(
    _: Exporter, session: Session, status: str | None = None, q: str | None = None
) -> StreamingResponse:
    rows = [
        _row(*r)
        for r in (
            await session.execute(_query(status, None, q).order_by(VendorInvoice.number))
        ).tuples()
    ]
    columns = [
        Column("Nomor", "number", width=14),
        Column("Vendor", "vendor_name", width=28),
        Column("No. invoice", "invoice_no", width=18),
        Column("PO", "po_number", width=14),
        Column("Tanggal", "invoice", "date"),
        Column("Jatuh tempo", "due", "date"),
        Column("DPP", "dpp", "idr"),
        Column("Hutang", "payable", "idr"),
        Column("Sisa", "outstanding", "idr"),
        Column("Status", "status_label", width=24),
    ]
    return xlsx_response(
        f"tagihan-vendor-{today_jakarta():%Y%m%d}.xlsx",
        "Tagihan vendor",
        columns,
        (
            {
                **r,
                "invoice": date.fromisoformat(r["invoice_date"]),
                "due": date.fromisoformat(r["due_date"]) if r["due_date"] else None,
            }
            for r in rows
        ),
    )


@router.get("/vendor-invoices/po-options")
async def po_options(_: Creator, session: Session, q: str | None = None) -> list[dict[str, Any]]:
    """Issued/closed POs with something received (GR posted)."""
    from app.inventory.models import GoodsReceipt

    stmt = (
        select(PurchaseOrder, Vendor.name)
        .join(Vendor, Vendor.code == PurchaseOrder.vendor_code)
        .where(
            PurchaseOrder.status.in_(("issued", "closed")),
            PurchaseOrder.id.in_(select(GoodsReceipt.po_id).where(GoodsReceipt.status == "posted")),
        )
        .order_by(PurchaseOrder.number.desc())
        .limit(50)
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(PurchaseOrder.number.ilike(like), Vendor.name.ilike(like)))
    return [
        {"id": str(po.id), "number": po.number, "vendor_name": name, "status": po.status}
        for po, name in (await session.execute(stmt)).tuples()
    ]


@router.get("/vendor-invoices/prefill/{po_id}")
async def prefill(po_id: uuid.UUID, _: Creator, session: Session) -> dict[str, Any]:
    """PO lines with received-but-not-invoiced quantities at the PO price."""
    po = await session.get(PurchaseOrder, po_id)
    if po is None:
        raise NotFoundError("NOT_FOUND", "PO tidak ditemukan.")
    vendor = (
        await session.execute(select(Vendor).where(Vendor.code == po.vendor_code))
    ).scalar_one()
    lines = await po_service.lines_of(session, po.id)
    received = await gr_service.received_by_seq(session, po.id)
    invoiced = await ap.invoiced_by_seq(session, po.id)
    return {
        "po_id": str(po.id),
        "po_number": po.number,
        "vendor_code": vendor.code,
        "vendor_name": vendor.name,
        "vendor_npwp": vendor.npwp,
        "term_days": vendor.payment_term_days,
        "kind": gr_service.kind_of(lines),
        "ppn_pct": str(await po_service.ppn_pct(session)),
        "lines": [
            {
                "seq": x.seq,
                "description": x.description,
                "uom": x.uom,
                "po_qty": _q(x.qty),
                "received": _q(received.get(x.seq, Decimal(0))),
                "invoiced": _q(invoiced.get(x.seq, Decimal(0))),
                "open": _q(received.get(x.seq, Decimal(0)) - invoiced.get(x.seq, Decimal(0))),
                "unit_price": _m(x.unit_price),
            }
            for x in lines
        ],
    }


@router.post("/vendor-invoices", status_code=201)
async def create_invoice(body: CreateBody, actor: Creator, session: Session) -> dict[str, Any]:
    po = await session.get(PurchaseOrder, body.po_id)
    if po is None:
        raise NotFoundError("NOT_FOUND", "PO tidak ditemukan.")
    vi = await ap.create(session, actor, po, body.header(), body.line_list())
    await session.commit()
    return await _detail(session, actor, vi)


@router.get("/vendor-invoices/{vid}")
async def get_invoice(vid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _detail(session, principal, await _get(session, vid))


@router.put("/vendor-invoices/{vid}")
async def correct_invoice(
    vid: uuid.UUID, body: InvoiceBody, actor: Editor, session: Session
) -> dict[str, Any]:
    vi = await _get(session, vid, lock=True)
    await ap.correct(session, actor, vi, body.header(), body.line_list())
    await session.commit()
    return await _detail(session, actor, vi)


@router.post("/vendor-invoices/{vid}/match")
async def match_invoice(vid: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    vi = await _get(session, vid, lock=True)
    await ap.match(session, actor, vi)
    await session.commit()
    return await _detail(session, actor, vi)


@router.post("/vendor-invoices/{vid}/credit-note")
async def add_credit_note(
    vid: uuid.UUID, body: CreditNoteBody, actor: Editor, session: Session
) -> dict[str, Any]:
    vi = await _get(session, vid, lock=True)
    await ap.credit_note(
        session,
        actor,
        vi,
        credit_note_no=body.credit_note_no,
        note_date=body.note_date,
        dpp=body.dpp,
        ppn=body.ppn,
        reason=body.reason,
        lines=[ap.LineIn(x.seq, x.qty, x.unit_price) for x in body.lines],
    )
    await session.commit()
    return await _detail(session, actor, vi)


@router.post("/vendor-invoices/{vid}/cancel")
async def cancel_invoice(
    vid: uuid.UUID, body: CancelBody, actor: Editor, session: Session
) -> dict[str, Any]:
    vi = await _get(session, vid, lock=True)
    await ap.cancel(session, actor, vi, body.reason)
    await session.commit()
    return await _detail(session, actor, vi)


@router.get("/payables")
async def list_payables(
    _: Viewer, session: Session, due_by: date | None = None, vendor: str | None = None
) -> list[dict[str, Any]]:
    """Invoices that may enter a payment run (approved, not fully paid)."""
    return [
        {
            "id": str(vi.id),
            "number": vi.number,
            "vendor_code": vi.vendor_code,
            "invoice_no": vi.invoice_no,
            "due_date": vi.due_date.isoformat() if vi.due_date else None,
            "outstanding": _m(ap.outstanding(vi)),
        }
        for vi in await ap.payables(session, due_by=due_by, vendor=vendor)
    ]


@router.get("/ap-aging")
async def ap_aging(_: Viewer, session: Session, as_of: date | None = None) -> dict[str, Any]:
    a = await ap.aging(session, as_of or today_jakarta())

    def money(d: dict[str, Any]) -> dict[str, Any]:
        return {k: (_m(v) if isinstance(v, Decimal) else v) for k, v in d.items()}

    return {
        "as_of": a["as_of"].isoformat(),
        "rows": [money(r) for r in a["rows"]],
        "totals": money(a["totals"]),
    }


@router.get("/ap-aging/export")
async def export_aging(_: Exporter, session: Session) -> StreamingResponse:
    a = await ap.aging(session, today_jakarta())
    columns = [
        Column("Vendor", "vendor_name", width=30),
        Column("Belum jatuh tempo", "not_due", "idr"),
        Column("1-30 hari", "d1_30", "idr"),
        Column("31-60 hari", "d31_60", "idr"),
        Column("61-90 hari", "d61_90", "idr"),
        Column("> 90 hari", "d90_plus", "idr"),
        Column("Total", "total", "idr"),
    ]
    return xlsx_response(
        f"umur-hutang-{today_jakarta():%Y%m%d}.xlsx", "Umur hutang", columns, a["rows"]
    )


@router.get("/vendor-statement")
async def vendor_statement(
    _: Viewer, session: Session, vendor: str, date_from: date, date_to: date
) -> dict[str, Any]:
    v = (await session.execute(select(Vendor).where(Vendor.code == vendor))).scalar_one_or_none()
    if v is None:
        raise NotFoundError("NOT_FOUND", "Vendor tidak ditemukan.")
    st = await ap.statement(session, vendor, date_from, date_to)
    return {
        "vendor_code": v.code,
        "vendor_name": v.name,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "opening": _m(st["opening"]),
        "closing": _m(st["closing"]),
        "rows": [
            {
                **r,
                "date": r["date"].isoformat(),
                "debit": _m(r["debit"]),
                "credit": _m(r["credit"]),
                "balance": _m(r["balance"]),
            }
            for r in st["rows"]
        ],
    }


@router.get("/vendors")
async def vendors(_: Viewer, session: Session) -> list[dict[str, str]]:
    rows = await session.execute(select(Vendor.code, Vendor.name).order_by(Vendor.name))
    return [{"code": c, "name": n} for c, n in rows.tuples()]
