"""Tax returns per period, depreciation runs, period close log (07d)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 0), nullable=False, server_default="0")


def _fk(target: str) -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete="RESTRICT"))


class TaxReturn(EntityMixin, Base):
    """One monthly tax obligation (ppn | pph21 | pph23).

    draft (amounts from the GL, recomputed on view) -> billed (billing code; amount locked)
    -> paid (NTPN; payment run or direct journal) -> filed (SPT Masa, BPE).
    A return with nothing to pay (nil, or PPN overpaid/compensated) goes draft -> filed."""

    __tablename__ = "tax_returns"
    __table_args__ = (UniqueConstraint("year", "month", "tax_type"),)

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="draft")
    # PPN: output (2210), input (1420) of the period and the overpayment carried in/out.
    output_tax: Mapped[Decimal] = _money()
    input_tax: Mapped[Decimal] = _money()
    carried_in: Mapped[Decimal] = _money()
    carry_forward: Mapped[Decimal] = _money()
    amount: Mapped[Decimal] = _money()  # payable this period
    pay_due: Mapped[date] = mapped_column(Date, nullable=False)
    file_due: Mapped[date] = mapped_column(Date, nullable=False)
    billing_code: Mapped[str | None] = mapped_column(String(20))
    billing_expires: Mapped[date | None] = mapped_column(Date)
    paid_on: Mapped[date | None] = mapped_column(Date)
    ntpn: Mapped[str | None] = mapped_column(String(20))
    payment_method: Mapped[str | None] = mapped_column(String(15))  # payment_run | direct
    payment_run_id: Mapped[uuid.UUID | None] = _fk("payment_runs.id")
    journal_id: Mapped[uuid.UUID | None] = _fk("journal_entries.id")
    filed_on: Mapped[date | None] = mapped_column(Date)
    bpe_no: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)


class DepreciationRun(EntityMixin, Base):
    """Monthly depreciation (once per period): straight line (PSAK 216) to the ledger; fiscal
    depreciation (PMK 72/2023 groups) alongside for the fiscal report."""

    __tablename__ = "depreciation_runs"
    __table_args__ = (UniqueConstraint("year", "month"),)

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[Decimal] = _money()
    fiscal_total: Mapped[Decimal] = _money()
    journal_id: Mapped[uuid.UUID | None] = _fk("journal_entries.id")
    # [{"asset", "commercial", "fiscal", "account", "project_id"}]
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class PeriodCloseLog(Base):
    """Every close and reopen with the checklist as it stood and the note/reason."""

    __tablename__ = "period_close_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)  # close | reopen
    by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
