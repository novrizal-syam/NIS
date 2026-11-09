"""Customer invoice (prompt 06 · 2; ACCOUNTING.md tax configuration).

Only signed service tickets can be invoiced. Amounts:
  subtotal       = sum of signed ticket values (disputed lines already removed)
  DPP nilai lain = 11/12 x subtotal;  PPN = 12 % x DPP nilai lain  (effective 11 %)
  total          = subtotal + PPN
  PPh 23 (expected, withheld by the client) = 2 % x subtotal;  net cash = total - PPh 23
  bea meterai    = Rp 10.000 when the document exceeds Rp 5.000.000 (e-Meterai)
Faktur issued -> journal Dr 1210 (total) / Cr 1220 (subtotal), Cr 2210 (PPN); tickets invoiced.
"""

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from xml.etree import ElementTree as ET

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.billing import documents
from app.billing.models import CustomerInvoice, InvoiceTicket, ServiceTicket, TicketLine
from app.billing.ticket_service import lines_of
from app.contract.models import Contract
from app.core.errors import AppError, ConflictError
from app.dms import service as dms
from app.dms.models import Attachment
from app.master.models import Client
from app.notifications import service as notifications
from app.operations.models import Dor
from app.services import audit, email, fx, ledger, letterhead, numbering
from app.services.audit import AuditAction
from app.services.money import format_idr
from app.services.storage import Storage
from app.setup import service as settings_store
from app.workflow import engine

DOC = "customer_invoice"
ZERO = Decimal(0)
STATUS_LABELS = {
    "draft": "Draf",
    "faktur_issued": "Faktur terbit",
    "sent": "Terkirim",
    "paid": "Lunas",
    "cancelled": "Dibatalkan",
}
OPEN = ("faktur_issued", "sent")
FAKTUR_RE = re.compile(r"^(\d{17}|\d{3}\.\d{3}-\d{2}\.\d{8})$")
STAMP_THRESHOLD = Decimal(5_000_000)
STAMP_DUTY = Decimal(10_000)


def rp(v: Decimal) -> Decimal:
    return v.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def _now() -> datetime:
    return datetime.now(UTC)


def amounts(subtotal: Decimal, ppn_rate: Decimal, pph23_rate: Decimal) -> dict[str, Decimal]:
    dpp = rp(subtotal * 11 / 12)
    ppn = rp(dpp * ppn_rate / 100)
    total = subtotal + ppn
    pph = rp(subtotal * pph23_rate / 100)
    return {
        "subtotal": subtotal,
        "dpp_other": dpp,
        "ppn": ppn,
        "total": total,
        "pph23_expected": pph,
        "net_cash": total - pph,
        "stamp_duty": STAMP_DUTY if total > STAMP_THRESHOLD else ZERO,
    }


def outstanding(inv: CustomerInvoice) -> Decimal:
    return inv.total - inv.paid_amount - inv.pph23_withheld


async def tickets_of(session: AsyncSession, invoice_id: uuid.UUID) -> list[ServiceTicket]:
    rows = await session.execute(
        select(ServiceTicket)
        .join(InvoiceTicket, InvoiceTicket.ticket_id == ServiceTicket.id)
        .where(InvoiceTicket.invoice_id == invoice_id)
        .order_by(ServiceTicket.number)
    )
    return list(rows.scalars())


