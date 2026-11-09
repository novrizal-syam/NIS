"""Financial reports from the general ledger (prompt 07a · 4).

All amounts are IDR from posted journal lines (reversals included, so corrected entries net
out). Balance sheet equity includes the unclosed result (prior years + current year); the year
end closing entry comes with the period close (07d).
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fpdf import FPDF, FontFace
from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import ServiceTicket, TicketLine
from app.crm.quotation_pdf import _t
from app.finance.models import JournalEntry, JournalLine
from app.master.models import Account
from app.operations.models import Dor
from app.project.models import BudgetLedgerEntry, Project, ProjectBudgetLine
from app.services.export import Column
from app.services.money import format_idr

ZERO = Decimal(0)
BANK = ("1110", "1111")
CASH_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Penerimaan dari pelanggan", ("1210", "1220", "4100")),
    ("Pembayaran ke vendor", ("2110", "2120")),
    ("Gaji karyawan", ("2310", "5100", "6100")),
    ("Pajak dan BPJS", ("2210", "2220", "2230", "2240", "1410", "1420")),
    ("Uang muka kerja", ("1120",)),
    ("Investasi aset (CAPEX)", ("1510", "1520")),
    ("Pinjaman bank", ("2410",)),
    ("Modal", ("3100", "3200")),
)


@dataclass(frozen=True)
class Report:
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    summary: dict[str, Any]


async def _accounts(session: AsyncSession) -> dict[str, Account]:
    return {a.code: a for a in (await session.execute(select(Account))).scalars()}


def _sums(
    date_from: date | None, date_to: date, project_id: uuid.UUID | None = None
) -> Select[Any]:
    conds = [JournalEntry.entry_date <= date_to]
    if date_from:
        conds.append(JournalEntry.entry_date >= date_from)
    if project_id:
        conds.append(JournalLine.project_id == project_id)
    return (
        select(
            JournalLine.account_code,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(and_(*conds))
        .group_by(JournalLine.account_code)
    )


async def _totals(
    session: AsyncSession,
    date_from: date | None,
    date_to: date,
    project_id: uuid.UUID | None = None,
) -> dict[str, tuple[Decimal, Decimal]]:
    rows = await session.execute(_sums(date_from, date_to, project_id))
    return {code: (Decimal(d), Decimal(c)) for code, d, c in rows.tuples()}


def _signed(acc: Account, debit: Decimal, credit: Decimal) -> Decimal:
    """Balance in the account's normal direction."""
    return debit - credit if acc.normal_balance == "debit" else credit - debit


# ---------------------------------------------------------------- trial balance


async def trial_balance(session: AsyncSession, as_of: date) -> Report:
    accs = await _accounts(session)
    t = await _totals(session, None, as_of)
    rows: list[dict[str, Any]] = []
    td = tc = ZERO
    for code in sorted(t):
        d, c = t[code]
        bal = d - c
        rows.append(
            {
                "account": code,
                "name": accs[code].name if code in accs else code,
                "debit": d,
                "credit": c,
                "balance_debit": bal if bal > 0 else ZERO,
                "balance_credit": -bal if bal < 0 else ZERO,
            }
        )
        td, tc = td + d, tc + c
    bd: Decimal = sum((r["balance_debit"] for r in rows), ZERO)
    bc: Decimal = sum((r["balance_credit"] for r in rows), ZERO)
    return Report(
        f"Neraca saldo per {as_of:%d/%m/%Y}",
        [
            Column("Akun", "account", width=10),
            Column("Nama", "name", width=32),
            Column("Mutasi debit", "debit", "idr"),
            Column("Mutasi kredit", "credit", "idr"),
            Column("Saldo debit", "balance_debit", "idr"),
            Column("Saldo kredit", "balance_credit", "idr"),
        ],
        rows,
        {
            "debit": td,
            "credit": tc,
            "balance_debit": bd,
            "balance_credit": bc,
            "difference": bd - bc,
        },
    )


# ---------------------------------------------------------------- general ledger


