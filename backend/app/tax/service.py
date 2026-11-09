"""Monthly tax workspace (07d; ACCOUNTING.md · Tax configuration).

Amounts come from the GL movements of the period (entry date in the month):
  PPN    output = credits on 2210, input = debits on 1420 (the settlement itself excluded);
         payable = output - input - overpayment carried in from the previous period
  PPh 21 credits on 2220 (payroll), PPh 23 credits on 2230 (vendor invoices); payments excluded
Steps per return: billing code -> payment (payment run or direct, NTPN) -> SPT Masa (BPE).
Deadlines (PMK 81/2024, setting `tax.deadlines`): PPh pay by the 15th and file by the 20th of
the next month; PPN pay and file by the end of the next month. Alert D-3 (job `tax`).
"""

import calendar
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.billing.models import CustomerInvoice, Receipt, ReceiptAllocation
from app.core.errors import AppError, ConflictError, NotFoundError
from app.finance.models import JournalEntry, JournalLine, VendorInvoice
from app.notifications import service as notifications
from app.services import audit, ledger
from app.services.numbering import today_jakarta
from app.setup import service as settings_store
from app.tax.models import TaxReturn
from app.treasury import bank_service
from app.treasury.models import PaymentRun, PaymentRunItem
from app.workflow import engine

TYPES = ("ppn", "pph21", "pph23")
LABELS = {"ppn": "PPN", "pph21": "PPh 21", "pph23": "PPh 23"}
DEADLINES_KEY = "tax.deadlines"
DEFAULT_DEADLINES = {"pph_pay_day": 15, "pph_file_day": 20, "ppn_months_after": 1}
ALERT_DAYS = 3
ZERO = Decimal(0)
SETTLEMENT_EVENTS = ("ppn_settled", "tax_paid", "payment_run")
NTPN = re.compile(r"^[0-9A-Z]{16}$")
BILLING = re.compile(r"^\d{15}$")


def _bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _next_month(year: int, month: int, n: int = 1) -> tuple[int, int]:
    k = year * 12 + (month - 1) + n
    return k // 12, k % 12 + 1


async def deadlines(
    session: AsyncSession, year: int, month: int, tax_type: str
) -> tuple[date, date]:
    cfg = {**DEFAULT_DEADLINES, **(await settings_store.get(session, DEADLINES_KEY, {}) or {})}
    if tax_type == "ppn":
        y, m = _next_month(year, month, int(cfg["ppn_months_after"]))
        end = date(y, m, calendar.monthrange(y, m)[1])
        return end, end
    y, m = _next_month(year, month)
    last = calendar.monthrange(y, m)[1]
    return (
        date(y, m, min(int(cfg["pph_pay_day"]), last)),
        date(y, m, min(int(cfg["pph_file_day"]), last)),
    )


