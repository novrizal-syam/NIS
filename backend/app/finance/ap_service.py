"""Vendor invoice and 3-way match (PROCESS.md · Vendor invoice; ACCOUNTING.md).

The AP Accountant records the vendor's invoice against a PO (invoice and tax-invoice numbers,
date, DPP, PPN, type, lines, attachment). Matching compares, per PO line:
  invoice qty <= received (posted GRs) - already invoiced, and invoice price = PO price,
and the invoice DPP with the sum of its lines, all within `ap.match_tolerance_pct` (default 0).

- match -> "approved" (payable): due = invoice date + term; journal
  Dr 2120 (GR value) [+/- price variance to the cost element's expense], Dr 1420 (PPN)
  / Cr 2110 (DPP + PPN - PPh 23), Cr 2230 (PPh 23).
- no match -> "exception": not payable, nothing posted; resolved by a correction (data-entry
  error) or a vendor credit note, then matched again.

Taxes: PPN = 12% x 11/12 DPP (setting `tax.ppn_effective_pct`, default 11) unless the faktur
says otherwise; PPh 23 = `tax.pph23_pct` (default 2%) of DPP on services/rentals, doubled when
the vendor has no NPWP (UU PPh art. 23 (1a)); none on goods.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.dms.models import Attachment
from app.finance.models import (
    JournalEntry,
    JournalLine,
    VendorCreditNote,
    VendorInvoice,
    VendorInvoiceLine,
)
from app.inventory import gr_service
from app.master.models import Vendor
from app.notifications import service as notifications
from app.procurement import po_service
from app.procurement.models import PurchaseOrder
from app.services import audit, ledger, numbering
from app.services.audit import AuditAction
from app.setup import service as settings_store

DOC = "vendor_invoice"
TOLERANCE_KEY = "ap.match_tolerance_pct"
PPH23_KEY = "tax.pph23_pct"
AP = "2110"
PPN_IN = "1420"
PPH23_PAYABLE = "2230"
EDITABLE = ("draft", "exception")
ZERO = Decimal(0)
STATUS_LABELS = {
    "draft": "Draf",
    "approved": "Disetujui untuk dibayar",
    "exception": "Selisih pencocokan",
    "paid": "Lunas",
    "cancelled": "Dibatalkan",
}


def rp(v: Decimal) -> Decimal:
    return v.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class LineIn:
    seq: int
    qty: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class Header:
    invoice_no: str
    tax_invoice_no: str | None
    invoice_date: date
    kind: str
    dpp: Decimal
    ppn: Decimal | None  # None = computed (12% x 11/12 DPP)
    term_days: int | None
    note: str | None


async def tolerance(session: AsyncSession) -> Decimal:
    return Decimal(str(await settings_store.get(session, TOLERANCE_KEY, 0)))


async def taxes(
    session: AsyncSession, vendor: Vendor, kind: str, dpp: Decimal, ppn: Decimal | None
) -> tuple[Decimal, Decimal, Decimal]:
    """(PPN, PPh 23 rate, PPh 23)."""
    if ppn is None:
        ppn = rp(dpp * await po_service.ppn_pct(session) / 100)
    rate = ZERO
    if kind == "service":
        rate = Decimal(str(await settings_store.get(session, PPH23_KEY, 2)))
        if not (vendor.npwp or "").strip():
            rate *= 2
    return ppn, rate, rp(dpp * rate / 100)


async def lines_of(session: AsyncSession, invoice_id: uuid.UUID) -> list[VendorInvoiceLine]:
    rows = await session.execute(
        select(VendorInvoiceLine)
        .where(VendorInvoiceLine.invoice_id == invoice_id)
        .order_by(VendorInvoiceLine.po_line_seq)
    )
    return list(rows.scalars())


async def invoiced_by_seq(
    session: AsyncSession, po_id: uuid.UUID, exclude: uuid.UUID | None = None
) -> dict[int, Decimal]:
    """Quantity already on approved (or paid) invoices per PO line."""
    stmt = (
        select(VendorInvoiceLine.po_line_seq, func.sum(VendorInvoiceLine.qty))
        .join(VendorInvoice, VendorInvoice.id == VendorInvoiceLine.invoice_id)
        .where(VendorInvoice.po_id == po_id, VendorInvoice.status.in_(("approved", "paid")))
        .group_by(VendorInvoiceLine.po_line_seq)
    )
    if exclude is not None:
        stmt = stmt.where(VendorInvoice.id != exclude)
    return {seq: Decimal(q) for seq, q in (await session.execute(stmt)).tuples()}


async def _vendor(session: AsyncSession, code: str) -> Vendor:
    return (await session.execute(select(Vendor).where(Vendor.code == code))).scalar_one()


async def _check_duplicate(
    session: AsyncSession, vendor_code: str, invoice_no: str, exclude: uuid.UUID | None
) -> None:
    stmt = select(VendorInvoice.number).where(
        VendorInvoice.vendor_code == vendor_code,
        func.upper(VendorInvoice.invoice_no) == invoice_no.strip().upper(),
        VendorInvoice.status != "cancelled",
    )
    if exclude is not None:
        stmt = stmt.where(VendorInvoice.id != exclude)
    if (other := (await session.execute(stmt)).scalars().first()) is not None:
        raise ConflictError(
            "DUPLICATE_INVOICE", f"Invoice {invoice_no} dari vendor ini sudah dicatat ({other})."
        )


async def _apply(
    session: AsyncSession,
    vi: VendorInvoice,
    po: PurchaseOrder,
    h: Header,
    lines: list[LineIn],
) -> None:
    if h.kind not in ("goods", "service"):
        raise AppError("KIND_INVALID", "Jenis tagihan: barang atau jasa/sewa.", status_code=422)
    if h.invoice_date > numbering.today_jakarta():
        raise AppError(
            "DATE_IN_FUTURE", "Tanggal invoice tidak boleh di masa depan.", status_code=422
        )
    if h.dpp <= 0 or (h.ppn is not None and h.ppn < 0):
        raise AppError("AMOUNT_INVALID", "DPP harus > 0 dan PPN tidak negatif.", status_code=422)
    if not lines:
        raise AppError("LINES_REQUIRED", "Isi minimal satu baris tagihan.", status_code=422)
    if len({x.seq for x in lines}) != len(lines):
        raise AppError(
            "DUPLICATE_LINE", "Setiap baris PO hanya sekali per invoice.", status_code=422
        )
    await _check_duplicate(session, po.vendor_code, h.invoice_no, vi.id)
    po_lines = {x.seq: x for x in await po_service.lines_of(session, po.id)}
    vendor = await _vendor(session, po.vendor_code)
    ppn, rate, pph = await taxes(session, vendor, h.kind, h.dpp, h.ppn)
    vi.invoice_no = h.invoice_no.strip()
    vi.tax_invoice_no = (h.tax_invoice_no or "").strip() or None
    vi.invoice_date = h.invoice_date
    vi.kind = h.kind
    vi.term_days = h.term_days if h.term_days is not None else vendor.payment_term_days
    vi.dpp, vi.ppn, vi.pph23_pct, vi.pph23 = h.dpp, ppn, rate, pph
    vi.payable = h.dpp + ppn - pph
    vi.note = h.note
    await session.execute(delete(VendorInvoiceLine).where(VendorInvoiceLine.invoice_id == vi.id))
    for x in sorted(lines, key=lambda x: x.seq):
        pl = po_lines.get(x.seq)
        if pl is None:
            raise AppError("PO_LINE_INVALID", f"Baris PO {x.seq} tidak ada.", status_code=422)
        if x.qty <= 0 or x.unit_price < 0:
            raise AppError(
                "LINE_INVALID", "Kuantitas harus > 0 dan harga tidak negatif.", status_code=422
            )
        session.add(
            VendorInvoiceLine(
                invoice_id=vi.id,
                po_line_seq=x.seq,
                description=pl.description,
                qty=x.qty,
                unit_price=x.unit_price,
                amount=rp(x.qty * x.unit_price),
            )
        )
    await session.flush()


async def create(
    session: AsyncSession, actor: Principal, po: PurchaseOrder, h: Header, lines: list[LineIn]
) -> VendorInvoice:
    if po.status not in ("issued", "closed"):
        raise ConflictError("PO_NOT_OPEN", f"{po.number} belum terbit; tidak dapat ditagih.")
    await _check_duplicate(session, po.vendor_code, h.invoice_no, None)
    vi = VendorInvoice(
        number=await numbering.next(session, "VI"),
        vendor_code=po.vendor_code,
        po_id=po.id,
        invoice_no=h.invoice_no.strip(),
        invoice_date=h.invoice_date,
        kind=h.kind,
        term_days=0,
        dpp=ZERO,
        ppn=ZERO,
        payable=ZERO,
        status="draft",
        created_by=actor.id,
        is_demo=po.is_demo,
    )
    session.add(vi)
    await session.flush()
    await _apply(session, vi, po, h, lines)
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=vi.id,
        actor_id=actor.id,
        after=snapshot(vi),
    )
    return vi


async def correct(
    session: AsyncSession, actor: Principal, vi: VendorInvoice, h: Header, lines: list[LineIn]
) -> VendorInvoice:
    """Fix a data-entry error (draft or exception); back to draft for a new match."""
    if vi.status not in EDITABLE:
        raise ConflictError("NOT_EDITABLE", f"{vi.number} tidak dapat diubah lagi.")
    before = snapshot(vi)
    po = await session.get(PurchaseOrder, vi.po_id)
    assert po is not None
    await _apply(session, vi, po, h, lines)
    vi.status, vi.exception_reason = "draft", None
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=vi.id,
        actor_id=actor.id,
        before=before,
        after=snapshot(vi),
        note="Koreksi",
    )
    return vi


async def credit_note(
    session: AsyncSession,
    actor: Principal,
    vi: VendorInvoice,
    *,
    credit_note_no: str,
    note_date: date,
    dpp: Decimal,
    ppn: Decimal,
    reason: str,
    lines: list[LineIn],
) -> VendorCreditNote:
    """Vendor credit note on an exception: reduces DPP/PPN, lines become the corrected ones."""
    if vi.status != "exception":
        raise ConflictError(
            "NOT_EXCEPTION", "Nota kredit hanya untuk invoice dengan selisih pencocokan."
        )
    if dpp <= 0 or ppn < 0 or dpp >= vi.dpp or ppn > vi.ppn:
        raise AppError(
            "CREDIT_NOTE_INVALID",
            "Nilai nota kredit harus > 0 dan lebih kecil dari nilai invoice.",
            status_code=422,
        )
    if len(reason.strip()) < 5:
        raise AppError("REASON_REQUIRED", "Tulis alasan nota kredit.", status_code=422)
    before = snapshot(vi)
    cn = VendorCreditNote(
        invoice_id=vi.id,
        credit_note_no=credit_note_no.strip(),
        note_date=note_date,
        dpp=dpp,
        ppn=ppn,
        reason=reason.strip(),
        created_by=actor.id,
        is_demo=vi.is_demo,
    )
    session.add(cn)
    po = await session.get(PurchaseOrder, vi.po_id)
    assert po is not None
    h = Header(
        invoice_no=vi.invoice_no,
        tax_invoice_no=vi.tax_invoice_no,
        invoice_date=vi.invoice_date,
        kind=vi.kind,
        dpp=vi.dpp - dpp,
        ppn=vi.ppn - ppn,
        term_days=vi.term_days,
        note=vi.note,
    )
    await _apply(session, vi, po, h, lines)
    vi.status, vi.exception_reason = "draft", None
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=vi.id,
        actor_id=actor.id,
        before=before,
        after={**snapshot(vi), "credit_note": cn.credit_note_no},
        note=reason.strip(),
    )
    return cn


async def _attachments(session: AsyncSession, vi: VendorInvoice) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Attachment)
                .where(
                    Attachment.entity_type == DOC,
                    Attachment.entity_id == str(vi.id),
                    Attachment.archived_at.is_(None),
                )
            )
        ).scalar_one()
    )


def _within(actual: Decimal, expected: Decimal, tol: Decimal) -> bool:
    return abs(actual - expected) <= abs(expected) * tol / 100


async def three_way(
    session: AsyncSession, vi: VendorInvoice, po: PurchaseOrder
) -> tuple[list[dict[str, Any]], list[str]]:
    """Per-line comparison and the list of problems (empty = match)."""
    tol = await tolerance(session)
    po_lines = {x.seq: x for x in await po_service.lines_of(session, po.id)}
    received = await gr_service.received_by_seq(session, po.id)
    invoiced = await invoiced_by_seq(session, po.id, exclude=vi.id)
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for x in await lines_of(session, vi.id):
        pl = po_lines[x.po_line_seq]
        got = received.get(x.po_line_seq, ZERO)
        before = invoiced.get(x.po_line_seq, ZERO)
        open_qty = got - before
        qty_ok = x.qty <= open_qty or (open_qty > 0 and _within(x.qty, open_qty, tol))
        price_ok = _within(x.unit_price, pl.unit_price, tol)
        if not qty_ok:
            problems.append(
                f"Baris {x.po_line_seq} ({pl.description}): ditagih {x.qty.normalize():f}, "
                f"diterima belum ditagih {open_qty.normalize():f} {pl.uom}."
            )
        if not price_ok:
            problems.append(
                f"Baris {x.po_line_seq} ({pl.description}): harga {x.unit_price} ≠ harga PO "
                f"{pl.unit_price}."
            )
        rows.append(
            {
                "seq": x.po_line_seq,
                "description": pl.description,
                "uom": pl.uom,
                "po_qty": pl.qty,
                "received": got,
                "invoiced_before": before,
                "qty": x.qty,
                "po_price": pl.unit_price,
                "price": x.unit_price,
                "qty_ok": qty_ok,
                "price_ok": price_ok,
            }
        )
    lines_total = sum((rp(r["qty"] * r["price"]) for r in rows), ZERO)
    if not _within(vi.dpp, lines_total, tol):
        problems.append(f"DPP {vi.dpp} ≠ jumlah baris {lines_total}.")
    return rows, problems


async def match(session: AsyncSession, actor: Principal, vi: VendorInvoice) -> VendorInvoice:
    if vi.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{vi.number} tidak dalam status draf.")
    if await _attachments(session, vi) == 0:
        raise AppError(
            "ATTACHMENT_REQUIRED",
            "Lampirkan scan invoice dan faktur pajak sebelum pencocokan.",
            status_code=422,
        )
    # Lock the PO: two invoices on the same lines cannot both pass.
    po = await session.get(PurchaseOrder, vi.po_id, with_for_update=True)
    assert po is not None
    rows, problems = await three_way(session, vi, po)
    vi.match_result = [
        {k: (format(v, "f") if isinstance(v, Decimal) else v) for k, v in r.items()} for r in rows
    ]
    if problems:
        vi.status, vi.exception_reason = "exception", " ".join(problems)[:1000]
        await session.flush()
        if po.created_by:
            await notifications.notify(
                session,
                [po.created_by],
                kind="vendor_invoice_exception",
                title=f"Selisih pencocokan {vi.number} ({po.number})",
                body=vi.exception_reason,
                link=f"/keuangan/tagihan-vendor/{vi.id}",
            )
    else:
        await _post(session, actor, vi, po, rows)
    await audit.record(
        session,
        action="match",
        entity_type=DOC,
        entity_id=vi.id,
        actor_id=actor.id,
        after={"status": vi.status, "problems": problems},
    )
    return vi


async def _post(
    session: AsyncSession,
    actor: Principal,
    vi: VendorInvoice,
    po: PurchaseOrder,
    rows: list[dict[str, Any]],
) -> None:
    gr_value = sum((rp(r["qty"] * r["po_price"]) for r in rows), ZERO)
    variance = vi.dpp - gr_value
    entry = await ledger.post_event(
        session,
        "vendor_invoice",
        {
            "grir": gr_value,
            "price_variance": variance,
            "ppn": vi.ppn,
            "payable": vi.payable,
            "pph23": vi.pph23,
        },
        entry_date=vi.invoice_date,
        description=f"{vi.number} tagihan {vi.vendor_code} {vi.invoice_no}",
        source_type=DOC,
        source_id=vi.id,
        source_number=vi.number,
        by=actor.id,
        dims=ledger.Dims(
            project_id=po.project_id,
            wbs_id=po.wbs_id,
            cost_element=po.cost_element_code,
            partner_type="vendor",
            partner_code=vi.vendor_code,
        ),
        memo=f"{vi.invoice_no} / {po.number}",
        is_demo=vi.is_demo,
    )
    vi.status, vi.exception_reason = "approved", None
    vi.approved_at, vi.journal_id = _now(), entry.id
    vi.due_date = vi.invoice_date + timedelta(days=vi.term_days)
    await session.flush()


async def cancel(session: AsyncSession, actor: Principal, vi: VendorInvoice, reason: str) -> None:
    if vi.status not in EDITABLE:
        raise ConflictError(
            "NOT_CANCELLABLE", f"{vi.number} sudah diposting; koreksi dengan nota kredit."
        )
    if len(reason.strip()) < 5:
        raise AppError("REASON_REQUIRED", "Tulis alasan pembatalan.", status_code=422)
    before = vi.status
    vi.status = "cancelled"
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type=DOC,
        entity_id=vi.id,
        actor_id=actor.id,
        before={"status": before},
        after={"status": "cancelled"},
        note=reason.strip(),
    )


# ---------------------------------------------------------------- payables, aging, statement


def outstanding(vi: VendorInvoice) -> Decimal:
    return vi.payable - vi.paid_amount


def ensure_payable(vi: VendorInvoice) -> None:
    """Gate for payment runs (07b): only approved invoices with an open balance."""
    if vi.status != "approved":
        raise ConflictError(
            "NOT_PAYABLE",
            f"{vi.number} berstatus {STATUS_LABELS.get(vi.status, vi.status)}; "
            "hanya invoice yang disetujui untuk dibayar yang dapat masuk payment run.",
        )
    if outstanding(vi) <= 0:
        raise ConflictError("ALREADY_PAID", f"{vi.number} sudah lunas.")


async def payables(
    session: AsyncSession, *, due_by: date | None = None, vendor: str | None = None
) -> list[VendorInvoice]:
    stmt = select(VendorInvoice).where(
        VendorInvoice.status == "approved", VendorInvoice.payable > VendorInvoice.paid_amount
    )
    if due_by is not None:
        stmt = stmt.where(VendorInvoice.due_date <= due_by)
    if vendor:
        stmt = stmt.where(VendorInvoice.vendor_code == vendor)
    return list((await session.execute(stmt.order_by(VendorInvoice.due_date))).scalars())


BUCKETS = ("not_due", "d1_30", "d31_60", "d61_90", "d90_plus")


def bucket(due: date, as_of: date) -> str:
    late = (as_of - due).days
    if late <= 0:
        return "not_due"
    if late <= 30:
        return "d1_30"
    if late <= 60:
        return "d31_60"
    if late <= 90:
        return "d61_90"
    return "d90_plus"


async def aging(session: AsyncSession, as_of: date) -> dict[str, Any]:
    per_vendor: dict[str, dict[str, Decimal]] = {}
    totals = dict.fromkeys(BUCKETS, ZERO)
    for vi in await payables(session):
        assert vi.due_date is not None
        b = bucket(vi.due_date, as_of)
        row = per_vendor.setdefault(vi.vendor_code, dict.fromkeys(BUCKETS, ZERO))
        row[b] += outstanding(vi)
        totals[b] += outstanding(vi)
    names = dict(
        (
            await session.execute(
                select(Vendor.code, Vendor.name).where(Vendor.code.in_(per_vendor.keys()))
            )
        )
        .tuples()
        .all()
    )
    return {
        "as_of": as_of,
        "rows": [
            {"vendor_code": c, "vendor_name": names.get(c, c), **b, "total": sum(b.values())}
            for c, b in sorted(per_vendor.items())
        ],
        "totals": {**totals, "total": sum(totals.values())},
    }


async def statement(
    session: AsyncSession, vendor_code: str, date_from: date, date_to: date
) -> dict[str, Any]:
    """Vendor account (2110) from the ledger: invoices credit, payments/credit notes debit."""
    base = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.account_code == AP,
            JournalLine.partner_type == "vendor",
            JournalLine.partner_code == vendor_code,
        )
    )
    opening = (
        await session.execute(
            select(func.coalesce(func.sum(JournalLine.credit - JournalLine.debit), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.account_code == AP,
                JournalLine.partner_type == "vendor",
                JournalLine.partner_code == vendor_code,
                JournalEntry.entry_date < date_from,
            )
        )
    ).scalar_one()
    balance = Decimal(opening)
    rows = []
    for jl, je in (
        await session.execute(
            base.where(JournalEntry.entry_date.between(date_from, date_to)).order_by(
                JournalEntry.entry_date, JournalEntry.number
            )
        )
    ).tuples():
        balance += jl.credit - jl.debit
        rows.append(
            {
                "date": je.entry_date,
                "journal": je.number,
                "document": je.source_number,
                "description": je.description,
                "debit": jl.debit,
                "credit": jl.credit,
                "balance": balance,
            }
        )
    return {"opening": Decimal(opening), "rows": rows, "closing": balance}


def snapshot(vi: VendorInvoice) -> dict[str, Any]:
    return {
        "number": vi.number,
        "invoice_no": vi.invoice_no,
        "tax_invoice_no": vi.tax_invoice_no,
        "invoice_date": vi.invoice_date,
        "kind": vi.kind,
        "dpp": vi.dpp,
        "ppn": vi.ppn,
        "pph23": vi.pph23,
        "payable": vi.payable,
        "status": vi.status,
    }