async def create(
    session: AsyncSession,
    actor: Principal,
    ticket_ids: list[uuid.UUID],
    invoice_date: date,
    note: str | None,
) -> CustomerInvoice:
    if not ticket_ids:
        raise AppError("TICKETS_REQUIRED", "Pilih minimal satu service ticket.", status_code=422)
    tickets = list(
        (
            await session.execute(
                select(ServiceTicket).where(ServiceTicket.id.in_(ticket_ids)).with_for_update()
            )
        ).scalars()
    )
    if len(tickets) != len(set(ticket_ids)):
        raise AppError(
            "TICKET_INVALID", "Sebagian service ticket tidak ditemukan.", status_code=422
        )
    unsigned = [t.number for t in tickets if t.status != "signed"]
    if unsigned:
        raise AppError(
            "TICKET_NOT_SIGNED",
            "Invoice hanya dari service ticket yang sudah ditandatangani klien: "
            + ", ".join(sorted(unsigned))
            + ".",
            status_code=422,
        )
    taken = await session.execute(
        select(ServiceTicket.number)
        .join(InvoiceTicket, InvoiceTicket.ticket_id == ServiceTicket.id)
        .where(InvoiceTicket.ticket_id.in_(ticket_ids))
    )
    if (n := taken.scalars().first()) is not None:
        raise ConflictError("TICKET_ON_INVOICE", f"{n} sudah ada di invoice lain.")
    contracts = {t.contract_id for t in tickets}
    if len(contracts) != 1:
        raise AppError("MIXED_CONTRACTS", "Satu invoice untuk satu kontrak.", status_code=422)
    contract = await session.get(Contract, contracts.pop())
    assert contract is not None
    subtotal = sum((t.value for t in tickets), ZERO)
    if subtotal <= 0:
        raise AppError(
            "NOTHING_TO_BILL", "Nilai service ticket nol (seluruhnya di-dispute).", status_code=422
        )
    if invoice_date > numbering.today_jakarta():
        raise AppError(
            "DATE_IN_FUTURE", "Tanggal invoice tidak boleh di masa depan.", status_code=422
        )
    ppn_rate = Decimal(str(await settings_store.get(session, "tax.ppn_rate_pct", 12)))
    pph_rate = Decimal(str(await settings_store.get(session, "tax.pph23_pct", 2)))
    currency = contract.currency or "IDR"
    rate = await fx.rate(session, currency, invoice_date)
    total_foreign = None
    if currency != fx.BASE:
        # Ticket values are in the contract currency; the IDR columns use the invoice-date rate.
        dpp_f = fx.cents(subtotal * 11 / 12)
        total_foreign = fx.cents(subtotal + fx.cents(dpp_f * ppn_rate / 100))
        subtotal = fx.to_idr(subtotal, rate)
    a = amounts(subtotal, ppn_rate, pph_rate)
    inv = CustomerInvoice(
        currency=currency,
        fx_rate=rate,
        total_foreign=total_foreign,
        number=await numbering.next(session, "INV", on=invoice_date),
        contract_id=contract.id,
        client_code=contract.client_code,
        status="draft",
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=contract.payment_term_days),
        ppn_rate=ppn_rate,
        pph23_rate=pph_rate,
        note=note,
        created_by=actor.id,
        is_demo=contract.is_demo,
        **a,
    )
    session.add(inv)
    await session.flush()
    for t in tickets:
        session.add(InvoiceTicket(invoice_id=inv.id, ticket_id=t.id))
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=inv.id,
        actor_id=actor.id,
        after={"number": inv.number, "tickets": [t.number for t in tickets], **a},
    )
    return inv


async def cancel_draft(session: AsyncSession, actor: Principal, inv: CustomerInvoice) -> None:
    if inv.status != "draft":
        raise ConflictError(
            "NOT_DRAFT",
            f"{inv.number} sudah berfaktur; koreksi dengan nota retur/pembatalan faktur.",
        )
    await session.execute(delete(InvoiceTicket).where(InvoiceTicket.invoice_id == inv.id))
    inv.status = "cancelled"
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type=DOC,
        entity_id=inv.id,
        actor_id=actor.id,
        after={"status": "cancelled"},
    )


async def issue_faktur(
    session: AsyncSession,
    actor: Principal,
    inv: CustomerInvoice,
    faktur_number: str,
    faktur_date: date,
) -> CustomerInvoice:
    if inv.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{inv.number} sudah berfaktur.")
    fn = faktur_number.strip()
    if not FAKTUR_RE.match(fn):
        raise AppError(
            "FAKTUR_INVALID",
            "Nomor faktur: 17 digit (Coretax) atau format 010.000-26.00000001.",
            status_code=422,
        )
    if faktur_date < inv.invoice_date:
        raise AppError(
            "FAKTUR_DATE", "Tanggal faktur tidak boleh sebelum tanggal invoice.", status_code=422
        )
    clash = await session.execute(
        select(CustomerInvoice.number).where(
            CustomerInvoice.faktur_number == fn, CustomerInvoice.id != inv.id
        )
    )
    if (n := clash.scalar_one_or_none()) is not None:
        raise ConflictError("FAKTUR_USED", f"Nomor faktur sudah dipakai {n}.")
    tickets = await tickets_of(session, inv.id)
    project_id = tickets[0].project_id if tickets else None
    entry = await ledger.post_event(
        session,
        "customer_invoice",
        {"total": inv.total, "subtotal": inv.subtotal, "ppn": inv.ppn},
        entry_date=inv.invoice_date,
        description=f"{inv.number} tagihan {inv.client_code or ''} faktur {fn}",
        source_type=DOC,
        source_id=inv.id,
        source_number=inv.number,
        by=actor.id,
        dims=ledger.Dims(
            project_id=project_id, partner_type="client", partner_code=inv.client_code
        ),
        memo=inv.number,
        is_demo=inv.is_demo,
    )
    inv.faktur_number, inv.faktur_date, inv.journal_id = fn, faktur_date, entry.id
    inv.status = "faktur_issued"
    for t in tickets:
        t.status, t.invoice_id = "invoiced", inv.id
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.POST,
        entity_type=DOC,
        entity_id=inv.id,
        actor_id=actor.id,
        after={"faktur": fn, "journal": entry.number, "total": inv.total},
    )
    return inv


