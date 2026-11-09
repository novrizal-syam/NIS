"""Payroll runs (07c; PROCESS.md · Payroll; ACCOUNTING.md · Payroll approved).

Calculate (HCBP) -> submit -> DOA payroll (Head of Finance & Support; the calculator never
approves) -> journal: employer cost (gross + employer BPJS) to 5100 per project by DOR days
for field staff, 6100 for office staff; Cr 2310 net per employee, 2220 PPh 21, 2240 BPJS
(employee + employer), 1120 deductions -> paid through a payment run (treasury, 07b).

Site days and overtime come from approved DORs (payroll_days) not yet used by another run, up
to the cut-off; HCBP can edit them with a reason. Project budgets are NOT charged again: DOR
approval already charged manpower at internal rates (ACCOUNTING.md: internal rates for
management reporting, ledger cost through payroll).
"""

import calendar
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.master.models import Employee
from app.operations.models import Dor, PayrollDay
from app.payroll import calc
from app.payroll.models import PayrollRun, Payslip, PayslipDay, PayslipItem, Pph21TerRate
from app.payroll.seed import DEFAULT_RULES, TER_CATEGORY
from app.services import audit, ledger
from app.services.audit import AuditAction
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest, ApprovalStep

DOC = "payroll"
RULES_KEY = "payroll.rules"
ZERO = Decimal(0)
DONE = ("approved", "paid")
STATUS_LABELS = {
    "calculated": "Dihitung",
    "awaiting_approval": "Menunggu persetujuan",
    "approved": "Disetujui",
    "paid": "Dibayar",
}


async def rules(session: AsyncSession) -> dict[str, Any]:
    stored = await settings_store.get(session, RULES_KEY, {}) or {}
    out = {**DEFAULT_RULES, **stored}
    out["bpjs"] = {**DEFAULT_RULES["bpjs"], **(stored.get("bpjs") or {})}  # type: ignore[dict-item]
    out["ptkp"] = {**DEFAULT_RULES["ptkp"], **(stored.get("ptkp") or {})}  # type: ignore[dict-item]
    return out


async def ter_bands(session: AsyncSession, category: str) -> list[tuple[Decimal | None, Decimal]]:
    rows = (
        await session.execute(
            select(Pph21TerRate.upper, Pph21TerRate.rate)
            .where(Pph21TerRate.category == category)
            .order_by(Pph21TerRate.seq)
        )
    ).all()
    if not rows:
        raise AppError(
            "TER_TABLE_MISSING", f"Tabel TER kategori {category} belum diisi.", status_code=422
        )
    return [(u, r) for u, r in rows]


def period(year: int, month: int, cutoff: int) -> tuple[date, date]:
    """(previous month's cut-off + 1, this month's cut-off), cut-off clamped to month end."""
    end = date(year, month, min(cutoff, calendar.monthrange(year, month)[1]))
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    prev_end = date(py, pm, min(cutoff, calendar.monthrange(py, pm)[1]))
    return prev_end + timedelta(days=1), end


def ter_category(ptkp_status: str) -> str:
    return TER_CATEGORY.get(ptkp_status, "A")


# ---------------------------------------------------------------- calculation


async def _days_from_dor(session: AsyncSession, ps: Payslip, run: PayrollRun) -> list[PayslipDay]:
    """Approved DOR days of the employee up to the cut-off not used by another run (late DORs
    from an earlier period are picked up by the next run)."""
    used = (
        select(PayslipDay.payroll_day_id)
        .join(Payslip, Payslip.id == PayslipDay.payslip_id)
        .where(PayslipDay.payroll_day_id.is_not(None), Payslip.run_id != run.id)
    )
    rows = (
        await session.execute(
            select(PayrollDay, Dor.wbs_id)
            .join(Dor, Dor.id == PayrollDay.dor_id)
            .where(
                PayrollDay.employee_code == ps.employee_code,
                PayrollDay.work_date <= run.period_end,
                PayrollDay.id.not_in(used),
            )
            .order_by(PayrollDay.work_date)
        )
    ).all()
    return [
        PayslipDay(
            payslip_id=ps.id,
            work_date=pd.work_date,
            project_id=pd.project_id,
            wbs_id=wbs_id,
            payroll_day_id=pd.id,
            overtime_hours=pd.overtime_hours,
            source="dor",
        )
        for pd, wbs_id in rows
    ]