async def general_ledger(
    session: AsyncSession,
    account: str,
    date_from: date,
    date_to: date,
    project_id: uuid.UUID | None = None,
) -> Report:
    accs = await _accounts(session)
    if account not in accs:
        from app.core.errors import NotFoundError

        raise NotFoundError("NOT_FOUND", f"Akun {account} tidak ditemukan.")
    acc = accs[account]
    conds = [JournalLine.account_code == account]
    if project_id:
        conds.append(JournalLine.project_id == project_id)
    opening = (
        await session.execute(
            select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(*conds, JournalEntry.entry_date < date_from)
        )
    ).scalar_one()
    bal = Decimal(opening)
    rows = []
    q = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(*conds, JournalEntry.entry_date.between(date_from, date_to))
        .order_by(JournalEntry.entry_date, JournalEntry.number, JournalLine.seq)
    )
    for jl, je in (await session.execute(q)).tuples():
        bal += jl.debit - jl.credit
        rows.append(
            {
                "date": je.entry_date,
                "journal": je.number,
                "source": je.source_number or je.source_type,
                "description": jl.memo or je.description,
                "partner": jl.partner_code,
                "debit": jl.debit,
                "credit": jl.credit,
                "balance": bal,
            }
        )
    return Report(
        f"Buku besar {account} {acc.name} {date_from:%d/%m/%Y} - {date_to:%d/%m/%Y}",
        [
            Column("Tanggal", "date", "date"),
            Column("Jurnal", "journal", width=14),
            Column("Sumber", "source", width=14),
            Column("Keterangan", "description", width=36),
            Column("Mitra", "partner", width=10),
            Column("Debit", "debit", "idr"),
            Column("Kredit", "credit", "idr"),
            Column("Saldo", "balance", "idr"),
        ],
        rows,
        {"opening": Decimal(opening), "closing": bal, "normal_balance": acc.normal_balance},
    )


# ---------------------------------------------------------------- P&L, balance sheet


async def profit_loss(
    session: AsyncSession, month: date, project_id: uuid.UUID | None = None
) -> Report:
    """Month and year-to-date (calendar year) for revenue and expense accounts."""
    accs = await _accounts(session)
    start = month.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    m = await _totals(session, start, end, project_id)
    y = await _totals(session, start.replace(month=1), end, project_id)
    rows = []
    totals = {"revenue": [ZERO, ZERO], "expense": [ZERO, ZERO]}
    for code in sorted(set(m) | set(y)):
        acc = accs.get(code)
        if acc is None or acc.account_type not in ("revenue", "expense"):
            continue
        mv = _signed(acc, *m.get(code, (ZERO, ZERO)))
        yv = _signed(acc, *y.get(code, (ZERO, ZERO)))
        totals[acc.account_type][0] += mv
        totals[acc.account_type][1] += yv
        rows.append(
            {
                "section": "Pendapatan" if acc.account_type == "revenue" else "Beban",
                "account": code,
                "name": acc.name,
                "month": mv,
                "ytd": yv,
            }
        )
    net_m = totals["revenue"][0] - totals["expense"][0]
    net_y = totals["revenue"][1] - totals["expense"][1]
    return Report(
        f"Laba rugi {start:%m/%Y} (bulan & s.d. bulan ini)" + (" - proyek" if project_id else ""),
        [
            Column("Bagian", "section", width=12),
            Column("Akun", "account", width=10),
            Column("Nama", "name", width=32),
            Column("Bulan ini", "month", "idr"),
            Column("Tahun berjalan", "ytd", "idr"),
        ],
        rows,
        {
            "revenue_month": totals["revenue"][0],
            "revenue_ytd": totals["revenue"][1],
            "expense_month": totals["expense"][0],
            "expense_ytd": totals["expense"][1],
            "net_month": net_m,
            "net_ytd": net_y,
        },
    )


