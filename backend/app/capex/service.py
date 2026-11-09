"""CAPEX lifecycle (08).

The approved amount becomes a locked `capex` project with one budget line (WBS CAPEX, cost
element CAPEX -> account 1520), so every spend goes through budget_control: PR/PO/GR on the
project (GR posts Dr 1520 through the cost element) or milestone payments recorded here
(Dr 1520 / Cr bank or 2110). Spend above the budget is blocked until a CAPEX change request
is approved (DOA capex on the new total). Capitalisation moves the project's AUC balance to
1510 and creates the asset (internal day rate, useful life, depreciation from next month).
"""

import calendar
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.capex import calc
from app.capex.models import CapexChange, CapexProposal, CapexReview
from app.core.errors import AppError, ConflictError
from app.dms.models import Attachment
from app.finance.models import JournalEntry, JournalLine
from app.master.models import Asset, Vendor
from app.notifications import service as notifications
from app.operations.models import AssetUsage, Dor, DorEquipment
from app.project.models import Project, ProjectBudgetLine, ProjectWbs
from app.services import audit, ledger, numbering
from app.services import budget_control as bc
from app.services.audit import AuditAction
from app.services.numbering import today_jakarta
from app.setup import service as settings_store
from app.treasury import bank_service
from app.treasury.lookup import by_code
from app.workflow import engine
from app.workflow.models import ApprovalRequest

DOC = "capex"
CE = "CAPEX"
WBS = "CAPEX"
RATE_KEY = "capex.discount_rate"
EXECUTING = ("approved", "in_execution")
ZERO = Decimal(0)
STATUS_LABELS = {
    "draft": "Draf",
    "submitted": "Menunggu Direktur",
    "awaiting_rups": "Menunggu RUPS",
    "approved": "Disetujui (rencana terkunci)",
    "in_execution": "Pelaksanaan (AUC)",
    "commissioned": "Commissioning (BAST)",
    "capitalised": "Dikapitalisasi",
    "reviewed": "Ditinjau",
}
INPUTS = (
    "title", "rjpp_ref", "description", "asset_class", "equipment_type_code", "amount", "funding",
    "day_rate", "internal_day_rate", "utilisation_pct", "opex_pct", "life_years", "salvage_pct",
    "rental_annual", "lease_monthly", "strategic_fit", "risk", "tax_group",
)  # fmt: skip


def _rp(v: Decimal) -> str:
    return "Rp " + f"{int(v):,}".replace(",", ".")


async def discount_rate(session: AsyncSession) -> Decimal:
    return Decimal(str(await settings_store.get(session, RATE_KEY, "12") or "12"))


async def rental_spend(session: AsyncSession, until: date | None = None) -> Decimal:
    """Actual equipment rental (5400) of the last 12 months: the 'rent' baseline."""
    until = until or today_jakarta()
    v = (
        await session.execute(
            select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.account_code == "5400",
                JournalEntry.entry_date > until - timedelta(days=365),
                JournalEntry.entry_date <= until,
            )
        )
    ).scalar_one()
    return Decimal(v)


def case_of(p: CapexProposal) -> calc.CaseIn:
    return calc.CaseIn(
        amount=Decimal(p.amount),
        day_rate=Decimal(p.day_rate),
        utilisation_pct=Decimal(p.utilisation_pct),
        opex_pct=Decimal(p.opex_pct),
        life_years=p.life_years,
        salvage_pct=Decimal(p.salvage_pct),
        rental_annual=Decimal(p.rental_annual),
        lease_monthly=Decimal(p.lease_monthly),
        discount_rate=Decimal(p.discount_rate),
        strategic_fit=p.strategic_fit,
        risk=p.risk,
    )


def _validate(data: dict[str, Any]) -> None:
    if Decimal(data["amount"]) <= 0:
        raise AppError("AMOUNT_INVALID", "Nilai investasi harus lebih dari 0.", status_code=422)
    if not 1 <= int(data["life_years"]) <= 40:
        raise AppError("LIFE_INVALID", "Umur ekonomis 1-40 tahun.", status_code=422)
    if not 0 <= Decimal(data["utilisation_pct"]) <= 100:
        raise AppError("UTILISATION_INVALID", "Utilisasi 0-100%.", status_code=422)
    if data["funding"] not in ("equity", "loan", "lease", "mixed"):
        raise AppError("FUNDING_INVALID", "Sumber dana tidak dikenal.", status_code=422)


