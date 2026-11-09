"""Customer receipts (prompt 06 · 3).

Receipt journal: Dr 1110 (cash received), Dr 1410 (PPh 23 withheld by the client = prepaid tax)
/ Cr 1210 (cash + PPh 23). An invoice is paid when cash + PPh 23 cover its total.
Bank import: CSV (date, description, amount, reference) or MT940 (:61: / :86:); credits only,
deduplicated. Auto-match: an open invoice number in the text, else a unique open invoice whose
net cash (total - expected PPh 23) or outstanding equals the amount.
"""

import csv
import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.billing.invoice_service import OPEN, outstanding
from app.billing.models import BankLine, CustomerInvoice, Receipt, ReceiptAllocation
from app.core.errors import AppError, ConflictError
from app.master.models import Client
from app.services import audit, fx, ledger, numbering
from app.services.audit import AuditAction

DOC = "customer_receipt"
ZERO = Decimal(0)


@dataclass(frozen=True)
class AllocationIn:
    invoice_id: uuid.UUID
    cash: Decimal  # IDR received; for a USD invoice give cash_foreign instead
    pph23: Decimal = ZERO
    bukti_potong_no: str | None = None
    cash_foreign: Decimal | None = None


async def record(
    session: AsyncSession,
    actor: Principal,
    *,
    receipt_date: date,
    allocations: list[AllocationIn],
    bank_ref: str | None,
    source: str = "manual",
) -> Receipt:
    if not allocations:
        raise AppError(
            "ALLOCATIONS_REQUIRED",
            "Alokasikan penerimaan ke minimal satu invoice.",
            status_code=422,
        )
    if receipt_date > numbering.today_jakarta():
        raise AppError(
            "DATE_IN_FUTURE", "Tanggal penerimaan tidak boleh di masa depan.", status_code=422
        )
    invoices = {
        i.id: i
        for i in (
            await session.execute(
                select(CustomerInvoice)
                .where(CustomerInvoice.id.in_([a.invoice_id for a in allocations]))
                .with_for_update()
            )
        ).scalars()
    }
    clients = {i.client_code for i in invoices.values()}
    if len(invoices) != len({a.invoice_id for a in allocations}):
        raise AppError("INVOICE_INVALID", "Invoice tidak ditemukan.", status_code=422)
    if len(clients) != 1:
        raise AppError("MIXED_CLIENTS", "Satu penerimaan untuk satu klien.", status_code=422)
    # What each allocation clears from AR (at the invoice rate) and brings into the bank (at the
    # receipt rate). For USD the difference is the realised FX result (7100).
    plan: list[tuple[AllocationIn, Decimal, Decimal, Decimal | None, Decimal | None]] = []
    for a in allocations:
        inv = invoices[a.invoice_id]
        if inv.status not in OPEN:
            raise ConflictError("NOT_OPEN", f"{inv.number} tidak terbuka untuk pembayaran.")
        if a.cash < 0 or a.pph23 < 0:
            raise AppError(
                "AMOUNT_INVALID", "Nilai penerimaan tidak boleh negatif.", status_code=422
            )
        if inv.currency != fx.BASE:
            if not a.cash_foreign or a.cash_foreign <= 0:
                raise AppError(
                    "FOREIGN_AMOUNT_REQUIRED",
                    f"{inv.number} dalam {inv.currency}: isi jumlah diterima dalam {inv.currency}.",
                    status_code=422,
                )
            r_rate = await fx.rate(session, inv.currency, receipt_date)
            cash_idr = fx.to_idr(a.cash_foreign, r_rate)
            settled_f = a.cash_foreign + fx.cents(a.pph23 / inv.fx_rate)
            assert inv.total_foreign is not None
            remaining_f = inv.total_foreign - inv.paid_foreign
            if settled_f > remaining_f + Decimal("0.01"):
                raise AppError(
                    "OVERPAYMENT",
                    f"{inv.number}: diterima {settled_f} {inv.currency} "
                    f"melebihi sisa {remaining_f}.",
                    status_code=422,
                )
            cleared = (
                outstanding(inv) - a.pph23
                if settled_f >= remaining_f - Decimal("0.01")
                else fx.to_idr(a.cash_foreign, inv.fx_rate)
            )
            plan.append((a, cash_idr, cleared, a.cash_foreign, r_rate))
        else:
            if a.cash + a.pph23 <= 0:
                raise AppError(
                    "AMOUNT_INVALID", "Nilai penerimaan harus lebih dari 0.", status_code=422
                )
            plan.append((a, a.cash, a.cash, None, None))
        if plan[-1][2] + a.pph23 > outstanding(inv):
            raise AppError(
                "OVERPAYMENT",
                f"{inv.number}: diterima {plan[-1][2] + a.pph23} melebihi sisa {outstanding(inv)}.",
                status_code=422,
            )
        if inv.pph23_withheld + a.pph23 > inv.pph23_expected:
            raise AppError(
                "PPH23_EXCEEDS",
                f"{inv.number}: PPh 23 dipotong melebihi perkiraan {inv.pph23_expected}.",
                status_code=422,
            )
    cash = sum((p[1] for p in plan), ZERO)
    cleared = sum((p[2] for p in plan), ZERO)
    pph = sum((a.pph23 for a in allocations), ZERO)
    client = clients.pop()
    r = Receipt(
        number=await numbering.next(session, "RCP", on=receipt_date),
        client_code=client,
        receipt_date=receipt_date,
        cash=cash,
        pph23=pph,
        bank_ref=bank_ref,
        source=source,
        created_by=actor.id,
    )
    session.add(r)
    await session.flush()
    entry = await ledger.post_event(
        session,
        "customer_receipt",
        {"cash": cash, "pph23": pph, "fx_loss": cleared - cash, "receivable": cleared + pph},
        entry_date=receipt_date,
        description=f"{r.number} penerimaan {client or ''}",
        source_type=DOC,
        source_id=r.id,
        source_number=r.number,
        by=actor.id,
        dims=ledger.Dims(partner_type="client", partner_code=client),
        memo=r.number,
    )
    r.journal_id = entry.id
    for a, cash_idr, clears, cash_f, rate_used in plan:
        inv = invoices[a.invoice_id]
        session.add(
            ReceiptAllocation(
                receipt_id=r.id,
                invoice_id=inv.id,
                cash=cash_idr,
                pph23=a.pph23,
                bukti_potong_no=(a.bukti_potong_no or "").strip() or None,
                cash_foreign=cash_f,
                fx_rate=rate_used,
                fx_difference=clears - cash_idr,
            )
        )
        inv.paid_amount += clears
        if cash_f is not None:
            inv.paid_foreign += cash_f + fx.cents(a.pph23 / inv.fx_rate)
        inv.pph23_withheld += a.pph23
        if outstanding(inv) == 0:
            inv.status, inv.paid_at = "paid", receipt_date
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.POST,
        entity_type=DOC,
        entity_id=r.id,
        actor_id=actor.id,
        after={"number": r.number, "cash": cash, "pph23": pph, "journal": entry.number},
    )
    return r