async def days_of(session: AsyncSession, payslip_id: uuid.UUID) -> list[PayslipDay]:
    return list(
        (
            await session.execute(
                select(PayslipDay)
                .where(PayslipDay.payslip_id == payslip_id)
                .order_by(PayslipDay.work_date)
            )
        ).scalars()
    )


async def items_of(session: AsyncSession, payslip_id: uuid.UUID) -> list[PayslipItem]:
    return list(
        (
            await session.execute(select(PayslipItem).where(PayslipItem.payslip_id == payslip_id))
        ).scalars()
    )


async def _year_before(
    session: AsyncSession, run: PayrollRun, employee_code: str
) -> tuple[Decimal, Decimal, Decimal, int]:
    """Taxable gross, pension (JHT+JP employee) and PPh 21 of approved runs earlier this year."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(Payslip.taxable), 0),
                func.coalesce(func.sum(Payslip.jht_ee + Payslip.jp_ee), 0),
                func.coalesce(func.sum(Payslip.pph21), 0),
                func.count(),
            )
            .join(PayrollRun, PayrollRun.id == Payslip.run_id)
            .where(
                Payslip.employee_code == employee_code,
                PayrollRun.year == run.year,
                PayrollRun.month < run.month,
                PayrollRun.status.in_(DONE),
            )
        )
    ).one()
    return Decimal(row[0]), Decimal(row[1]), Decimal(row[2]), int(row[3])


async def compute(
    session: AsyncSession, run: PayrollRun, ps: Payslip, r: dict[str, Any]
) -> Payslip:
    """All amounts of one payslip from its master data snapshot, days and items."""
    days = await days_of(session, ps.id)
    items = await items_of(session, ps.id)
    ps.site_days = len(days)
    ps.field_allowance = calc.rp(Decimal(ps.site_days) * calc.d(r["field_allowance_per_day"]))
    ps.overtime_hours = sum((Decimal(x.overtime_hours) for x in days), ZERO)
    ps.overtime_factor_hours = calc.overtime_factor_hours(
        [Decimal(x.overtime_hours) for x in days],
        calc.d(r["overtime_first_hour_factor"]),
        calc.d(r["overtime_next_hours_factor"]),
    )
    ps.overtime_pay = calc.rp(
        Decimal(ps.basic) / calc.d(r["overtime_divisor"]) * ps.overtime_factor_hours
    )
    allowances = [x for x in items if x.kind == "allowance"]
    ps.other_allowances = sum((Decimal(x.amount) for x in allowances), ZERO)
    untaxed = sum((Decimal(x.amount) for x in allowances if not x.taxable), ZERO)
    ps.deductions = sum((Decimal(x.amount) for x in items if x.kind == "deduction"), ZERO)
    ps.gross = (
        Decimal(ps.basic)
        + Decimal(ps.fixed_allowance)
        + ps.field_allowance
        + ps.overtime_pay
        + ps.other_allowances
    )
    b = calc.bpjs(Decimal(ps.basic) + Decimal(ps.fixed_allowance), r["bpjs"])
    ps.kes_er, ps.kes_ee, ps.jht_er, ps.jht_ee = b.kes_er, b.kes_ee, b.jht_er, b.jht_ee
    ps.jp_er, ps.jp_ee, ps.jkk_er, ps.jkm_er = b.jp_er, b.jp_ee, b.jkk_er, b.jkm_er
    # Employer-paid JKK, JKM and BPJS Kesehatan are income for PPh 21; JHT/JP employer are not.
    ps.taxable = ps.gross - untaxed + b.kes_er + b.jkk_er + b.jkm_er
    surcharge = (calc.HUNDRED + calc.d(r["no_npwp_surcharge_pct"])) / calc.HUNDRED
    if run.month == 12:
        gross_y, pension_y, withheld, months = await _year_before(session, run, ps.employee_code)
        a = calc.annual(
            gross_year=gross_y + ps.taxable,
            pension_year=pension_y + b.jht_ee + b.jp_ee,
            withheld_before=withheld,
            months=months + 1,
            ptkp=calc.d(r["ptkp"].get(ps.ptkp_status, r["ptkp"]["TK/0"])),
            rules=r,
            has_tax_id=ps.has_tax_id,
        )
        ps.ter_rate, ps.pph21, ps.annual = ZERO, a.december, a.as_dict()
    else:
        ps.ter_rate = calc.ter_rate(await ter_bands(session, ps.ter_category), ps.taxable)
        tax = calc.tax_rp(ps.taxable * ps.ter_rate / calc.HUNDRED)
        ps.pph21 = tax if ps.has_tax_id else calc.tax_rp(tax * surcharge)
        ps.annual = None
    ps.net = ps.gross - b.employee - ps.pph21 - ps.deductions
    ps.employer_cost = ps.gross + b.employer
    # Field cost to projects by site days (per project and WBS).
    if ps.is_field and days:
        keys: dict[tuple[uuid.UUID, uuid.UUID | None], int] = {}
        for x in days:
            k = (x.project_id, x.wbs_id)
            keys[k] = keys.get(k, 0) + 1
        split = calc.allocate(ps.employer_cost, list(keys.values()))
        ps.allocation = [
            {
                "project_id": str(p),
                "wbs_id": str(w) if w else None,
                "days": n,
                "amount": format(a_, "f"),
            }
            for (p, w), n, a_ in zip(keys, keys.values(), split, strict=True)
        ]
    else:
        ps.allocation = []
    return ps


async def payslips_of(session: AsyncSession, run_id: uuid.UUID) -> list[Payslip]:
    return list(
        (
            await session.execute(
                select(Payslip).where(Payslip.run_id == run_id).order_by(Payslip.employee_code)
            )
        ).scalars()
    )


def _totals(run: PayrollRun, slips: list[Payslip]) -> None:
    run.employees = len(slips)
    run.gross = sum((s.gross for s in slips), ZERO)
    run.employer_bpjs = sum(
        (s.kes_er + s.jht_er + s.jp_er + s.jkk_er + s.jkm_er for s in slips), ZERO
    )
    run.employee_bpjs = sum((s.kes_ee + s.jht_ee + s.jp_ee for s in slips), ZERO)
    run.pph21 = sum((s.pph21 for s in slips), ZERO)
    run.deductions = sum((s.deductions for s in slips), ZERO)
    run.net = sum((s.net for s in slips), ZERO)
    run.employer_cost = sum((s.employer_cost for s in slips), ZERO)


async def recompute_run(session: AsyncSession, run: PayrollRun) -> PayrollRun:
    r = await rules(session)
    slips = await payslips_of(session, run.id)
    for ps in slips:
        await compute(session, run, ps, r)
    await session.flush()
    _totals(run, slips)
    await session.flush()
    return run


async def calculate(
    session: AsyncSession, actor: Principal, year: int, month: int, *, reload: bool = True
) -> PayrollRun:
    """Create the run for the month (or refresh it while still `calculated`): one payslip per
    active employee with a basic salary; with `reload`, days are re-read from approved DORs
    (HCBP day edits are discarded) and master data is snapshotted again."""
    if not 1 <= month <= 12:
        raise AppError("PERIOD_INVALID", "Bulan harus 1-12.", status_code=422)
    r = await rules(session)
    run = (
        await session.execute(
            select(PayrollRun)
            .where(PayrollRun.year == year, PayrollRun.month == month)
            .with_for_update()
        )
    ).scalar_one_or_none()
    start, end = period(year, month, int(r["cutoff_day"]))
    pay_day = min(int(r["pay_day"]), calendar.monthrange(year, month)[1])
    if run is None:
        prior_open = (
            await session.execute(
                select(PayrollRun.id).where(
                    PayrollRun.status.not_in(DONE),
                    (PayrollRun.year * 12 + PayrollRun.month) < year * 12 + month,
                )
            )
        ).first()
        if prior_open:
            raise ConflictError("PRIOR_RUN_OPEN", "Penggajian bulan sebelumnya belum disetujui.")
        run = PayrollRun(
            year=year,
            month=month,
            period_start=start,
            period_end=end,
            pay_date=date(year, month, pay_day),
            status="calculated",
            created_by=actor.id,
        )
        session.add(run)
        await session.flush()
    elif run.status != "calculated":
        raise ConflictError(
            "RUN_LOCKED", f"Penggajian {month:02d}/{year} sudah {STATUS_LABELS[run.status]}."
        )
    elif not reload:
        run.calculated_by, run.calculated_at = actor.id, datetime.now(UTC)
        return await recompute_run(session, run)

    for old in await payslips_of(session, run.id):
        await session.delete(old)
    await session.flush()
    employees = list(
        (
            await session.execute(
                select(Employee)
                .where(
                    Employee.is_active.is_(True),
                    Employee.basic_salary > 0,
                    (Employee.join_date.is_(None)) | (Employee.join_date <= end),
                )
                .order_by(Employee.code)
            )
        ).scalars()
    )
    for e in employees:
        ps = Payslip(
            run_id=run.id,
            employee_code=e.code,
            employee_name=e.full_name,
            position=e.position,
            is_field=e.is_field,
            ptkp_status=e.ptkp_status,
            ter_category=ter_category(e.ptkp_status),
            has_tax_id=bool(e.npwp or e.nik),
            basic=Decimal(e.basic_salary or 0),
            fixed_allowance=Decimal(e.fixed_allowance or 0),
        )
        session.add(ps)
        await session.flush()
        session.add_all(await _days_from_dor(session, ps, run))
    await session.flush()
    run.calculated_by, run.calculated_at = actor.id, datetime.now(UTC)
    run.reject_reason = None
    await recompute_run(session, run)
    await audit.record(
        session,
        action="calculate",
        entity_type=DOC,
        entity_id=run.id,
        actor_id=actor.id,
        after={"period": f"{year}-{month:02d}", "employees": run.employees, "net": run.net},
    )
    return run


def _editable(run: PayrollRun) -> None:
    if run.status != "calculated":
        raise ConflictError("RUN_LOCKED", "Penggajian hanya dapat diubah saat berstatus Dihitung.")


async def set_days(
    session: AsyncSession,
    actor: Principal,
    ps: Payslip,
    days: list[dict[str, Any]],
    reason: str,
) -> Payslip:
    """HCBP replaces the timesheet of one payslip (with a reason, audited). Days that match a
    DOR day keep their link; others are manual."""
    run = await session.get(PayrollRun, ps.run_id, with_for_update=True)
    assert run is not None
    _editable(run)
    if len(reason.strip()) < 5:
        raise AppError(
            "REASON_REQUIRED", "Tulis alasan perubahan (min. 5 karakter).", status_code=422
        )
    old = await days_of(session, ps.id)
    by_date = {x.work_date: x for x in old}
    seen: set[date] = set()
    before = [
        {"date": x.work_date.isoformat(), "project": str(x.project_id), "ot": str(x.overtime_hours)}
        for x in old
    ]
    new: list[PayslipDay] = []
    for raw in days:
        wd = raw["work_date"]
        if wd in seen:
            raise AppError("DAY_DUPLICATE", f"Tanggal {wd:%d/%m/%Y} dua kali.", status_code=422)
        seen.add(wd)
        if wd > run.period_end:
            raise AppError(
                "DAY_OUT_OF_PERIOD",
                f"Tanggal {wd:%d/%m/%Y} setelah cut-off {run.period_end:%d/%m/%Y}.",
                status_code=422,
            )
        ot = Decimal(raw.get("overtime_hours") or 0)
        if ot < 0 or ot > 24:
            raise AppError("OVERTIME_INVALID", "Jam lembur 0-24 per hari.", status_code=422)
        prev = by_date.get(wd)
        same = (
            prev is not None
            and prev.project_id == raw["project_id"]
            and Decimal(prev.overtime_hours) == ot
        )
        new.append(
            PayslipDay(
                payslip_id=ps.id,
                work_date=wd,
                project_id=raw["project_id"],
                wbs_id=raw.get("wbs_id") or (prev.wbs_id if prev else None),
                payroll_day_id=prev.payroll_day_id if prev else None,
                overtime_hours=ot,
                source=prev.source if same and prev else "manual",
                note=None if same else reason.strip()[:300],
            )
        )
    for x in old:
        await session.delete(x)
    await session.flush()
    session.add_all(new)
    await session.flush()
    await recompute_run(session, run)
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="payslip_days",
        entity_id=ps.id,
        actor_id=actor.id,
        before={"days": before},
        after={
            "days": [
                {
                    "date": x.work_date.isoformat(),
                    "project": str(x.project_id),
                    "ot": str(x.overtime_hours),
                }
                for x in new
            ]
        },
        note=reason.strip(),
    )
    return ps


async def set_items(
    session: AsyncSession, actor: Principal, ps: Payslip, items: list[dict[str, Any]]
) -> Payslip:
    run = await session.get(PayrollRun, ps.run_id, with_for_update=True)
    assert run is not None
    _editable(run)
    before = [
        {"kind": x.kind, "name": x.name, "amount": str(x.amount)}
        for x in await items_of(session, ps.id)
    ]
    for x in await items_of(session, ps.id):
        await session.delete(x)
    await session.flush()
    for raw in items:
        amount = Decimal(raw["amount"])
        if amount <= 0 or amount != amount.to_integral_value():
            raise AppError("AMOUNT_INVALID", "Nilai harus rupiah bulat > 0.", status_code=422)
        session.add(
            PayslipItem(
                payslip_id=ps.id,
                kind=raw["kind"],
                name=str(raw["name"]).strip()[:120],
                amount=amount,
                taxable=bool(raw.get("taxable", True)) if raw["kind"] == "allowance" else False,
            )
        )
    await session.flush()
    await recompute_run(session, run)
    if ps.net < 0:
        raise AppError(
            "NET_NEGATIVE", f"Gaji bersih {ps.employee_name} menjadi negatif.", status_code=422
        )
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="payslip_items",
        entity_id=ps.id,
        actor_id=actor.id,
        before={"items": before},
        after={"items": [{**i, "amount": str(i["amount"])} for i in items]},
    )
    return ps


# ---------------------------------------------------------------- approval and journal


async def submit(session: AsyncSession, actor: Principal, run: PayrollRun) -> ApprovalRequest:
    _editable(run)
    if run.employees == 0:
        raise AppError("RUN_EMPTY", "Tidak ada karyawan dalam penggajian ini.", status_code=422)
    negative = [s.employee_name for s in await payslips_of(session, run.id) if s.net < 0]
    if negative:
        raise AppError(
            "NET_NEGATIVE", f"Gaji bersih negatif: {', '.join(negative)}.", status_code=422
        )
    req = await engine.submit(
        session,
        actor,
        doc_type=DOC,
        doc_id=run.id,
        doc_number=f"GAJI-{run.year}-{run.month:02d}",
        title=f"Penggajian {run.month:02d}/{run.year}: {run.employees} karyawan",
        amount=run.employer_cost,
    )
    run.status, run.request_id, run.reject_reason = "awaiting_approval", req.id, None
    await session.flush()
    return req


async def _before_approve(
    session: AsyncSession, request: ApprovalRequest, _step: ApprovalStep, principal: Principal
) -> None:
    run = await session.get(PayrollRun, uuid.UUID(request.doc_id))
    if run is not None and principal.id in {run.calculated_by, run.created_by}:
        raise ForbiddenError(
            "SOD_PAYROLL_CALCULATOR", "Penghitung penggajian tidak dapat menyetujuinya."
        )


def journal_parts(slips: list[Payslip]) -> list[ledger.Part]:
    parts: list[ledger.Part] = []
    pph21 = bpjs = ZERO
    for s in slips:
        emp = ledger.Dims(partner_type="employee", partner_code=s.employee_code)
        if s.allocation:
            for a in s.allocation:
                parts.append(
                    ledger.Part(
                        "field_cost",
                        Decimal(a["amount"]),
                        ledger.Dims(
                            project_id=uuid.UUID(a["project_id"]),
                            wbs_id=uuid.UUID(a["wbs_id"]) if a["wbs_id"] else None,
                            cost_element="MANPOWER",
                        ),
                        s.employee_code,
                    )
                )
        elif s.is_field:
            parts.append(ledger.Part("field_cost", s.employer_cost, None, s.employee_code))
        else:
            parts.append(ledger.Part("office_cost", s.employer_cost, None, s.employee_code))
        parts.append(ledger.Part("net_salary", s.net, emp, s.employee_code))
        if s.deductions:
            parts.append(ledger.Part("deductions", s.deductions, emp, s.employee_code))
        pph21 += s.pph21
        bpjs += s.kes_er + s.jht_er + s.jp_er + s.jkk_er + s.jkm_er
        bpjs += s.kes_ee + s.jht_ee + s.jp_ee
    parts.append(ledger.Part("pph21", pph21))
    parts.append(ledger.Part("bpjs", bpjs))
    return parts


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    run = await session.get(PayrollRun, uuid.UUID(request.doc_id), with_for_update=True)
    if run is None or run.status != "awaiting_approval":
        return
    acted = [s.acted_by for s in request.steps if s.acted_by]
    slips = await payslips_of(session, run.id)
    entry = await ledger.post_parts(
        session,
        "payroll",
        journal_parts(slips),
        entry_date=run.period_end,
        description=f"Penggajian {run.month:02d}/{run.year} ({run.employees} karyawan)",
        source_type=DOC,
        source_id=run.id,
        source_number=f"GAJI-{run.year}-{run.month:02d}",
        by=acted[-1] if acted else None,
    )
    run.status, run.journal_id, run.approved_at = "approved", entry.id, datetime.now(UTC)
    await session.flush()


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    run = await session.get(PayrollRun, uuid.UUID(request.doc_id), with_for_update=True)
    if run is None or run.status != "awaiting_approval":
        return
    acted = [s for s in request.steps if s.acted_by]
    run.status, run.request_id = "calculated", None
    run.reject_reason = (acted[-1].comment if acted else None) or None
    await session.flush()


engine.register_document(
    DOC, on_approved=_on_approved, on_rejected=_on_rejected, before_approve=_before_approve
)


# ---------------------------------------------------------------- payment (treasury hooks)


async def payable(session: AsyncSession, run_id: uuid.UUID) -> PayrollRun:
    run = await session.get(PayrollRun, run_id)
    if run is None:
        raise NotFoundError("PAYROLL_NOT_FOUND", "Penggajian tidak ditemukan.")
    if run.status != "approved":
        raise ConflictError(
            "PAYROLL_NOT_PAYABLE",
            f"Penggajian {run.month:02d}/{run.year} berstatus "
            f"{STATUS_LABELS.get(run.status, run.status)}; hanya yang disetujui dapat dibayar.",
        )
    return run


async def mark_paid(session: AsyncSession, run_id: uuid.UUID, payment_run_id: uuid.UUID) -> None:
    run = await session.get(PayrollRun, run_id, with_for_update=True)
    assert run is not None
    run.status, run.payment_run_id = "paid", payment_run_id
    await session.flush()


def label(run: PayrollRun) -> str:
    return f"Gaji {run.month:02d}/{run.year}"


# ---------------------------------------------------------------- 1721-A1


async def a1(session: AsyncSession, year: int, employee_code: str) -> dict[str, Any]:
    """Annual summary of approved payslips for 1721-A1."""
    rows = list(
        (
            await session.execute(
                select(Payslip, PayrollRun.month)
                .join(PayrollRun, PayrollRun.id == Payslip.run_id)
                .where(
                    Payslip.employee_code == employee_code,
                    PayrollRun.year == year,
                    PayrollRun.status.in_(DONE),
                )
                .order_by(PayrollRun.month)
            )
        ).tuples()
    )
    if not rows:
        raise NotFoundError("A1_NOT_FOUND", f"Tidak ada penggajian disetujui tahun {year}.")
    slips = [p for p, _ in rows]
    last = slips[-1]
    salary = sum((p.basic + p.fixed_allowance for p in slips), ZERO)
    insurance = sum((p.kes_er + p.jkk_er + p.jkm_er for p in slips), ZERO)
    gross = sum((p.taxable for p in slips), ZERO)
    withheld = sum((p.pph21 for p in slips), ZERO)
    if last.annual:
        ann = {k: Decimal(str(v)) for k, v in last.annual.items() if k not in ("months", "extra")}
        tax = ann["tax"]
    else:
        r = await rules(session)
        res = calc.annual(
            gross_year=gross,
            pension_year=sum((p.jht_ee + p.jp_ee for p in slips), ZERO),
            withheld_before=ZERO,
            months=len(slips),
            ptkp=calc.d(r["ptkp"].get(last.ptkp_status, r["ptkp"]["TK/0"])),
            rules=r,
            has_tax_id=last.has_tax_id,
        )
        ann = {k: v for k, v in res.__dict__.items() if isinstance(v, Decimal)}
        tax = res.tax
    return {
        "first_month": rows[0][1],
        "last_month": rows[-1][1],
        "salary": salary,
        "allowances": gross - salary - insurance,
        "insurance": insurance,
        "gross": gross,
        "position_cost": ann["position_cost"],
        "pension": ann["pension"],
        "net": ann["net"],
        "ptkp": ann["ptkp"],
        "pkp": ann["pkp"],
        "tax": tax,
        "withheld": withheld,
        "ptkp_status": last.ptkp_status,
        "name": last.employee_name,
    }
