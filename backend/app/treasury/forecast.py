"""13-week cash forecast (07b), weekly from the Monday of the current week.

Opening: balance of the active bank accounts (GL).
In:  AR open invoices by due date, net of the PPh 23 still expected to be withheld (overdue
     items in week 1); WIP to be invoiced (unbilled revenue 1220) collected after
     `wip_collection_days`.
Out: AP approved vendor invoices by due date (net of what released runs paid); net salaries on
     the 25th; BPJS on the 10th; PPh 21/23 on the 15th; PPN at month end; loan instalments;
     CAPEX milestones. The first occurrence of salaries/BPJS/PPh/PPN uses what the GL owes now
     (2310, 2240, 2220+2230, 2210-1420) when that is higher than the monthly estimate.
Estimates and schedules live in setting `treasury.forecast`:
  {"payroll_monthly", "bpjs_monthly", "pph_monthly", "ppn_monthly", "wip_collection_days",
   "loans": [{"day", "amount", "until", "label"}], "capex": [{"date", "amount", "label"}]}
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.invoice_service import OPEN as AR_OPEN
from app.billing.models import CustomerInvoice
from app.finance import ap_service as ap
from app.services import ledger
from app.services.numbering import today_jakarta
from app.setup import service as settings_store
from app.treasury import bank_service
from app.treasury.models import BankAccount

KEY = "treasury.forecast"
WEEKS = 13
ZERO = Decimal(0)
IN = ("ar", "wip")
OUT = ("ap", "payroll", "bpjs", "tax", "ppn", "loan", "capex")
LABELS = {
    "ar": "Piutang jatuh tempo (neto PPh 23)",
    "wip": "WIP akan ditagih",
    "ap": "Utang vendor jatuh tempo",
    "payroll": "Gaji bersih (tgl 25)",
    "bpjs": "BPJS (tgl 10)",
    "tax": "PPh 21/23 (tgl 15)",
    "ppn": "PPN (akhir bulan)",
    "loan": "Angsuran pinjaman",
    "capex": "Termin CAPEX",
}


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return ZERO


def _monthly(start: date, end: date, day: int) -> list[date]:
    """Each date with day-of-month `day` (clamped to month end) in [start, end]."""
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        last = calendar.monthrange(y, m)[1]
        d = date(y, m, min(day, last))
        if start <= d <= end:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


async def build(session: AsyncSession, today: date | None = None) -> dict[str, Any]:
    today = today or today_jakarta()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=7 * WEEKS - 1)
    cfg = await settings_store.get(session, KEY, {}) or {}
    starts = [start + timedelta(days=7 * i) for i in range(WEEKS)]
    weeks: list[dict[str, Decimal]] = [{k: ZERO for k in (*IN, *OUT)} for _ in range(WEEKS)]

    def put(on: date, key: str, amount: Decimal) -> None:
        if amount <= 0:
            return
        i = 0 if on < start else (on - start).days // 7
        if i < WEEKS:
            weeks[i][key] += amount

    accounts = list(
        (
            await session.execute(select(BankAccount).where(BankAccount.is_active.is_(True)))
        ).scalars()
    )
    opening = sum([await bank_service.balance(session, a) for a in accounts], ZERO)

    for inv in (
        await session.execute(select(CustomerInvoice).where(CustomerInvoice.status.in_(AR_OPEN)))
    ).scalars():
        net = inv.net_cash - inv.paid_amount
        due = inv.due_date or inv.invoice_date
        put(due or today, "ar", Decimal(net))
    wip = await ledger.balance(session, "1220")
    put(today + timedelta(days=int(_d(cfg.get("wip_collection_days", 45)))), "wip", wip)

    for vi in await ap.payables(session):
        put(vi.due_date or vi.invoice_date, "ap", ap.outstanding(vi))

    owed = {
        "payroll": -await ledger.balance(session, "2310"),
        "bpjs": -await ledger.balance(session, "2240"),
        "tax": -(await ledger.balance(session, "2220") + await ledger.balance(session, "2230")),
        "ppn": -(await ledger.balance(session, "2210") + await ledger.balance(session, "1420")),
    }
    monthly = {
        "payroll": _d(cfg.get("payroll_monthly")),
        "bpjs": _d(cfg.get("bpjs_monthly")),
        "tax": _d(cfg.get("pph_monthly")),
        "ppn": _d(cfg.get("ppn_monthly")),
    }
    for key, day in (("payroll", 25), ("bpjs", 10), ("tax", 15), ("ppn", 31)):
        for n, on in enumerate(_monthly(today, end, day)):
            put(on, key, max(owed[key], monthly[key]) if n == 0 else monthly[key])

    for loan in cfg.get("loans") or []:
        until = date.fromisoformat(loan["until"]) if loan.get("until") else end
        for on in _monthly(today, min(end, until), int(loan.get("day") or 1)):
            put(on, "loan", _d(loan.get("amount")))
    for c in cfg.get("capex") or []:
        try:
            on = date.fromisoformat(str(c.get("date")))
        except ValueError:
            continue
        if on <= end:
            put(on, "capex", _d(c.get("amount")))

    balance = opening
    lowest = opening
    rows: list[dict[str, Any]] = []
    for i, w in enumerate(weeks):
        inflow = sum((w[k] for k in IN), ZERO)
        outflow = sum((w[k] for k in OUT), ZERO)
        row = {
            "week": i + 1,
            "start": starts[i].isoformat(),
            "end": (starts[i] + timedelta(days=6)).isoformat(),
            "opening": format(balance, "f"),
            **{k: format(w[k], "f") for k in (*IN, *OUT)},
            "inflow": format(inflow, "f"),
            "outflow": format(outflow, "f"),
            "net": format(inflow - outflow, "f"),
        }
        balance += inflow - outflow
        row["closing"] = format(balance, "f")
        row["negative"] = balance < 0
        lowest = min(lowest, balance)
        rows.append(row)
    return {
        "as_of": today.isoformat(),
        "opening": format(opening, "f"),
        "closing": format(balance, "f"),
        "lowest": format(lowest, "f"),
        "inflows": [{"key": k, "label": LABELS[k]} for k in IN],
        "outflows": [{"key": k, "label": LABELS[k]} for k in OUT],
        "weeks": rows,
        "settings": cfg,
    }