async def _apply(session: AsyncSession, p: CapexProposal, data: dict[str, Any]) -> None:
    _validate({k: data[k] if k in data else getattr(p, k) for k in INPUTS})
    for k in INPUTS:
        if k in data:
            setattr(p, k, data[k])
    if not p.rental_annual:
        p.rental_annual = await rental_spend(session)
    p.discount_rate = await discount_rate(session)
    out = calc.evaluate(case_of(p))
    p.case, p.priority_score = out.as_dict(), out.priority_score


async def create(session: AsyncSession, actor: Principal, data: dict[str, Any]) -> CapexProposal:
    p = CapexProposal(
        number=await numbering.next(session, "CPX"),
        status="draft",
        created_by=actor.id,
        case={},
        priority_score=ZERO,
        discount_rate=Decimal(12),
    )
    await _apply(session, p, data)
    session.add(p)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=p.id,
        actor_id=actor.id,
        after={"number": p.number, "amount": p.amount, "score": p.priority_score},
    )
    return p


async def update(
    session: AsyncSession, actor: Principal, p: CapexProposal, data: dict[str, Any]
) -> CapexProposal:
    if p.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{p.number} tidak lagi draf.")
    before = {"amount": p.amount, "score": p.priority_score}
    await _apply(session, p, data)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=p.id,
        actor_id=actor.id,
        before=before,
        after={"amount": p.amount, "score": p.priority_score},
    )
    return p


async def submit(session: AsyncSession, actor: Principal, p: CapexProposal) -> ApprovalRequest:
    if p.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{p.number} tidak lagi draf.")
    await _apply(session, p, {})
    req = await engine.submit(
        session,
        actor,
        doc_type=DOC,
        doc_id=p.id,
        doc_number=p.number,
        title=f"CAPEX {p.number}: {p.title[:80]}",
        amount=p.amount,
        context={"kind": "proposal", "npv": p.case.get("npv"), "irr": p.case.get("irr")},
    )
    p.status, p.request_id, p.reject_reason = "submitted", req.id, None
    await session.flush()
    return req


# ---------------------------------------------------------------- approval hooks


async def _lock_plan(session: AsyncSession, p: CapexProposal, by: uuid.UUID | None) -> None:
    """Locked CAPEX plan: a `capex` project with one budget line (budget_control)."""
    project = Project(
        number=p.number,
        name=f"CAPEX {p.title}"[:200],
        company_name="Internal (CAPEX)",
        status="locked",
        project_type="capex",
        revenue=ZERO,
        budget_total=Decimal(p.amount),
        contingency_pct=ZERO,
        owner_id=p.created_by,
        locked_at=datetime.now(UTC),
        created_by=by,
        is_demo=p.is_demo,
    )
    session.add(project)
    await session.flush()
    wbs = ProjectWbs(project_id=project.id, code=WBS, name="Investasi", seq=1)
    session.add(wbs)
    await session.flush()
    session.add(
        ProjectBudgetLine(
            project_id=project.id,
            version=0,
            wbs_id=wbs.id,
            cost_element_code=CE,
            amount=Decimal(p.amount),
            source="capex",
        )
    )
    p.project_id, p.budget = project.id, Decimal(p.amount)
    await session.flush()


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    doc_id = uuid.UUID(request.doc_id)
    acted = [s.acted_by for s in request.steps if s.acted_by]
    by = acted[-1] if acted else None
    p = await session.get(CapexProposal, doc_id, with_for_update=True)
    if p is not None:
        if p.status in ("submitted", "awaiting_rups"):
            await _lock_plan(session, p, by)
            p.status, p.approved_at = "approved", datetime.now(UTC)
            await session.flush()
        return
    ch = await session.get(CapexChange, doc_id, with_for_update=True)
    if ch is None or ch.status != "submitted":
        return
    p = await session.get(CapexProposal, ch.proposal_id, with_for_update=True)
    assert p is not None and p.project_id is not None
    line = (
        await session.execute(
            select(ProjectBudgetLine)
            .where(
                ProjectBudgetLine.project_id == p.project_id,
                ProjectBudgetLine.cost_element_code == CE,
            )
            .with_for_update()
        )
    ).scalar_one()
    line.amount += ch.amount
    project = await session.get(Project, p.project_id, with_for_update=True)
    assert project is not None
    project.budget_total += ch.amount
    p.budget += ch.amount
    ch.status, ch.decided_at = "approved", datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        action="capex_change_approved",
        entity_type=DOC,
        entity_id=p.id,
        actor_id=by,
        after={"change": ch.number, "amount": ch.amount, "budget": p.budget},
    )


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    doc_id = uuid.UUID(request.doc_id)
    acted = [s for s in request.steps if s.acted_by]
    p = await session.get(CapexProposal, doc_id, with_for_update=True)
    if p is not None:
        if p.status in ("submitted", "awaiting_rups"):
            p.status, p.request_id = "draft", None
            p.reject_reason = (acted[-1].comment if acted else None) or None
            await session.flush()
        return
    ch = await session.get(CapexChange, doc_id, with_for_update=True)
    if ch is not None and ch.status == "submitted":
        ch.status, ch.decided_at = "rejected", datetime.now(UTC)
        await session.flush()


