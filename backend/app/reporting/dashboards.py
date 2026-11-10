"""Dashboards (10): live process map, OKR with yearly targets (setting `okr.targets`), role
dashboards. Every number is computed from live data; cells a user may not open are hidden."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.billing.models import BankLine, CustomerInvoice, ServiceTicket
from app.capex.models import CapexProposal
from app.contract.models import Contract
from app.crm.models import Lead, Opportunity
from app.finance.models import JournalEntry, JournalLine, VendorInvoice
from app.inventory.models import GoodsReceipt, MaterialRequest
from app.lms.models import Assignment
from app.master.models import Asset, Employee, FiscalPeriod
from app.operations.models import AssetUsage, Dor
from app.payroll.models import PayrollRun
from app.procurement.models import PurchaseOrder, PurchaseRequisition
from app.project.models import Project
from app.qhse.models import LOST_TIME, Incident
from app.services import ledger
from app.services.numbering import today_jakarta
from app.setup import service as settings_store
from app.tax.models import TaxReturn
from app.treasury.models import BankAccount, CashAdvance, PaymentRun
from app.workflow.models import ApprovalRequest

ZERO = Decimal(0)
M = 1_000_000
PHASES = ("plan", "commit", "execute", "record", "settle", "review")
LANES = ("revenue", "spend", "people", "finance")
TARGETS_KEY = "okr.targets"
# OKR 2026 (RJPP); later years are set in Settings.
DEFAULT_TARGETS: dict[str, Any] = {
    "revenue": 25_000 * M,
    "new_contracts": 80_000 * M,
    "win_rate_pct": 45,
    "invoice_to_cash_days": 30,
    "cost_overrun_change_pct": -15,
    "utilisation_pct": 85,
    "downtime_pct": 3,
    "net_margin_pct": 10,
    "cash_months_opex": 6,
    "tax_penalties": 0,
    "accidents": 0,
}


async def _count(session: AsyncSession, stmt: Any) -> int:
    return int((await session.execute(stmt)).scalar_one() or 0)


@dataclass(frozen=True)
class Cell:
    lane: str
    phase: str
    key: str
    module: str
    link: str
    stmt: Any
    alert: bool = False  # a non-zero count needs attention


def _cells(today: date) -> list[Cell]:
    c = func.count()
    return [
        Cell(
            "revenue",
            "plan",
            "leads",
            "crm",
            "/lead",
            select(c).select_from(Lead).where(Lead.status.in_(("new", "contacted", "qualified"))),
        ),
        Cell(
            "revenue",
            "commit",
            "opportunities",
            "crm",
            "/peluang",
            select(c)
            .select_from(Opportunity)
            .where(Opportunity.stage.in_(("qualified", "quotation", "submitted"))),
        ),
        Cell(
            "revenue",
            "commit",
            "contracts",
            "contract",
            "/kontrak",
            select(c).select_from(Contract).where(Contract.status == "active"),
        ),
        Cell(
            "revenue",
            "execute",
            "dors_pending",
            "operations",
            "/operasi/dor",
            select(c).select_from(Dor).where(Dor.status == "submitted"),
            True,
        ),
        Cell(
            "revenue",
            "record",
            "tickets_unsigned",
            "billing",
            "/tagihan?tab=tickets",
            select(c)
            .select_from(ServiceTicket)
            .where(ServiceTicket.status == "awaiting_signature"),
            True,
        ),
        Cell(
            "revenue",
            "settle",
            "invoices_overdue",
            "billing",
            "/tagihan?tab=invoices",
            select(c)
            .select_from(CustomerInvoice)
            .where(
                CustomerInvoice.status.in_(("faktur_issued", "sent")),
                CustomerInvoice.due_date < today,
            ),
            True,
        ),
        Cell(
            "revenue",
            "review",
            "bank_unmatched",
            "billing",
            "/tagihan?tab=bank",
            select(c).select_from(BankLine).where(BankLine.status == "unmatched"),
            True,
        ),
        Cell(
            "spend",
            "plan",
            "projects_draft",
            "project",
            "/proyek",
            select(c)
            .select_from(Project)
            .where(Project.status.in_(("draft", "controller_review", "awaiting_approval"))),
        ),
        Cell(
            "spend",
            "commit",
            "pr_pending",
            "procurement",
            "/pengadaan/pr",
            select(c)
            .select_from(PurchaseRequisition)
            .where(PurchaseRequisition.status.in_(("blocked", "awaiting_approval"))),
            True,
        ),
        Cell(
            "spend",
            "commit",
            "po_open",
            "procurement",
            "/pengadaan/po",
            select(c).select_from(PurchaseOrder).where(PurchaseOrder.status == "issued"),
        ),
        Cell(
            "spend",
            "execute",
            "mr_week",
            "inventory",
            "/gudang/mr",
            select(c)
            .select_from(MaterialRequest)
            .where(MaterialRequest.created_at >= today - timedelta(days=7)),
        ),
        Cell(
            "spend",
            "record",
            "gr_draft",
            "inventory",
            "/gudang/gr",
            select(c).select_from(GoodsReceipt).where(GoodsReceipt.status == "draft"),
        ),
        Cell(
            "spend",
            "record",
            "vi_exception",
            "finance",
            "/keuangan/tagihan-vendor",
            select(c).select_from(VendorInvoice).where(VendorInvoice.status == "exception"),
            True,
        ),
        Cell(
            "spend",
            "settle",
            "runs_to_release",
            "treasury",
            "/keuangan/treasury?tab=runs",
            select(c).select_from(PaymentRun).where(PaymentRun.status == "approved"),
            True,
        ),
        Cell(
            "spend",
            "review",
            "capex_open",
            "capex",
            "/capex",
            select(c)
            .select_from(CapexProposal)
            .where(
                CapexProposal.status.in_(
                    ("submitted", "awaiting_rups", "approved", "in_execution", "commissioned")
                )
            ),
        ),
        Cell(
            "people",
            "plan",
            "certs_expiring",
            "master",
            "/pelatihan?tab=compliance",
            select(c)
            .select_from(Assignment)
            .where(Assignment.reason == "certificate_expiry", Assignment.status == "assigned"),
            True,
        ),
        Cell(
            "people",
            "execute",
            "training_overdue",
            "lms",
            "/pelatihan",
            select(c)
            .select_from(Assignment)
            .where(Assignment.status == "assigned", Assignment.due_date < today),
            True,
        ),
        Cell(
            "people",
            "record",
            "advances_open",
            "treasury",
            "/keuangan/treasury?tab=advances",
            select(c)
            .select_from(CashAdvance)
            .where(CashAdvance.status.in_(("disbursed", "settlement_submitted"))),
        ),
        Cell(
            "people",
            "settle",
            "payroll_unpaid",
            "payroll",
            "/keuangan/penggajian",
            select(c)
            .select_from(PayrollRun)
            .where(PayrollRun.status.in_(("calculated", "awaiting_approval", "approved"))),
            True,
        ),
        Cell(
            "people",
            "review",
            "incidents_open",
            "qhse",
            "/qhse",
            select(c).select_from(Incident).where(Incident.status != "closed"),
            True,
        ),
        Cell(
            "finance",
            "commit",
            "approvals_pending",
            "workflow",
            "/persetujuan",
            select(c).select_from(ApprovalRequest).where(ApprovalRequest.status == "pending"),
        ),
        Cell(
            "finance",
            "record",
            "journals_month",
            "finance",
            "/keuangan/buku-besar?tab=journals",
            select(c)
            .select_from(JournalEntry)
            .where(JournalEntry.entry_date >= today.replace(day=1)),
        ),
        Cell(
            "finance",
            "settle",
            "tax_open",
            "tax",
            "/keuangan/pajak",
            select(c)
            .select_from(TaxReturn)
            .where(TaxReturn.status != "filed", TaxReturn.file_due <= today + timedelta(days=7)),
            True,
        ),
        Cell(
            "finance",
            "review",
            "periods_open",
            "finance",
            "/keuangan/tutup-buku",
            select(c).select_from(FiscalPeriod).where(FiscalPeriod.status == "open"),
        ),
    ]


async def process_map(
    session: AsyncSession, p: Principal, today: date | None = None
) -> dict[str, Any]:
    today = today or today_jakarta()
    cells = []
    for cell in _cells(today):
        if not p.can(cell.module, "view"):
            continue
        n = await _count(session, cell.stmt)
        cells.append(
            {
                "lane": cell.lane,
                "phase": cell.phase,
                "key": cell.key,
                "count": n,
                "link": cell.link,
                "attention": cell.alert and n > 0,
            }
        )
    return {"lanes": list(LANES), "phases": list(PHASES), "cells": cells}


# ---------------------------------------------------------------- OKR


async def targets(session: AsyncSession, year: int) -> dict[str, Any]:
    stored = await settings_store.get(session, TARGETS_KEY, {}) or {}
    return {**DEFAULT_TARGETS, **(stored.get(str(year)) or {})}


async def _movement(
    session: AsyncSession, prefixes: tuple[str, ...], start: date, end: date
) -> Decimal:
    """Debit - credit of accounts starting with the prefixes, entries in [start, end]."""
    cond = func.substr(JournalLine.account_code, 1, 1).in_(prefixes)
    v = (
        await session.execute(
            select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(cond, JournalEntry.entry_date.between(start, end))
        )
    ).scalar_one()
    return Decimal(v)


def _pct(a: Decimal, b: Decimal) -> Decimal | None:
    if b == 0:
        return None
    return (a * 100 / b).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


async def _overrun_pct(session: AsyncSession, year: int) -> Decimal | None:
    """Cost overrun of projects locked in the year: sum(max(actual - budget, 0)) / budget."""
    from app.services import budget_control as bc

    rows = (
        await session.execute(
            select(Project.id).where(
                Project.project_type == "operation",
                func.extract("year", Project.locked_at) == year,
            )
        )
    ).scalars()
    over = budget = ZERO
    for pid in rows:
        for _line, _wbs, bal in await bc.project_status(session, pid):
            budget += bal.budget
            over += max(bal.actual - bal.budget, ZERO)
    return _pct(over, budget)


async def okr(session: AsyncSession, year: int, today: date | None = None) -> dict[str, Any]:
    today = today or today_jakarta()
    start, end = date(year, 1, 1), min(date(year, 12, 31), today)
    t = await targets(session, year)
    revenue = -await _movement(session, ("4",), start, end)
    expenses = await _movement(session, ("5", "6", "7"), start, end)
    contracts = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(Contract.value), 0)).where(
                    func.extract("year", Contract.created_at) == year
                )
            )
        ).scalar_one()
    )
    won = await _count(
        session,
        select(func.count())
        .select_from(Opportunity)
        .where(func.extract("year", Opportunity.won_at) == year),
    )
    lost = await _count(
        session,
        select(func.count())
        .select_from(Opportunity)
        .where(func.extract("year", Opportunity.lost_at) == year),
    )
    paid = (
        await session.execute(
            select(func.avg(CustomerInvoice.paid_at - CustomerInvoice.invoice_date)).where(
                CustomerInvoice.status == "paid",
                func.extract("year", CustomerInvoice.paid_at) == year,
            )
        )
    ).scalar_one()
    days_to_cash = Decimal(str(round(float(paid), 1))) if paid is not None else None
    this_over, last_over = await _overrun_pct(session, year), await _overrun_pct(session, year - 1)
    overrun_change = (
        _pct(this_over - last_over, last_over)
        if this_over is not None and last_over not in (None, ZERO)
        else None
    )
    equipment = await _count(
        session,
        select(func.count())
        .select_from(Asset)
        .where(Asset.is_active.is_(True), Asset.equipment_type_code.is_not(None)),
    )
    worked = await _count(
        session,
        select(
            func.count(func.distinct(func.concat(AssetUsage.asset_code, AssetUsage.usage_date)))
        ).where(AssetUsage.usage_date.between(start, end), AssetUsage.operating > 0),
    )
    days = (end - start).days + 1
    utilisation = _pct(Decimal(worked), Decimal(equipment * days)) if equipment else None
    hours = (
        await session.execute(
            select(
                func.coalesce(func.sum(AssetUsage.breakdown), 0),
                func.coalesce(
                    func.sum(AssetUsage.operating + AssetUsage.standby + AssetUsage.breakdown), 0
                ),
            ).where(AssetUsage.usage_date.between(start, end))
        )
    ).one()
    downtime = _pct(Decimal(hours[0]), Decimal(hours[1]))
    accounts = list(
        (
            await session.execute(select(BankAccount).where(BankAccount.is_active.is_(True)))
        ).scalars()
    )
    cash = sum([await ledger.balance(session, a.gl_account) for a in accounts], ZERO)
    q_start = today - timedelta(days=90)
    opex_month = (await _movement(session, ("5", "6"), q_start, today)) / 3
    cash_months = (cash / opex_month).quantize(Decimal("0.1")) if opex_month > 0 else None
    late_tax = await _count(
        session,
        select(func.count())
        .select_from(TaxReturn)
        .where(
            TaxReturn.year == year,
            ((TaxReturn.paid_on > TaxReturn.pay_due) | (TaxReturn.filed_on > TaxReturn.file_due)),
        ),
    )
    accidents = await _count(
        session,
        select(func.count())
        .select_from(Incident)
        .where(
            Incident.category.in_(LOST_TIME), func.extract("year", Incident.occurred_on) == year
        ),
    )

    def row(key: str, actual: Any, target: Any, better: str, unit: str) -> dict[str, Any]:
        status = "n/a"
        if actual is not None:
            a, b = Decimal(str(actual)), Decimal(str(target))
            ok = a >= b if better == "higher" else a <= b
            status = "on_track" if ok else "off_track"
        return {
            "key": key,
            "actual": None if actual is None else format(Decimal(str(actual)), "f"),
            "target": format(Decimal(str(target)), "f"),
            "better": better,
            "unit": unit,
            "status": status,
        }

    # Revenue is judged against the year-to-date share of the yearly target.
    ytd_share = Decimal((end - start).days + 1) / Decimal(366 if year % 4 == 0 else 365)
    rev_target_ytd = (Decimal(t["revenue"]) * ytd_share).quantize(Decimal(1))
    return {
        "year": year,
        "as_of": end.isoformat(),
        "rows": [
            {
                **row("revenue", revenue, rev_target_ytd, "higher", "idr"),
                "year_target": str(t["revenue"]),
            },
            row("new_contracts", contracts, t["new_contracts"], "higher", "idr"),
            row(
                "win_rate_pct",
                _pct(Decimal(won), Decimal(won + lost)),
                t["win_rate_pct"],
                "higher",
                "pct",
            ),
            row("invoice_to_cash_days", days_to_cash, t["invoice_to_cash_days"], "lower", "days"),
            row(
                "cost_overrun_change_pct",
                overrun_change,
                t["cost_overrun_change_pct"],
                "lower",
                "pct",
            ),
            row("utilisation_pct", utilisation, t["utilisation_pct"], "higher", "pct"),
            row("downtime_pct", downtime, t["downtime_pct"], "lower", "pct"),
            row(
                "net_margin_pct",
                _pct(revenue - expenses, revenue),
                t["net_margin_pct"],
                "higher",
                "pct",
            ),
            row("cash_months_opex", cash_months, t["cash_months_opex"], "higher", "x"),
            row("tax_penalties", late_tax, t["tax_penalties"], "lower", "count"),
            row("accidents", accidents, t["accidents"], "lower", "count"),
        ],
        "figures": {
            "revenue": format(revenue, "f"),
            "expenses": format(expenses, "f"),
            "cash": format(cash, "f"),
            "won": won,
            "lost": lost,
        },
    }


# ---------------------------------------------------------------- role dashboards

ROLE_DASHBOARDS = {
    "director": ("director", "head_of_finance", "super_admin"),
    "sales": ("head_of_sales", "account_executive", "tender_specialist"),
    "operation": (
        "head_of_operation",
        "ofs_superintendent",
        "epcom_superintendent",
        "lead_engineer",
    ),
    "finance": (
        "lead_controller",
        "head_of_finance",
        "finance_officer",
        "ap_accountant",
        "cashier",
        "tax_specialist",
    ),
    "hc": ("hcbp_officer", "qhse_coordinator"),
}


def dashboards_for(p: Principal) -> list[str]:
    return [k for k, roles in ROLE_DASHBOARDS.items() if p.role_codes & set(roles)]


async def role_tiles(
    session: AsyncSession, kind: str, today: date | None = None
) -> list[dict[str, Any]]:
    today = today or today_jakarta()
    tiles: list[dict[str, Any]] = []

    def tile(
        key: str, value: Any, unit: str = "count", link: str | None = None, tone: str = "neutral"
    ) -> None:
        tiles.append(
            {
                "key": key,
                "value": format(value, "f") if isinstance(value, Decimal) else value,
                "unit": unit,
                "link": link,
                "tone": tone,
            }
        )

    if kind in ("director", "finance"):
        from app.billing.receipt_service import cash_kpis
        from app.treasury import forecast

        k = await cash_kpis(session, today)
        fc = await forecast.build(session, today)
        accounts = list(
            (
                await session.execute(select(BankAccount).where(BankAccount.is_active.is_(True)))
            ).scalars()
        )
        tile(
            "cash",
            sum([await ledger.balance(session, a.gl_account) for a in accounts], ZERO),
            "idr",
            "/keuangan/treasury",
        )
        tile(
            "lowest_13w",
            Decimal(fc["lowest"]),
            "idr",
            "/keuangan/treasury?tab=forecast",
            "danger" if Decimal(fc["lowest"]) < 0 else "neutral",
        )
        tile("ar_open", Decimal(str(k.get("ar_balance") or 0)), "idr", "/tagihan?tab=aging")
        tile("dso", k.get("dso_days"), "days", "/tagihan?tab=aging")
        ap_due = (
            await session.execute(
                select(
                    func.coalesce(func.sum(VendorInvoice.payable - VendorInvoice.paid_amount), 0)
                ).where(
                    VendorInvoice.status == "approved",
                    VendorInvoice.due_date <= today + timedelta(days=7),
                )
            )
        ).scalar_one()
        tile("ap_due_7d", Decimal(ap_due), "idr", "/keuangan/treasury?tab=runs")
    if kind == "finance":
        tile(
            "tax_due_7d",
            await _count(
                session,
                select(func.count())
                .select_from(TaxReturn)
                .where(
                    TaxReturn.status != "filed", TaxReturn.file_due <= today + timedelta(days=7)
                ),
            ),
            link="/keuangan/pajak",
        )
        tile(
            "bank_unreconciled",
            await _count(
                session,
                select(func.count())
                .select_from(BankLine)
                .where(BankLine.journal_line_id.is_(None)),
            ),
            link="/keuangan/treasury",
        )
    if kind in ("director", "sales"):
        pipeline = (
            await session.execute(
                select(func.count(), func.coalesce(func.sum(Opportunity.value), 0)).where(
                    Opportunity.stage.in_(("qualified", "quotation", "submitted"))
                )
            )
        ).one()
        tile("pipeline_count", int(pipeline[0]), link="/peluang")
        tile("pipeline_value", Decimal(pipeline[1]), "idr", "/peluang")
    if kind in ("director", "operation"):
        tile(
            "dors_pending",
            await _count(
                session, select(func.count()).select_from(Dor).where(Dor.status == "submitted")
            ),
            link="/operasi/dor",
            tone="warning",
        )
        tile(
            "dors_late",
            await _count(
                session,
                select(func.count())
                .select_from(Dor)
                .where(Dor.late.is_(True), Dor.report_date >= today - timedelta(days=30)),
            ),
            link="/operasi/dor",
            tone="danger",
        )
        tile(
            "projects_locked",
            await _count(
                session,
                select(func.count())
                .select_from(Project)
                .where(Project.status == "locked", Project.project_type == "operation"),
            ),
            link="/proyek",
        )
    if kind in ("director", "hc"):
        tile(
            "employees",
            await _count(
                session,
                select(func.count()).select_from(Employee).where(Employee.is_active.is_(True)),
            ),
            link="/master/employees",
        )
        tile(
            "training_overdue",
            await _count(
                session,
                select(func.count())
                .select_from(Assignment)
                .where(Assignment.status == "assigned", Assignment.due_date < today),
            ),
            link="/pelatihan",
            tone="warning",
        )
        tile(
            "certs_expiring",
            await _count(
                session,
                select(func.count())
                .select_from(Assignment)
                .where(Assignment.reason == "certificate_expiry", Assignment.status == "assigned"),
            ),
            link="/pelatihan?tab=compliance",
            tone="warning",
        )
    if kind == "hc":
        last = (
            await session.execute(
                select(PayrollRun)
                .order_by(PayrollRun.year.desc(), PayrollRun.month.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        tile(
            "payroll_status",
            f"{last.month:02d}/{last.year} {last.status}" if last else "-",
            "text",
            "/keuangan/penggajian",
        )
    return tiles