# ---------------------------------------------------------------- Coretax XML


def _npwp(v: str | None) -> str:
    digits = re.sub(r"\D", "", v or "")
    return digits.zfill(16) if len(digits) == 15 else digits


async def coretax_xml(session: AsyncSession, invoices: list[CustomerInvoice]) -> bytes:
    """Coretax e-Faktur bulk import (TaxInvoiceBulk). Code 04 = DPP nilai lain (11/12)."""
    company = {
        **settings_store.DEFAULT_COMPANY,
        **(await settings_store.get(session, settings_store.COMPANY, {}) or {}),
    }
    seller = _npwp(company.get("npwp"))
    root = ET.Element(
        "TaxInvoiceBulk",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": "TaxInvoice.xsd",
        },
    )
    ET.SubElement(root, "TIN").text = seller
    lst = ET.SubElement(root, "ListOfTaxInvoice")
    for inv in invoices:
        if inv.status not in ("faktur_issued", "sent", "paid"):
            raise AppError("NOT_ISSUED", f"{inv.number} belum berfaktur.", status_code=422)
        client = (
            await session.execute(select(Client).where(Client.code == inv.client_code))
        ).scalar_one_or_none()
        buyer = _npwp(client.npwp if client else None)
        ti = ET.SubElement(lst, "TaxInvoice")
        for tag, value in (
            ("TaxInvoiceDate", (inv.faktur_date or inv.invoice_date).isoformat()),
            ("TaxInvoiceOpt", "Normal"),
            ("TrxCode", "04"),
            ("AddInfo", ""),
            ("CustomDoc", ""),
            ("RefDesc", inv.number),
            ("FacilityStamp", ""),
            ("SellerIDTKU", f"{seller}000000"),
            ("BuyerTin", buyer or "0000000000000000"),
            ("BuyerDocument", "TIN"),
            ("BuyerCountry", "IDN"),
            ("BuyerDocumentNumber", "-"),
            ("BuyerName", client.name if client else ""),
            ("BuyerAdress", (client.address if client else "") or "-"),
            ("BuyerEmail", (client.email if client else "") or ""),
            ("BuyerIDTKU", f"{buyer}000000" if buyer else ""),
        ):
            ET.SubElement(ti, tag).text = value
        goods = ET.SubElement(ET.SubElement(ti, "ListOfGoodService"), "GoodService")
        tickets = await tickets_of(session, inv.id)
        name = "Jasa sesuai service ticket " + ", ".join(t.number for t in tickets)
        for tag, value in (
            ("Opt", "B"),  # B = jasa
            ("Code", "000000"),
            ("Name", name[:250]),
            ("Unit", "UM.0030"),  # lainnya / paket
            ("Price", f"{inv.subtotal:.2f}"),
            ("Qty", "1"),
            ("TotalDiscount", "0"),
            ("TaxBase", f"{inv.subtotal:.2f}"),
            ("OtherTaxBase", f"{inv.dpp_other:.2f}"),
            ("VATRate", f"{inv.ppn_rate.normalize():f}"),
            ("VAT", f"{inv.ppn:.2f}"),
            ("STLGRate", "0"),
            ("STLG", "0"),
        ):
            ET.SubElement(goods, tag).text = value
    ET.indent(root)
    body: bytes = ET.tostring(root, encoding="utf-8")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + body


# ---------------------------------------------------------------- pack, send, reminders