# ---------------------------------------------------------------- bank import


@dataclass(frozen=True)
class StatementLine:
    value_date: date
    amount: Decimal
    description: str
    reference: str | None


def _amount(raw: str) -> Decimal | None:
    s = raw.strip().replace("Rp", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = (
            s.replace(".", "").replace(",", ".")
            if s.rfind(",") > s.rfind(".")
            else s.replace(",", "")
        )
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _date(raw: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    return None


def parse_csv(text: str) -> list[StatementLine]:
    sample = text[:2000]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]

    def col(*names: str) -> int | None:
        return next((head.index(n) for n in names if n in head), None)

    c_date = col("date", "tanggal", "tgl", "value date")
    c_desc = col("description", "keterangan", "uraian", "remark")
    c_amt = col("amount", "jumlah", "nominal", "credit", "kredit")
    c_ref = col("reference", "referensi", "ref", "no. referensi")
    if c_date is None or c_desc is None or c_amt is None:
        raise AppError(
            "CSV_HEADER", "CSV perlu kolom tanggal, keterangan, dan jumlah.", status_code=422
        )
    out = []
    for i, r in enumerate(rows[1:], start=2):
        d, a = _date(r[c_date]), _amount(r[c_amt])
        if d is None or a is None:
            raise AppError("CSV_ROW", f"Baris {i} tidak terbaca (tanggal/jumlah).", status_code=422)
        out.append(
            StatementLine(
                d,
                a,
                r[c_desc].strip(),
                r[c_ref].strip() if c_ref is not None and len(r) > c_ref else None,
            )
        )
    return out


_MT61 = re.compile(r"^:61:(\d{6})(\d{4})?(R?[CD])([A-Z])?([\d,]+)N?\w{3}(.*)$")


def parse_mt940(text: str) -> list[StatementLine]:
    out: list[StatementLine] = []
    pending: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith(":61:"):
            if pending:
                out.append(StatementLine(**pending))
            m = _MT61.match(line)
            if not m:
                raise AppError(
                    "MT940_ROW", f"Baris :61: tidak terbaca: {line[:40]}", status_code=422
                )
            yymmdd, _entry, mark, _fund, amount, rest = m.groups()
            d = date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6]))
            amt = Decimal(amount.replace(",", "."))
            if mark in ("D", "RC"):
                amt = -amt
            ref = rest.split("//")[0].strip() or None
            pending = {"value_date": d, "amount": amt, "description": "", "reference": ref}
        elif line.startswith(":86:") and pending is not None:
            pending["description"] = line[4:].strip()
        elif pending is not None and pending["description"] and not line.startswith(":"):
            pending["description"] += " " + line.strip()
    if pending:
        out.append(StatementLine(**pending))
    return out


