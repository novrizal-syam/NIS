"""Period close (07d; ACCOUNTING.md · Period close checklist).

Blocking: every DOR of the month approved (none draft/submitted/returned); trial balance
balanced. Warnings (close allowed with a note): unsigned service tickets, open GR/IR (2120),
unpaid payroll, unfiled tax, unsettled cash advances, unreconciled bank lines, depreciation not
run. Close by the Lead Controller; reopen only by the Head of Finance & Support with a reason.
A closed period rejects every posting (services/ledger.check_period).
"""

import calendar
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.billing.models import BankLine, ServiceTicket
from app.core.errors import AppError, ConflictError, ForbiddenError
from app.finance.models import JournalEntry, JournalLine
from app.master.models import FiscalPeriod
from app.operations.models import Dor
from app.payroll.models import PayrollRun
from app.services import audit, ledger
from app.tax.models import DepreciationRun, PeriodCloseLog, TaxReturn
from app.treasury.models import CashAdvance

ZERO = Decimal(0)


def _bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _check(key: str, label: str, ok: bool, detail: str, blocking: bool) -> dict[str, Any]:
    return {"key": key, "label": label, "ok": ok, "detail": detail, "blocking": blocking}


async def _count(session: AsyncSession, stmt: Any) -> int:
    return int((await session.execute(stmt)).scalar_one())


async def checklist(session: AsyncSession, year: int, month: int) -> list[dict[str, Any]]:
    start, end = _bounds(year, month)
    out = []
    open_dors = await _count(
        session,
        select(func.count()).where(
            Dor.report_date.between(start, end), Dor.status.in_(("draft", "submitted", "returned"))
        ),
    )
    out.append(
        _check(
            "dors",
            "Semua DOR periode disetujui",
            open_dors == 0,
            f"{open_dors} DOR belum disetujui." if open_dors else "Semua DOR disetujui.",
            True,
        )
    )
    debit, credit = (
        await session.execute(
            select(
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalEntry.entry_date <= end)
        )
    ).one()
    out.append(
        _check(
            "trial_balance",
            "Neraca saldo seimbang",
            Decimal(debit) == Decimal(credit),
            f"Debit {debit} / kredit {credit}.",
            True,
        )
    )
    unsigned = await _count(
        session,
        select(func.count()).where(
            ServiceTicket.status == "awaiting_signature", ServiceTicket.created_at <= _eod(end)
        ),
    )
    out.append(
        _check(
            "tickets",
            "Service ticket sudah ditandatangani",
            unsigned == 0,
            f"{unsigned} tiket menunggu tanda tangan klien.",
            False,
        )
    )
    grir = -await ledger.balance(session, "2120", until=end)
    out.append(
        _check(
            "grir",
            "GR/IR (2120) bersih",
            grir == 0,
            f"Saldo GR/IR {grir}: barang/jasa diterima belum ditagih (accrual).",
            False,
        )
    )
    payroll = (
        await session.execute(
            select(PayrollRun.status).where(PayrollRun.year == year, PayrollRun.month == month)
        )
    ).scalar_one_or_none()
    out.append(
        _check(
            "payroll",
            "Penggajian dibayar",
            payroll == "paid",
            f"Status penggajian: {payroll or 'belum dihitung'}.",
            False,
        )
    )
    filed = await _count(
        session,
        select(func.count()).where(
            TaxReturn.year == year, TaxReturn.month == month, TaxReturn.status == "filed"
        ),
    )
    out.append(
        _check(
            "tax",
            "SPT Masa PPN, PPh 21, PPh 23 dilaporkan",
            filed == 3,
            f"{filed} dari 3 SPT dilaporkan.",
            False,
        )
    )
    advances = await _count(
        session,
        select(func.count()).where(
            CashAdvance.status.in_(("disbursed", "settlement_submitted")),
            CashAdvance.disbursed_at <= end,
        ),
    )
    out.append(
        _check(
            "advances",
            "Uang muka dipertanggungjawabkan",
            advances == 0,
            f"{advances} uang muka belum selesai.",
            False,
        )
    )
    bank = await _count(
        session,
        select(func.count()).where(BankLine.value_date <= end, BankLine.journal_line_id.is_(None)),
    )
    out.append(
        _check(
            "bank",
            "Mutasi bank direkonsiliasi",
            bank == 0,
            f"{bank} baris mutasi belum cocok.",
            False,
        )
    )
    dep = await _count(
        session,
        select(func.count()).where(DepreciationRun.year == year, DepreciationRun.month == month),
    )
    out.append(
        _check(
            "depreciation",
            "Penyusutan dijalankan",
            dep > 0,
            "Belum dijalankan." if not dep else "Sudah.",
            False,
        )
    )
    return out


