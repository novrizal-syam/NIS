"""Payroll (07c): monthly runs, payslips, timesheet days, extra items, PPh 21 TER table.

Run status (PROCESS.md): (not started) -> calculated -> awaiting_approval (DOA payroll)
-> approved (journal posted) -> paid (payment run released). Rejected -> calculated."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 0), nullable=False, server_default="0")


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class Pph21TerRate(Base):
    """PPh 21 TER monthly bands (PP 58/2023), stored as data."""

    __tablename__ = "pph21_ter_rates"
    __table_args__ = (UniqueConstraint("category", "seq"),)

    id: Mapped[uuid.UUID] = _pk()
    category: Mapped[str] = mapped_column(String(1), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    upper: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))  # None = no upper bound
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)


class PayrollRun(EntityMixin, Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (UniqueConstraint("year", "month"),)

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="calculated")
    calculated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    reject_reason: Mapped[str | None] = mapped_column(String(1000))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    payment_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_runs.id", ondelete="RESTRICT")
    )
    employees: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    gross: Mapped[Decimal] = _money()
    employer_bpjs: Mapped[Decimal] = _money()
    employee_bpjs: Mapped[Decimal] = _money()
    pph21: Mapped[Decimal] = _money()
    deductions: Mapped[Decimal] = _money()
    net: Mapped[Decimal] = _money()
    employer_cost: Mapped[Decimal] = _money()


class Payslip(Base):
    __tablename__ = "payslips"
    __table_args__ = (UniqueConstraint("run_id", "employee_code"),)

    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False
    )
    employee_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("employees.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    employee_name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[str | None] = mapped_column(String(120))
    is_field: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ptkp_status: Mapped[str] = mapped_column(String(5), nullable=False)
    ter_category: Mapped[str] = mapped_column(String(1), nullable=False)
    has_tax_id: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    basic: Mapped[Decimal] = _money()
    fixed_allowance: Mapped[Decimal] = _money()
    site_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    field_allowance: Mapped[Decimal] = _money()
    overtime_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="0"
    )
    overtime_factor_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="0"
    )
    overtime_pay: Mapped[Decimal] = _money()
    other_allowances: Mapped[Decimal] = _money()
    gross: Mapped[Decimal] = _money()
    kes_er: Mapped[Decimal] = _money()
    kes_ee: Mapped[Decimal] = _money()
    jht_er: Mapped[Decimal] = _money()
    jht_ee: Mapped[Decimal] = _money()
    jp_er: Mapped[Decimal] = _money()
    jp_ee: Mapped[Decimal] = _money()
    jkk_er: Mapped[Decimal] = _money()
    jkm_er: Mapped[Decimal] = _money()
    taxable: Mapped[Decimal] = _money()  # monthly gross for TER (incl. employer JKK/JKM/Kes)
    ter_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    pph21: Mapped[Decimal] = _money()  # December: annual tax minus Jan-Nov (may be negative)
    annual: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    deductions: Mapped[Decimal] = _money()
    net: Mapped[Decimal] = _money()
    employer_cost: Mapped[Decimal] = _money()
    # [{"project_id", "wbs_id", "days", "amount"}] (field cost per project by DOR days)
    allocation: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )


class PayslipDay(Base):
    """Timesheet day on site (from an approved DOR, or added/edited by HCBP with a reason)."""

    __tablename__ = "payslip_days"
    __table_args__ = (UniqueConstraint("payslip_id", "work_date"),)

    id: Mapped[uuid.UUID] = _pk()
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payslips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    wbs_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_wbs.id", ondelete="RESTRICT")
    )
    payroll_day_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_days.id", ondelete="RESTRICT"), index=True
    )
    overtime_hours: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default="0"
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="dor")
    note: Mapped[str | None] = mapped_column(String(300))


class PayslipItem(Base):
    """Extra allowance (taxable or not) or deduction on one payslip."""

    __tablename__ = "payslip_items"

    id: Mapped[uuid.UUID] = _pk()
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payslips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # allowance | deduction
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = _money()
    taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