async def profit_loss_by_project(session: AsyncSession, date_from: date, date_to: date) -> Report:
    accs = await _accounts(session)
    rows_q = await session.execute(
        select(
            JournalLine.project_id,
            JournalLine.account_code,
            func.sum(JournalLine.debit),
            func.sum(JournalLine.credit),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalEntry.entry_date.between(date_from, date_to), JournalLine.project_id.is_not(None)
        )
        .group_by(JournalLine.project_id, JournalLine.account_code)
    )
    per: dict[uuid.UUID, dict[str, Decimal]] = {}
    for pid, code, d, c in rows_q.tuples():
        acc = accs.get(code)
        if pid is None or acc is None or acc.account_type not in ("revenue", "expense"):
            continue
        bucket = per.setdefault(pid, {"revenue": ZERO, "expense": ZERO})
        bucket[acc.account_type] += _signed(acc, Decimal(d), Decimal(c))
    names = {pr.id: pr for pr in (await session.execute(select(Project))).scalars()}
    rows: list[dict[str, Any]] = []
    for pid, v in per.items():
        p = names.get(pid)
        net = v["revenue"] - v["expense"]
        rows.append(
            {
                "project": p.number if p else str(pid),
                "name": p.name if p else "",
                "revenue": v["revenue"],
                "expense": v["expense"],
                "net": net,
                "margin_pct": (net * 100 / v["revenue"]).quantize(Decimal("0.1"))
                if v["revenue"]
                else None,
            }
        )
    rows.sort(key=lambda r: str(r["project"]))
    return Report(
        f"Laba rugi per proyek {date_from:%d/%m/%Y} - {date_to:%d/%m/%Y}",
        [
            Column("Proyek", "project", width=14),
            Column("Nama", "name", width=30),
            Column("Pendapatan", "revenue", "idr"),
            Column("Beban", "expense", "idr"),
            Column("Laba", "net", "idr"),
            Column("Margin %", "margin_pct", "number"),
        ],
        rows,
        {},
    )


async def balance_sheet(session: AsyncSession, as_of: date) -> Report:
    accs = await _accounts(session)
    t = await _totals(session, None, as_of)
    year_start = as_of.replace(month=1, day=1)
    ytd = await _totals(session, year_start, as_of)
    rows = []
    sums = {"asset": ZERO, "liability": ZERO, "equity": ZERO}
    earnings_all = ZERO
    for code in sorted(t):
        acc = accs.get(code)
        if acc is None:
            continue
        d, c = t[code]
        if acc.account_type in ("revenue", "expense"):
            earnings_all += c - d
            continue
        value = d - c if acc.account_type == "asset" else c - d
        sums[acc.account_type] += value
        rows.append(
            {
                "section": {"asset": "Aset", "liability": "Liabilitas", "equity": "Ekuitas"}[
                    acc.account_type
                ],
                "account": code,
                "name": acc.name,
                "amount": value,
            }
        )
    current = sum(
        (
            (c - d)
            for code, (d, c) in ytd.items()
            if code in accs and accs[code].account_type in ("revenue", "expense")
        ),
        ZERO,
    )
    prior = earnings_all - current
    rows.append(
        {
            "section": "Ekuitas",
            "account": "",
            "name": "Laba ditahan belum ditutup (tahun lalu)",
            "amount": prior,
        }
    )
    rows.append(
        {"section": "Ekuitas", "account": "", "name": "Laba tahun berjalan", "amount": current}
    )
    equity = sums["equity"] + earnings_all
    return Report(
        f"Neraca per {as_of:%d/%m/%Y}",
        [
            Column("Bagian", "section", width=12),
            Column("Akun", "account", width=10),
            Column("Nama", "name", width=36),
            Column("Jumlah", "amount", "idr"),
        ],
        rows,
        {
            "assets": sums["asset"],
            "liabilities": sums["liability"],
            "equity": equity,
            "difference": sums["asset"] - sums["liability"] - equity,
        },
    )


# ---------------------------------------------------------------- cash flow (direct)


def _group(code: str) -> str:
    for label, codes in CASH_GROUPS:
        if code in codes:
            return label
    return "Lainnya"