async def _on_step(session: AsyncSession, request: ApprovalRequest) -> None:
    """The RUPS step became active: the proposal waits for the shareholders."""
    p = await session.get(CapexProposal, uuid.UUID(request.doc_id), with_for_update=True)
    step = next((s for s in request.steps if s.seq == request.current_seq), None)
    if p is not None and p.status == "submitted" and step and step.approver_role == "shareholders":
        p.status = "awaiting_rups"
        await session.flush()


engine.register_document(
    DOC, on_approved=_on_approved, on_rejected=_on_rejected, on_step_activated=_on_step
)


# ---------------------------------------------------------------- execution


async def _line(session: AsyncSession, p: CapexProposal) -> bc.Line:
    if p.project_id is None or p.status not in EXECUTING:
        raise ConflictError("CAPEX_NOT_EXECUTING", f"{p.number} tidak dalam tahap pelaksanaan.")
    return await bc.resolve(session, p.project_id, WBS, CE)


async def auc_balance(session: AsyncSession, p: CapexProposal) -> Decimal:
    if p.project_id is None:
        return ZERO
    v = (
        await session.execute(
            select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0)).where(
                JournalLine.account_code == "1520", JournalLine.project_id == p.project_id
            )
        )
    ).scalar_one()
    return Decimal(v)


async def milestone(
    session: AsyncSession,
    actor: Principal,
    p: CapexProposal,
    *,
    amount: Decimal,
    on: date,
    description: str,
    vendor_code: str | None,
    pay: str,
    bank_account_id: uuid.UUID | None,
) -> JournalEntry:
    """Vendor milestone on the investment: budget actual (hard stop above the CAPEX budget)
    and Dr 1520 (project) / Cr bank (paid now) or Cr 2110 (vendor payable)."""
    line = await _line(session, p)
    if amount <= 0 or amount != amount.to_integral_value():
        raise AppError("AMOUNT_INVALID", "Nilai harus rupiah bulat > 0.", status_code=422)
    await bc.actualize(
        session, line, amount, doc_type=DOC, doc_id=str(p.id), by=actor.id, note=description[:200]
    )
    dims = ledger.Dims(project_id=p.project_id, wbs_id=line.wbs_id, asset=p.asset_code)
    parts = [ledger.Part("auc", amount, dims, description[:200])]
    accounts: dict[str, str] = {}
    if pay == "bank":
        acc = await bank_service.account_or_default(session, bank_account_id)
        if await bank_service.balance(session, acc) < amount:
            raise ConflictError("INSUFFICIENT_BALANCE", f"Saldo {acc.name} tidak cukup.")
        parts.append(ledger.Part("bank", amount))
        accounts["bank"] = acc.gl_account
    elif pay == "payable":
        if not vendor_code or await by_code(session, Vendor, vendor_code) is None:
            raise AppError("VENDOR_REQUIRED", "Pilih vendor untuk utang termin.", status_code=422)
        parts.append(
            ledger.Part(
                "payable", amount, ledger.Dims(partner_type="vendor", partner_code=vendor_code)
            )
        )
    else:
        raise AppError("PAY_INVALID", "Pembayaran: bank atau payable.", status_code=422)
    entry = await ledger.post_parts(
        session,
        "capex_milestone",
        parts,
        entry_date=on,
        description=f"{p.number} termin: {description[:150]}",
        source_type=DOC,
        source_id=p.id,
        source_number=p.number,
        by=actor.id,
        accounts=accounts,
    )
    if p.status == "approved":
        p.status = "in_execution"
    await session.flush()
    await audit.record(
        session,
        action="post",
        entity_type=DOC,
        entity_id=p.id,
        actor_id=actor.id,
        after={"milestone": format(amount, "f"), "journal": entry.number},
    )
    return entry