async def build_pack(
    session: AsyncSession, storage: Storage, actor: Principal, inv: CustomerInvoice
) -> Attachment:
    contract = await session.get(Contract, inv.contract_id)
    assert contract is not None
    client = (
        await session.execute(select(Client).where(Client.code == inv.client_code))
    ).scalar_one_or_none()
    client_d: dict[str, Any] = {
        "name": client.name if client else contract.company_name,
        "address": client.address if client else None,
        "npwp": client.npwp if client else None,
    }
    packs: list[tuple[ServiceTicket, list[TicketLine], str, bytes | None]] = []
    dor_rows: list[tuple[str, date, str]] = []
    for t in await tickets_of(session, inv.id):
        sig = None
        if t.signature_attachment_id:
            att = await session.get(Attachment, t.signature_attachment_id)
            if att is not None:
                sig = (await storage.get(att.storage_key)).data
        packs.append((t, await lines_of(session, t.id), client_d["name"], sig))
        dors = await session.execute(
            select(Dor)
            .where(Dor.id.in_(select(TicketLine.dor_id).where(TicketLine.ticket_id == t.id)))
            .order_by(Dor.report_date)
        )
        dor_rows += [(d.number, d.report_date, d.activities or "") for d in dors.scalars()]
    pdf = documents.render_invoice_pack(
        await letterhead.load(session, storage),
        inv,
        client=client_d,
        contract_label=f"{contract.number} {contract.po_number or ''}".strip(),
        tickets=packs,
        dor_summary=dor_rows,
    )
    att = await dms.upload(
        session,
        storage,
        actor,
        entity_type=DOC,
        entity_id=str(inv.id),
        filename=f"{inv.number}-paket-invoice.pdf",
        data=pdf,
        note="Paket invoice",
    )
    inv.pack_attachment_id = att.id
    await session.flush()
    return att


async def send(
    session: AsyncSession, storage: Storage, actor: Principal, inv: CustomerInvoice, to: str
) -> email.Result:
    if inv.status not in OPEN:
        raise ConflictError("NOT_ISSUED", "Terbitkan faktur sebelum mengirim invoice.")
    att = await build_pack(session, storage, actor, inv)
    data = (await storage.get(att.storage_key)).data
    res = await email.send_email(
        to,
        f"Invoice {inv.number} - {format_idr(inv.total)}",
        f"<p>Terlampir invoice <b>{inv.number}</b> beserta faktur pajak {inv.faktur_number}, "
        f"service ticket yang ditandatangani, ringkasan DOR, dan BAST.</p>"
        f"<p>Total {format_idr(inv.total)}, jatuh tempo {inv.due_date:%d/%m/%Y}.</p>",
        f"Invoice {inv.number}, total {format_idr(inv.total)}, "
        f"jatuh tempo {inv.due_date:%d/%m/%Y}.",
        attachments=(email.Attachment(f"{inv.number}.pdf", data),),
    )
    inv.status, inv.sent_at, inv.sent_to = "sent", _now(), to
    await session.flush()
    await audit.record(
        session,
        action="send",
        entity_type=DOC,
        entity_id=inv.id,
        actor_id=actor.id,
        after={"to": to, "email": res.status},
    )
    return res


REMINDERS = {-7: "D-7", 1: "D+1", 7: "D+7", 14: "D+14"}


async def run_reminders(session: AsyncSession, today: date | None = None) -> int:
    """D-7, D+1, D+7 reminders to Billing Admin (and the client); D+14 escalation."""
    today = today or numbering.today_jakarta()
    sent = 0
    billing = await engine.holders_of_role(session, "billing_admin")
    escalate = await engine.holders_of_role(
        session, "head_of_finance"
    ) + await engine.holders_of_role(session, "head_of_sales")
    for inv in (
        await session.execute(select(CustomerInvoice).where(CustomerInvoice.status.in_(OPEN)))
    ).scalars():
        stage = REMINDERS.get((today - inv.due_date).days)
        if stage is None:
            continue
        users = escalate + billing if stage == "D+14" else billing
        title = (
            f"Eskalasi: {inv.number} lewat 14 hari"
            if stage == "D+14"
            else f"Pengingat {stage}: {inv.number} jatuh tempo {inv.due_date:%d/%m/%Y}"
        )
        n = await notifications.notify(
            session,
            users,
            kind="invoice_reminder",
            title=title,
            body=f"Sisa tagihan {format_idr(outstanding(inv))}.",
            link=f"/tagihan/invoice/{inv.id}",
            dedupe_key=f"invoice-reminder:{inv.id}:{stage}",
        )
        if n and inv.sent_to and stage != "D+14":
            await email.send_email(
                inv.sent_to,
                f"Pengingat pembayaran {inv.number}",
                f"<p>Invoice {inv.number} sebesar {format_idr(outstanding(inv))} "
                f"jatuh tempo {inv.due_date:%d/%m/%Y}.</p>",
                f"Invoice {inv.number} jatuh tempo {inv.due_date:%d/%m/%Y}.",
            )
        sent += n
    return sent