async def _suggest(
    session: AsyncSession, line: StatementLine
) -> tuple[uuid.UUID | None, str | None]:
    open_invs = list(
        (
            await session.execute(select(CustomerInvoice).where(CustomerInvoice.status.in_(OPEN)))
        ).scalars()
    )
    text = f"{line.description} {line.reference or ''}".upper()
    for inv in open_invs:
        if inv.number.upper() in text:
            return inv.id, "invoice_number"
    by_amount = [
        i
        for i in open_invs
        if line.amount
        in (
            i.net_cash - i.paid_amount,
            outstanding(i),
            outstanding(i) - (i.pph23_expected - i.pph23_withheld),
        )
    ]
    if len(by_amount) == 1:
        return by_amount[0].id, "amount"
    return None, None


async def import_statement(
    session: AsyncSession,
    actor: Principal,
    filename: str,
    data: bytes,
    bank_account_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Store every statement line of a bank account (default account when not given).
    Credits get an invoice suggestion for AR; debits (negative) are kept for bank
    reconciliation (07b) with status `debit`. A line already imported is skipped."""
    from app.treasury import bank_service

    account = await bank_service.account_or_default(session, bank_account_id)
    text = data.decode("utf-8-sig", errors="replace")
    lines = parse_mt940(text) if ":61:" in text else parse_csv(text)
    ref = f"{filename[:40]}-{datetime.now(UTC):%Y%m%d%H%M%S}"
    created = skipped = matched = debits = 0
    for x in lines:
        if x.amount == 0:
            continue
        fp = hashlib.sha256(
            f"{account.code}|{x.value_date}|{x.amount}|{x.description}|{x.reference}".encode()
        ).hexdigest()
        if (await session.execute(select(BankLine.id).where(BankLine.fingerprint == fp))).first():
            skipped += 1 if x.amount > 0 else 0
            continue
        inv_id, rule = await _suggest(session, x) if x.amount > 0 else (None, None)
        session.add(
            BankLine(
                import_ref=ref,
                fingerprint=fp,
                value_date=x.value_date,
                amount=x.amount.quantize(Decimal(1)),
                description=x.description[:500] or "-",
                reference=x.reference,
                suggested_invoice_id=inv_id,
                match_rule=rule,
                status="unmatched" if x.amount > 0 else "debit",
                bank_account_id=account.id,
                created_by=actor.id,
            )
        )
        created += 1 if x.amount > 0 else 0
        debits += 1 if x.amount < 0 else 0
        matched += 1 if inv_id else 0
    await session.flush()
    await audit.record(
        session,
        action="import",
        entity_type="bank_statement",
        entity_id=ref,
        actor_id=actor.id,
        after={"lines": created, "debits": debits, "duplicates": skipped, "suggested": matched},
    )
    # `lines`/`duplicates` count credits (customer receipts); `debits` are kept for 07b
    # bank reconciliation.
    return {
        "import_ref": ref,
        "lines": created,
        "debits": debits,
        "duplicates": skipped,
        "suggested": matched,
    }


async def confirm_line(
    session: AsyncSession, actor: Principal, line: BankLine, invoice_id: uuid.UUID
) -> Receipt:
    """Turn a bank credit into a receipt. When the amount equals what is left after the
    expected PPh 23, the remaining PPh 23 is recorded as withheld."""
    if line.status != "unmatched":
        raise ConflictError("LINE_DONE", "Baris mutasi sudah diproses.")
    inv = await session.get(CustomerInvoice, invoice_id)
    if inv is None:
        raise AppError("INVOICE_INVALID", "Invoice tidak ditemukan.", status_code=422)
    pph_left = inv.pph23_expected - inv.pph23_withheld
    pph = pph_left if line.amount + pph_left == outstanding(inv) else ZERO
    r = await record(
        session,
        actor,
        receipt_date=line.value_date,
        allocations=[AllocationIn(inv.id, line.amount, pph)],
        bank_ref=line.reference or line.description[:120],
        source="bank_import",
    )
    line.status, line.receipt_id, line.suggested_invoice_id = "matched", r.id, inv.id
    await session.flush()
    return r


# ---------------------------------------------------------------- AR reports


BUCKETS = ("not_due", "d1_30", "d31_60", "d61_90", "d90_plus")


def _bucket(due: date, as_of: date) -> str:
    late = (as_of - due).days
    return (
        "not_due"
        if late <= 0
        else "d1_30"
        if late <= 30
        else "d31_60"
        if late <= 60
        else "d61_90"
        if late <= 90
        else "d90_plus"
    )


async def ar_aging(session: AsyncSession, as_of: date) -> dict[str, Any]:
    rows: dict[str, dict[str, Decimal]] = {}
    totals = dict.fromkeys(BUCKETS, ZERO)
    for inv in (
        await session.execute(select(CustomerInvoice).where(CustomerInvoice.status.in_(OPEN)))
    ).scalars():
        b = _bucket(inv.due_date, as_of)
        r = rows.setdefault(inv.client_code or "-", dict.fromkeys(BUCKETS, ZERO))
        r[b] += outstanding(inv)
        totals[b] += outstanding(inv)
    names = dict((await session.execute(select(Client.code, Client.name))).tuples().all())
    return {
        "as_of": as_of,
        "rows": [
            {"client_code": c, "client_name": names.get(c, c), **b, "total": sum(b.values())}
            for c, b in sorted(rows.items())
        ],
        "totals": {**totals, "total": sum(totals.values())},
    }


async def cash_kpis(session: AsyncSession, as_of: date, days: int = 90) -> dict[str, Any]:
    """DSO = AR (open invoices) / invoiced in the last `days` x `days`;
    days-to-cash = average days from invoice date to full payment (target < 30)."""
    start = as_of - timedelta(days=days - 1)
    ar = sum(
        (
            outstanding(i)
            for i in (
                await session.execute(
                    select(CustomerInvoice).where(CustomerInvoice.status.in_(OPEN))
                )
            ).scalars()
        ),
        ZERO,
    )
    billed = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(CustomerInvoice.total), 0)).where(
                    CustomerInvoice.status.in_((*OPEN, "paid")),
                    CustomerInvoice.invoice_date.between(start, as_of),
                )
            )
        ).scalar_one()
    )
    paid = list(
        (
            await session.execute(
                select(CustomerInvoice).where(
                    CustomerInvoice.status == "paid", CustomerInvoice.paid_at.between(start, as_of)
                )
            )
        ).scalars()
    )
    dtc = (
        Decimal(sum((i.paid_at - i.invoice_date).days for i in paid if i.paid_at)) / len(paid)
        if paid
        else None
    )
    return {
        "as_of": as_of,
        "ar_balance": ar,
        "billed_period": billed,
        "dso_days": (ar / billed * days).quantize(Decimal("0.1")) if billed > 0 else None,
        "days_to_cash": dtc.quantize(Decimal("0.1")) if dtc is not None else None,
        "paid_invoices": len(paid),
        "target_days_to_cash": 30,
    }