async def request_change(
    session: AsyncSession, actor: Principal, p: CapexProposal, amount: Decimal, reason: str
) -> CapexChange:
    if p.status not in EXECUTING:
        raise ConflictError("CAPEX_NOT_EXECUTING", f"{p.number} tidak dalam tahap pelaksanaan.")
    if amount <= 0 or amount != amount.to_integral_value():
        raise AppError("AMOUNT_INVALID", "Nilai harus rupiah bulat > 0.", status_code=422)
    if len(reason.strip()) < 10:
        raise AppError("REASON_REQUIRED", "Tulis alasan (min. 10 karakter).", status_code=422)
    pending = (
        await session.execute(
            select(CapexChange.id).where(
                CapexChange.proposal_id == p.id, CapexChange.status == "submitted"
            )
        )
    ).first()
    if pending:
        raise ConflictError("CHANGE_PENDING", "Masih ada permintaan perubahan yang menunggu.")
    n = (
        await session.execute(
            select(func.count()).select_from(CapexChange).where(CapexChange.proposal_id == p.id)
        )
    ).scalar_one()
    ch = CapexChange(
        number=f"{p.number}-CR{n + 1}",
        proposal_id=p.id,
        amount=amount,
        reason=reason.strip(),
        status="submitted",
        created_by=actor.id,
    )
    session.add(ch)
    await session.flush()
    # DOA on the new total: crossing Rp 5 M brings in the RUPS step.
    req = await engine.submit(
        session,
        actor,
        doc_type=DOC,
        doc_id=ch.id,
        doc_number=ch.number,
        title=f"Perubahan CAPEX {p.number}: +{_rp(amount)}",
        amount=p.budget + amount,
        context={"kind": "change", "increase": format(amount, "f")},
    )
    ch.request_id = req.id
    await session.flush()
    return ch


async def commission(
    session: AsyncSession,
    actor: Principal,
    p: CapexProposal,
    *,
    on: date,
    attachment_id: uuid.UUID,
    asset_code: str,
) -> CapexProposal:
    if p.status not in EXECUTING:
        raise ConflictError("CAPEX_NOT_EXECUTING", f"{p.number} tidak dalam tahap pelaksanaan.")
    att = await session.get(Attachment, attachment_id)
    if att is None or att.entity_type != DOC or att.entity_id != str(p.id):
        raise AppError(
            "BAST_REQUIRED",
            "Unggah BAST commissioning pada CAPEX ini terlebih dahulu.",
            status_code=422,
        )
    if await auc_balance(session, p) <= 0:
        raise ConflictError("AUC_EMPTY", "Belum ada biaya di AUC (1520) untuk CAPEX ini.")
    code = asset_code.strip().upper()
    if await by_code(session, Asset, code) is not None:
        raise ConflictError("ASSET_CODE_TAKEN", f"Kode aset {code} sudah dipakai.")
    p.status, p.commissioned_on, p.bast_attachment_id, p.asset_code = (
        "commissioned",
        on,
        att.id,
        code,
    )
    await session.flush()
    await audit.record(
        session,
        action="commission",
        entity_type=DOC,
        entity_id=p.id,
        actor_id=actor.id,
        after={"on": on.isoformat(), "asset": code},
    )
    return p