def _eod(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)


async def period(session: AsyncSession, year: int, month: int, lock: bool = False) -> FiscalPeriod:
    stmt = select(FiscalPeriod).where(FiscalPeriod.year == year, FiscalPeriod.month == month)
    if lock:
        stmt = stmt.with_for_update()
    p = (await session.execute(stmt)).scalar_one_or_none()
    if p is None:
        p = FiscalPeriod(year=year, month=month, status="open")
        session.add(p)
        await session.flush()
    return p


async def close(
    session: AsyncSession, actor: Principal, year: int, month: int, note: str | None
) -> FiscalPeriod:
    if "lead_controller" not in actor.role_codes:
        raise ForbiddenError("NOT_LEAD_CONTROLLER", "Periode ditutup oleh Lead Controller.")
    p = await period(session, year, month, lock=True)
    if p.status == "closed":
        raise ConflictError("PERIOD_CLOSED", f"Periode {p.code} sudah ditutup.")
    checks = await checklist(session, year, month)
    blocking = [c for c in checks if c["blocking"] and not c["ok"]]
    if blocking:
        raise ConflictError(
            "CLOSE_BLOCKED",
            "Periode belum bisa ditutup: " + "; ".join(c["detail"] for c in blocking),
            details={"checks": checks},
        )
    warnings = [c for c in checks if not c["ok"]]
    if warnings and len((note or "").strip()) < 10:
        raise AppError(
            "CLOSE_NOTE_REQUIRED",
            "Ada peringatan pada checklist; tulis catatan penutupan (min. 10 karakter).",
            status_code=422,
            details={"checks": checks},
        )
    before = p.status
    p.status = "closed"
    session.add(
        PeriodCloseLog(
            year=year,
            month=month,
            action="close",
            by=actor.id,
            at=datetime.now(UTC),
            note=(note or "").strip() or None,
            checks=checks,
        )
    )
    await session.flush()
    await audit.record(
        session,
        action="close",
        entity_type="fiscal_period",
        entity_id=p.id,
        actor_id=actor.id,
        before={"status": before},
        after={"status": "closed", "warnings": [c["key"] for c in warnings]},
        note=note,
    )
    return p


async def reopen(
    session: AsyncSession, actor: Principal, year: int, month: int, reason: str
) -> FiscalPeriod:
    if "head_of_finance" not in actor.role_codes:
        raise ForbiddenError(
            "NOT_HEAD_OF_FINANCE", "Periode dibuka kembali hanya oleh Head of Finance & Support."
        )
    if len(reason.strip()) < 10:
        raise AppError(
            "REASON_REQUIRED", "Tulis alasan membuka kembali (min. 10 karakter).", status_code=422
        )
    p = await period(session, year, month, lock=True)
    if p.status != "closed":
        raise ConflictError("PERIOD_NOT_CLOSED", f"Periode {p.code} tidak dalam status ditutup.")
    p.status = "open"
    session.add(
        PeriodCloseLog(
            year=year,
            month=month,
            action="reopen",
            by=actor.id,
            at=datetime.now(UTC),
            note=reason.strip(),
            checks=[],
        )
    )
    await session.flush()
    await audit.record(
        session,
        action="reopen",
        entity_type="fiscal_period",
        entity_id=p.id,
        actor_id=actor.id,
        before={"status": "closed"},
        after={"status": "open"},
        note=reason.strip(),
    )
    return p


async def history(session: AsyncSession, year: int, month: int) -> list[PeriodCloseLog]:
    return list(
        (
            await session.execute(
                select(PeriodCloseLog)
                .where(PeriodCloseLog.year == year, PeriodCloseLog.month == month)
                .order_by(PeriodCloseLog.at)
            )
        ).scalars()
    )