async def _movement(
    session: AsyncSession, account: str, year: int, month: int, *, credit_side: bool
) -> Decimal:
    start, end = _bounds(year, month)
    sign = (
        (JournalLine.credit - JournalLine.debit)
        if credit_side
        else (JournalLine.debit - JournalLine.credit)
    )
    v = (
        await session.execute(
            select(func.coalesce(func.sum(sign), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.account_code == account,
                JournalEntry.entry_date.between(start, end),
                (JournalEntry.event.is_(None)) | (JournalEntry.event.not_in(SETTLEMENT_EVENTS)),
            )
        )
    ).scalar_one()
    return Decimal(v)


async def _carried_in(session: AsyncSession, year: int, month: int) -> Decimal:
    py, pm = _next_month(year, month, -1)
    prev = (
        await session.execute(
            select(TaxReturn).where(
                TaxReturn.year == py, TaxReturn.month == pm, TaxReturn.tax_type == "ppn"
            )
        )
    ).scalar_one_or_none()
    return Decimal(prev.carry_forward) if prev else ZERO


async def _compute(session: AsyncSession, r: TaxReturn) -> None:
    if r.tax_type == "ppn":
        r.output_tax = await _movement(session, "2210", r.year, r.month, credit_side=True)
        r.input_tax = await _movement(session, "1420", r.year, r.month, credit_side=False)
        r.carried_in = await _carried_in(session, r.year, r.month)
        net = r.output_tax - r.input_tax - r.carried_in
        r.amount, r.carry_forward = max(net, ZERO), max(-net, ZERO)
    else:
        account = "2220" if r.tax_type == "pph21" else "2230"
        r.amount = max(await _movement(session, account, r.year, r.month, credit_side=True), ZERO)


async def returns(session: AsyncSession, year: int, month: int) -> list[TaxReturn]:
    """The period's returns, created on first view; drafts are recomputed from the GL."""
    out = []
    for t in TYPES:
        r = (
            await session.execute(
                select(TaxReturn)
                .where(TaxReturn.year == year, TaxReturn.month == month, TaxReturn.tax_type == t)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            pay_due, file_due = await deadlines(session, year, month, t)
            r = TaxReturn(
                year=year,
                month=month,
                tax_type=t,
                status="draft",
                pay_due=pay_due,
                file_due=file_due,
            )
            session.add(r)
        if r.status == "draft":
            await _compute(session, r)
        out.append(r)
    await session.flush()
    return out


async def _get(session: AsyncSession, rid: uuid.UUID) -> TaxReturn:
    r = await session.get(TaxReturn, rid, with_for_update=True)
    if r is None:
        raise NotFoundError("NOT_FOUND", "SPT tidak ditemukan.")
    return r


async def set_billing(
    session: AsyncSession, actor: Principal, r: TaxReturn, code: str, expires: date | None
) -> TaxReturn:
    if r.status != "draft":
        raise ConflictError(
            "NOT_DRAFT", f"{LABELS[r.tax_type]} {r.month:02d}/{r.year} sudah diproses."
        )
    await _compute(session, r)
    if r.amount <= 0:
        raise ConflictError(
            "NOTHING_TO_PAY", "Tidak ada pajak yang harus dibayar; langsung lapor SPT."
        )
    if not BILLING.match(code):
        raise AppError(
            "BILLING_CODE_INVALID", "Kode billing harus 15 digit angka.", status_code=422
        )
    r.billing_code, r.billing_expires, r.status = code, expires, "billed"
    await session.flush()
    await audit.record(
        session,
        action="billing",
        entity_type="tax_return",
        entity_id=r.id,
        actor_id=actor.id,
        after={"billing_code": code, "amount": r.amount},
    )
    return r


async def pay(
    session: AsyncSession,
    actor: Principal,
    r: TaxReturn,
    *,
    ntpn: str,
    paid_on: date,
    method: str,
    payment_run_id: uuid.UUID | None,
    bank_account_id: uuid.UUID | None,
) -> TaxReturn:
    if r.status != "billed":
        raise ConflictError("NOT_BILLED", "Buat kode billing terlebih dahulu.")
    ntpn = ntpn.strip().upper()
    if not NTPN.match(ntpn):
        raise AppError("NTPN_INVALID", "NTPN harus 16 karakter huruf/angka.", status_code=422)
    label = f"{LABELS[r.tax_type]} {r.month:02d}/{r.year}"
    if method == "payment_run":
        if r.tax_type == "ppn":
            raise AppError(
                "PPN_DIRECT_ONLY",
                "PPN dibayar langsung (setoran dan kompensasi masukan).",
                status_code=422,
            )
        run = await session.get(PaymentRun, payment_run_id) if payment_run_id else None
        if run is None or run.status != "released":
            raise ConflictError("RUN_NOT_RELEASED", "Payment run belum dirilis atau tidak ada.")
        paid = (
            await session.execute(
                select(func.coalesce(func.sum(PaymentRunItem.amount), 0)).where(
                    PaymentRunItem.run_id == run.id, PaymentRunItem.kind == r.tax_type
                )
            )
        ).scalar_one()
        if Decimal(paid) != r.amount:
            raise ConflictError(
                "RUN_AMOUNT_MISMATCH",
                f"Payment run {run.number} membayar {LABELS[r.tax_type]} {paid}, SPT {r.amount}.",
            )
        r.payment_run_id, r.journal_id = run.id, run.journal_id
    elif method == "direct":
        acc = await bank_service.account_or_default(session, bank_account_id)
        have = await bank_service.balance(session, acc)
        if have < r.amount:
            raise ConflictError(
                "INSUFFICIENT_BALANCE", f"Saldo {acc.name} tidak cukup untuk {label}."
            )
        if r.tax_type == "ppn":
            parts = [
                ledger.Part("output", r.output_tax),
                ledger.Part("input", r.output_tax - r.amount),
                ledger.Part("bank", r.amount),
            ]
            event = "ppn_settled"
        else:
            parts = [ledger.Part(r.tax_type, r.amount), ledger.Part("bank", r.amount)]
            event = "tax_paid"
        entry = await ledger.post_parts(
            session,
            event,
            parts,
            entry_date=paid_on,
            description=f"Setoran {label} NTPN {ntpn}",
            source_type="tax_return",
            source_id=r.id,
            source_number=f"{r.tax_type.upper()}-{r.year}-{r.month:02d}",
            by=actor.id,
            accounts={"bank": acc.gl_account},
        )
        r.journal_id = entry.id
    else:
        raise AppError("METHOD_INVALID", "Metode bayar: payment_run atau direct.", status_code=422)
    r.ntpn, r.paid_on, r.payment_method, r.status = ntpn, paid_on, method, "paid"
    await session.flush()
    await audit.record(
        session,
        action="pay",
        entity_type="tax_return",
        entity_id=r.id,
        actor_id=actor.id,
        after={"ntpn": ntpn, "method": method, "amount": r.amount},
    )
    return r


async def file(
    session: AsyncSession, actor: Principal, r: TaxReturn, *, bpe_no: str, filed_on: date
) -> TaxReturn:
    if r.status == "draft":
        await _compute(session, r)
        if r.amount > 0:
            raise ConflictError("NOT_PAID", "Bayar pajak terlebih dahulu sebelum lapor SPT.")
        if r.tax_type == "ppn" and r.output_tax > 0:
            # Overpaid/compensated: clear output against input; the rest of 1420 carries on.
            r.journal_id = (
                await ledger.post_parts(
                    session,
                    "ppn_settled",
                    [ledger.Part("output", r.output_tax), ledger.Part("input", r.output_tax)],
                    entry_date=filed_on,
                    description=f"Kompensasi PPN {r.month:02d}/{r.year}",
                    source_type="tax_return",
                    source_id=r.id,
                    source_number=f"PPN-{r.year}-{r.month:02d}",
                    by=actor.id,
                )
            ).id
    elif r.status != "paid":
        raise ConflictError("NOT_PAID", "Bayar pajak terlebih dahulu sebelum lapor SPT.")
    if len(bpe_no.strip()) < 5:
        raise AppError("BPE_INVALID", "Isi nomor BPE dari Coretax.", status_code=422)
    r.bpe_no, r.filed_on, r.status = bpe_no.strip(), filed_on, "filed"
    await session.flush()
    await audit.record(
        session,
        action="file",
        entity_type="tax_return",
        entity_id=r.id,
        actor_id=actor.id,
        after={"bpe_no": r.bpe_no, "filed_on": filed_on.isoformat()},
    )
    return r


# ---------------------------------------------------------------- source lists


async def documents(
    session: AsyncSession, year: int, month: int
) -> dict[str, list[dict[str, Any]]]:
    start, end = _bounds(year, month)
    out_f = (
        await session.execute(
            select(CustomerInvoice)
            .where(
                CustomerInvoice.invoice_date.between(start, end),
                CustomerInvoice.status.not_in(("draft", "cancelled")),
                CustomerInvoice.is_opening.is_(False),
            )
            .order_by(CustomerInvoice.invoice_date)
        )
    ).scalars()
    in_f = (
        await session.execute(
            select(VendorInvoice)
            .where(
                VendorInvoice.invoice_date.between(start, end),
                VendorInvoice.status.in_(("approved", "paid")),
                VendorInvoice.is_opening.is_(False),
            )
            .order_by(VendorInvoice.invoice_date)
        )
    ).scalars()
    in_list = list(in_f)
    withheld_by_clients = (
        await session.execute(
            select(ReceiptAllocation, Receipt, CustomerInvoice.number)
            .join(Receipt, Receipt.id == ReceiptAllocation.receipt_id)
            .join(CustomerInvoice, CustomerInvoice.id == ReceiptAllocation.invoice_id)
            .where(Receipt.receipt_date.between(start, end), ReceiptAllocation.pph23 > 0)
        )
    ).tuples()

    def m(v: Decimal | None) -> str | None:
        return format(v, "f") if v is not None else None

    return {
        "output_fakturs": [
            {
                "number": i.number,
                "faktur_no": i.faktur_number,
                "date": i.invoice_date.isoformat(),
                "client": i.client_code,
                "dpp": m(i.dpp_other),
                "ppn": m(i.ppn),
            }
            for i in out_f
        ],
        "input_fakturs": [
            {
                "number": v.number,
                "faktur_no": v.tax_invoice_no,
                "date": v.invoice_date.isoformat(),
                "vendor": v.vendor_code,
                "dpp": m(v.dpp),
                "ppn": m(v.ppn),
            }
            for v in in_list
            if v.ppn > 0
        ],
        "pph23_withheld": [
            {
                "number": v.number,
                "date": v.invoice_date.isoformat(),
                "vendor": v.vendor_code,
                "dpp": m(v.dpp),
                "pph23": m(v.pph23),
            }
            for v in in_list
            if v.pph23 > 0
        ],
        "pph23_by_clients": [
            {
                "invoice": inv_no,
                "date": rc.receipt_date.isoformat(),
                "client": rc.client_code,
                "pph23": m(a.pph23),
                "bukti_potong_no": a.bukti_potong_no,
            }
            for a, rc, inv_no in withheld_by_clients
        ],
    }


# ---------------------------------------------------------------- alerts


async def deadline_alerts(session: AsyncSession, today: date | None = None) -> int:
    """D-3 (and overdue) reminders to the Tax Specialists for unpaid or unfiled returns."""
    today = today or today_jakarta()
    y, m = _next_month(today.year, today.month, -1)
    await returns(session, y, m)  # last month's returns exist from the 1st of this month
    users = await engine.holders_of_role(session, "tax_specialist")
    sent = 0
    for r in (
        await session.execute(select(TaxReturn).where(TaxReturn.status != "filed"))
    ).scalars():
        label = f"{LABELS[r.tax_type]} {r.month:02d}/{r.year}"
        steps = []
        if r.status in ("draft", "billed") and r.amount > 0:
            steps.append(("pay", r.pay_due, f"bayar {label} paling lambat {r.pay_due:%d/%m/%Y}"))
        steps.append(("file", r.file_due, f"lapor SPT {label} paling lambat {r.file_due:%d/%m/%Y}"))
        for step, due, text in steps:
            if today >= due - timedelta(days=ALERT_DAYS):
                sent += await notifications.notify(
                    session,
                    users,
                    kind="tax_deadline",
                    title=f"Tenggat pajak: {text}",
                    body="Lewat tenggat!" if today > due else f"Tenggat {due:%d/%m/%Y}.",
                    link=f"/keuangan/pajak?year={r.year}&month={r.month}",
                    dedupe_key=f"tax-{r.id}-{step}-{'late' if today > due else 'd3'}",
                )
    await session.flush()
    return sent