async def capitalise(
    session: AsyncSession, actor: Principal, p: CapexProposal, *, on: date
) -> Asset:
    """Dr 1510 / Cr 1520 for the AUC balance; asset created; depreciation from next month."""
    if p.status != "commissioned" or p.asset_code is None:
        raise ConflictError("NOT_COMMISSIONED", "Commissioning (BAST) belum dicatat.")
    cost = await auc_balance(session, p)
    if cost <= 0:
        raise ConflictError("AUC_EMPTY", "AUC kosong.")
    nxt = date(on.year + (on.month == 12), on.month % 12 + 1, 1)
    asset = Asset(
        code=p.asset_code,
        name=p.title[:200],
        asset_class=p.asset_class,
        criticality="A",
        equipment_type_code=p.equipment_type_code,
        internal_day_rate=Decimal(p.internal_day_rate),
        acquisition_cost=cost,
        useful_life_months=p.life_years * 12,
        salvage_value=(cost * Decimal(p.salvage_pct) / 100).quantize(Decimal(1)),
        depreciation_start=nxt,
        tax_group=p.tax_group,
        created_by=actor.id,
        is_demo=p.is_demo,
    )
    session.add(asset)
    await session.flush()
    wbs_id = (await bc.resolve(session, p.project_id, WBS, CE)).wbs_id if p.project_id else None
    entry = await ledger.post_parts(
        session,
        "asset_capitalised",
        [
            ledger.Part("cost", cost, ledger.Dims(asset=asset.code), p.number),
            ledger.Part(
                "auc",
                cost,
                ledger.Dims(asset=asset.code, project_id=p.project_id, wbs_id=wbs_id),
                p.number,
            ),
        ],
        entry_date=on,
        description=f"Kapitalisasi {p.number} -> aset {asset.code}",
        source_type=DOC,
        source_id=p.id,
        source_number=p.number,
        by=actor.id,
    )
    p.status, p.capitalised_on, p.capitalised_cost = "capitalised", on, cost
    p.capitalisation_journal_id = entry.id
    if p.project_id:
        project = await session.get(Project, p.project_id)
        if project is not None:
            project.status = "closed"
    await session.flush()
    await audit.record(
        session,
        action="capitalise",
        entity_type=DOC,
        entity_id=p.id,
        actor_id=actor.id,
        after={"asset": asset.code, "cost": cost, "journal": entry.number},
    )
    return asset


# ---------------------------------------------------------------- post-investment review


def _add_months(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    y, m = k // 12, k % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


async def actuals(session: AsyncSession, p: CapexProposal, months: int) -> dict[str, Any]:
    """Since capitalisation: days the asset worked (approved DORs), revenue, payback vs case."""
    if p.capitalised_on is None or p.asset_code is None:
        raise ConflictError("NOT_CAPITALISED", "CAPEX belum dikapitalisasi.")
    start, end = p.capitalised_on, _add_months(p.capitalised_on, months)
    days_worked = (
        await session.execute(
            select(func.count(func.distinct(AssetUsage.usage_date))).where(
                AssetUsage.asset_code == p.asset_code,
                AssetUsage.usage_date.between(start, end),
                AssetUsage.operating > 0,
            )
        )
    ).scalar_one()
    revenue = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(DorEquipment.revenue), 0))
                .join(Dor, Dor.id == DorEquipment.dor_id)
                .where(
                    DorEquipment.asset_code == p.asset_code,
                    Dor.status == "approved",
                    Dor.report_date.between(start, end),
                )
            )
        ).scalar_one()
    )
    period_days = max((end - start).days, 1)
    utilisation = (Decimal(days_worked) * 100 / period_days).quantize(Decimal("0.1"))
    revenue_annual = (revenue * 365 / period_days).quantize(Decimal(1))
    opex_annual = Decimal(p.case.get("opex_annual") or 0)
    cf = revenue_annual - opex_annual
    payback = (Decimal(p.capitalised_cost) / cf).quantize(Decimal("0.01")) if cf > 0 else None
    return {
        "months": months,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days_worked": int(days_worked),
        "utilisation_pct": format(utilisation, "f"),
        "case_utilisation_pct": format(p.utilisation_pct, "f"),
        "revenue": format(revenue, "f"),
        "revenue_annualised": format(revenue_annual, "f"),
        "case_revenue_annual": p.case.get("revenue_annual"),
        "payback_years": format(payback, "f") if payback is not None else None,
        "case_payback_years": p.case.get("payback_years"),
        "cost": format(p.capitalised_cost, "f"),
        "case_amount": format(p.amount, "f"),
    }