async def cash_flow(session: AsyncSession, date_from: date, date_to: date) -> Report:
    """Direct method: every movement on the bank accounts, classified by the other side of
    its journal (split pro rata when a journal touches several accounts)."""
    opening = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(JournalLine.account_code.in_(BANK), JournalEntry.entry_date < date_from)
            )
        ).scalar_one()
    )
    entry_ids = (
        select(JournalLine.entry_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.account_code.in_(BANK), JournalEntry.entry_date.between(date_from, date_to)
        )
    )
    lines = list(
        (
            await session.execute(select(JournalLine).where(JournalLine.entry_id.in_(entry_ids)))
        ).scalars()
    )
    by_entry: dict[uuid.UUID, list[JournalLine]] = {}
    for x in lines:
        by_entry.setdefault(x.entry_id, []).append(x)
    flows: dict[str, list[Decimal]] = {}
    for group in by_entry.values():
        cash = sum((x.debit - x.credit for x in group if x.account_code in BANK), ZERO)
        # The counterpart of a bank inflow is on the credit side, of an outflow on the debit side.
        others = [
            x
            for x in group
            if x.account_code not in BANK and (x.credit > 0 if cash > 0 else x.debit > 0)
        ]
        weight = sum((x.debit + x.credit for x in others), ZERO)
        if cash == 0 or weight == 0:
            continue
        allocated = ZERO
        for i, x in enumerate(others):
            share = (
                cash - allocated
                if i == len(others) - 1
                else (cash * (x.debit + x.credit) / weight).quantize(Decimal(1))
            )
            allocated += share
            f = flows.setdefault(_group(x.account_code), [ZERO, ZERO])
            if share >= 0:
                f[0] += share
            else:
                f[1] += -share
    rows: list[dict[str, Any]] = [
        {"category": label, "inflow": v[0], "outflow": v[1], "net": v[0] - v[1]}
        for label, v in sorted(flows.items())
    ]
    net: Decimal = sum((v[0] - v[1] for v in flows.values()), ZERO)
    return Report(
        f"Arus kas (metode langsung) {date_from:%d/%m/%Y} - {date_to:%d/%m/%Y}",
        [
            Column("Kategori", "category", width=30),
            Column("Masuk", "inflow", "idr"),
            Column("Keluar", "outflow", "idr"),
            Column("Bersih", "net", "idr"),
        ],
        rows,
        {"opening": opening, "net": net, "closing": opening + net},
    )


# ---------------------------------------------------------------- dimensions & project P&L

DIMENSIONS = {
    "project": JournalLine.project_id,
    "cost_element": JournalLine.cost_element_code,
    "cost_center": JournalLine.cost_center_code,
    "asset": JournalLine.asset_code,
    "partner": JournalLine.partner_code,
}


async def dimension_report(
    session: AsyncSession,
    dimension: str,
    date_from: date,
    date_to: date,
    account_prefix: str | None,
) -> Report:
    col = DIMENSIONS.get(dimension)
    if col is None:
        from app.core.errors import AppError

        raise AppError("DIMENSION_INVALID", "Dimensi tidak dikenal.", status_code=422)
    q = (
        select(
            col, JournalLine.account_code, func.sum(JournalLine.debit), func.sum(JournalLine.credit)
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalEntry.entry_date.between(date_from, date_to), col.is_not(None))
        .group_by(col, JournalLine.account_code)
        .order_by(col, JournalLine.account_code)
    )
    if account_prefix:
        q = q.where(JournalLine.account_code.startswith(account_prefix))
    accs = await _accounts(session)
    projects = dict((await session.execute(select(Project.id, Project.number))).tuples().all())
    rows = []
    for key, code, d, c in (await session.execute(q)).tuples():
        label = projects.get(key, str(key)) if isinstance(key, uuid.UUID) else str(key)
        rows.append(
            {
                "dimension": label,
                "account": code,
                "name": accs[code].name if code in accs else code,
                "debit": Decimal(d),
                "credit": Decimal(c),
                "net": Decimal(d) - Decimal(c),
            }
        )
    return Report(
        f"Laporan dimensi {dimension} {date_from:%d/%m/%Y} - {date_to:%d/%m/%Y}",
        [
            Column("Dimensi", "dimension", width=16),
            Column("Akun", "account", width=10),
            Column("Nama", "name", width=30),
            Column("Debit", "debit", "idr"),
            Column("Kredit", "credit", "idr"),
            Column("Net (D-K)", "net", "idr"),
        ],
        rows,
        {},
    )


async def project_pnl(session: AsyncSession) -> Report:
    """Management view: DOR revenue (less client disputes) vs actual cost incl. internal rates
    (budget ledger), committed, budget and what remains."""
    projects = list(
        (
            await session.execute(
                select(Project)
                .where(Project.status.in_(("locked", "closed")))
                .order_by(Project.number)
            )
        ).scalars()
    )
    rev = dict(
        (
            await session.execute(
                select(Dor.project_id, func.sum(Dor.revenue))
                .where(Dor.status == "approved")
                .group_by(Dor.project_id)
            )
        )
        .tuples()
        .all()
    )
    disputed = dict(
        (
            await session.execute(
                select(ServiceTicket.project_id, func.sum(TicketLine.amount))
                .join(TicketLine, TicketLine.ticket_id == ServiceTicket.id)
                .where(TicketLine.disputed.is_(True))
                .group_by(ServiceTicket.project_id)
            )
        )
        .tuples()
        .all()
    )
    buckets: dict[tuple[uuid.UUID, str], Decimal] = {
        (pid, b): Decimal(v)
        for pid, b, v in (
            await session.execute(
                select(
                    BudgetLedgerEntry.project_id,
                    BudgetLedgerEntry.bucket,
                    func.sum(BudgetLedgerEntry.amount),
                ).group_by(BudgetLedgerEntry.project_id, BudgetLedgerEntry.bucket)
            )
        ).tuples()
    }
    budgets: dict[uuid.UUID, Decimal] = {}
    for p in projects:
        latest = (
            await session.execute(
                select(func.max(ProjectBudgetLine.version)).where(
                    ProjectBudgetLine.project_id == p.id
                )
            )
        ).scalar_one()
        total = (
            await session.execute(
                select(func.coalesce(func.sum(ProjectBudgetLine.amount), 0)).where(
                    ProjectBudgetLine.project_id == p.id,
                    ProjectBudgetLine.version == (latest or 0),
                    ProjectBudgetLine.cost_element_code != "CONTINGENCY",
                )
            )
        ).scalar_one()
        budgets[p.id] = Decimal(total)
    rows = []
    for p in projects:
        revenue = Decimal(rev.get(p.id) or 0) - Decimal(disputed.get(p.id) or 0)
        actual = buckets.get((p.id, "actual"), ZERO)
        commit = buckets.get((p.id, "commit"), ZERO)
        pre = buckets.get((p.id, "pre_commit"), ZERO)
        budget = budgets[p.id]
        margin = revenue - actual
        rows.append(
            {
                "project": p.number,
                "name": p.name,
                "contract_revenue": p.revenue,
                "dor_revenue": revenue,
                "actual_cost": actual,
                "margin": margin,
                "margin_pct": (margin * 100 / revenue).quantize(Decimal("0.1"))
                if revenue
                else None,
                "committed": commit,
                "pre_committed": pre,
                "budget": budget,
                "remaining": budget - actual - commit - pre,
            }
        )
    return Report(
        "Laba rugi manajemen per proyek",
        [
            Column("Proyek", "project", width=14),
            Column("Nama", "name", width=28),
            Column("Nilai kontrak", "contract_revenue", "idr"),
            Column("Pendapatan DOR", "dor_revenue", "idr"),
            Column("Biaya aktual", "actual_cost", "idr"),
            Column("Margin", "margin", "idr"),
            Column("Margin %", "margin_pct", "number"),
            Column("Commitment", "committed", "idr"),
            Column("Pre-commit", "pre_committed", "idr"),
            Column("Anggaran", "budget", "idr"),
            Column("Sisa anggaran", "remaining", "idr"),
        ],
        rows,
        {},
    )


# ---------------------------------------------------------------- PDF


def to_pdf(report: Report, company: str) -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _t(company), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, _t(report.title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    raw = [max(c.width, 12) for c in report.columns]
    scale = 277 / sum(raw)
    widths = [w * scale for w in raw]
    pdf.set_font("Helvetica", "", 7)

    def cell(v: Any, kind: str) -> str:
        if v is None:
            return ""
        if kind == "idr":
            return format_idr(v).replace("Rp ", "")
        if isinstance(v, date):
            return f"{v:%d/%m/%Y}"
        return _t(str(v))

    with pdf.table(
        col_widths=widths,
        width=277,
        line_height=4,
        text_align=tuple(
            "RIGHT" if c.kind in ("idr", "number") else "LEFT" for c in report.columns
        ),
        headings_style=FontFace(emphasis="BOLD", fill_color=(241, 242, 242)),
    ) as table:
        table.row(tuple(_t(c.header) for c in report.columns))
        for r in report.rows:
            table.row(tuple(cell(r.get(c.key), c.kind) for c in report.columns))
    if report.summary:
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 8)
        for k, v in report.summary.items():
            pdf.cell(
                0,
                4,
                _t(f"{k}: {format_idr(v) if isinstance(v, Decimal) else v}"),
                new_x="LMARGIN",
                new_y="NEXT",
            )
    return bytes(pdf.output())