async def review(
    session: AsyncSession, actor: Principal, p: CapexProposal, months: int, comment: str
) -> CapexReview:
    if months not in (6, 12):
        raise AppError("REVIEW_MONTHS", "Tinjauan pada bulan ke-6 atau ke-12.", status_code=422)
    if p.status not in ("capitalised", "reviewed") or p.capitalised_on is None:
        raise ConflictError("NOT_CAPITALISED", "CAPEX belum dikapitalisasi.")
    due = _add_months(p.capitalised_on, months)
    if today_jakarta() < due:
        raise ConflictError(
            "REVIEW_NOT_DUE", f"Tinjauan {months} bulan baru bisa mulai {due:%d/%m/%Y}."
        )
    if len(comment.strip()) < 10:
        raise AppError(
            "COMMENT_REQUIRED", "Tulis kesimpulan tinjauan (min. 10 karakter).", status_code=422
        )
    exists = (
        await session.execute(
            select(CapexReview.id).where(
                CapexReview.proposal_id == p.id, CapexReview.months == months
            )
        )
    ).first()
    if exists:
        raise ConflictError("REVIEW_DONE", f"Tinjauan {months} bulan sudah ada.")
    r = CapexReview(
        proposal_id=p.id,
        months=months,
        actuals=await actuals(session, p, months),
        comment=comment.strip(),
        reviewed_on=today_jakarta(),
        created_by=actor.id,
    )
    session.add(r)
    if months == 12:
        p.status = "reviewed"
    await session.flush()
    await audit.record(
        session,
        action="review",
        entity_type=DOC,
        entity_id=p.id,
        actor_id=actor.id,
        after={
            "months": months,
            **{k: v for k, v in r.actuals.items() if k in ("utilisation_pct", "payback_years")},
        },
    )
    return r


async def review_alerts(session: AsyncSession, today: date | None = None) -> int:
    """Remind the proposer and the Directors when a 6/12-month review is due."""
    today = today or today_jakarta()
    directors = await engine.holders_of_role(session, "director")
    sent = 0
    for p in (
        await session.execute(select(CapexProposal).where(CapexProposal.status == "capitalised"))
    ).scalars():
        assert p.capitalised_on is not None
        done = set(
            (
                await session.execute(
                    select(CapexReview.months).where(CapexReview.proposal_id == p.id)
                )
            ).scalars()
        )
        for months in (6, 12):
            if months in done or today < _add_months(p.capitalised_on, months):
                continue
            users = list({*directors, *([p.created_by] if p.created_by else [])})
            sent += await notifications.notify(
                session,
                users,
                kind="capex_review",
                title=f"Tinjauan pasca-investasi {months} bulan: {p.number}",
                body=p.title[:200],
                link=f"/capex/{p.id}",
                dedupe_key=f"capex-review-{p.id}-{months}",
            )
    return sent


def to_dict(p: CapexProposal) -> dict[str, Any]:
    def m(v: Decimal | None) -> str | None:
        return format(v, "f") if v is not None else None

    out: dict[str, Any] = {
        "id": str(p.id),
        "number": p.number,
        "status": p.status,
        "status_label": STATUS_LABELS.get(p.status, p.status),
        "case": p.case,
        "priority_score": m(p.priority_score),
        "discount_rate": m(p.discount_rate),
        "request_id": str(p.request_id) if p.request_id else None,
        "reject_reason": p.reject_reason,
        "budget": m(p.budget),
        "project_id": str(p.project_id) if p.project_id else None,
        "commissioned_on": p.commissioned_on.isoformat() if p.commissioned_on else None,
        "asset_code": p.asset_code,
        "capitalised_on": p.capitalised_on.isoformat() if p.capitalised_on else None,
        "capitalised_cost": m(p.capitalised_cost),
        "created_by": str(p.created_by) if p.created_by else None,
    }
    for k in INPUTS:
        v = getattr(p, k)
        out[k] = m(v) if isinstance(v, Decimal) else v
    return out
