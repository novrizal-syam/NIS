"""Treasury (07b): bank accounts, payment runs, cash advances.

Bank statement lines live in `bank_lines` (billing, 06), extended with the bank account and
the GL line they are reconciled to."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 0), nullable=False, server_default="0")


def _fk(target: str, nullable: bool = True, index: bool = False) -> Mapped[uuid.UUID | None]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey(target, ondelete="RESTRICT"),
        nullable=nullable,
        index=index,
    )


class BankAccount(EntityMixin, Base):
    """A company bank account. Its balance is the balance of its own GL account."""

    __tablename__ = "bank_accounts"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(60), nullable=False)
    account_no: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="IDR")
    gl_account: Mapped[str] = mapped_column(
        String(10), ForeignKey("accounts.code", ondelete="RESTRICT"), nullable=False, unique=True
    )
    # Bank file adapter for payment runs: csv (bulk transfer) now; mandiri/bri/bni/bca later.
    adapter: Mapped[str] = mapped_column(String(20), nullable=False, server_default="csv")
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class PaymentRun(EntityMixin, Base):
    """draft -> awaiting_approval (DOA payment_run) -> approved -> released (journal)
    rejected -> draft; draft | approved -> cancelled.
    Preparer (created_by), approver and releaser are three different people."""

    __tablename__ = "payment_runs"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(300))
    total: Mapped[Decimal] = _money()
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    request_id: Mapped[uuid.UUID | None] = _fk("approval_requests.id")
    reject_reason: Mapped[str | None] = mapped_column(String(1000))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[uuid.UUID | None] = _fk("users.id")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    journal_id: Mapped[uuid.UUID | None] = _fk("journal_entries.id")
    bank_file_ref: Mapped[str | None] = mapped_column(String(80))


class PaymentRunItem(Base):
    """One payment: an approved vendor invoice, an approved payroll run (net salaries per
    employee), or a liability paid from its GL balance (2310, BPJS 2240, PPh 21 2220,
    PPh 23 2230)."""

    __tablename__ = "payment_run_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payment_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_invoice_id: Mapped[uuid.UUID | None] = _fk("vendor_invoices.id", index=True)
    vendor_code: Mapped[str | None] = mapped_column(String(20))
    # Net salaries of an approved payroll run (07c); one transfer per employee in the bank file.
    payroll_run_id: Mapped[uuid.UUID | None] = _fk("payroll_runs.id", index=True)
    payee: Mapped[str] = mapped_column(String(200), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    amount: Mapped[Decimal] = _money()


class CashAdvance(EntityMixin, Base):
    """draft -> awaiting_approval (DOA cash_advance, Head of Operation) -> approved
    -> disbursed (Cashier; Dr 1120 / Cr bank) -> settlement_submitted (receipts per cost element)
    -> settled (Cashier; expenses + budget actuals, refund or reimbursement).
    rejected -> draft; draft | approved -> cancelled."""

    __tablename__ = "cash_advances"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    employee_code: Mapped[str | None] = mapped_column(String(20))
    project_id: Mapped[uuid.UUID | None] = _fk("projects.id", index=True)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = _money()
    needed_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(25), nullable=False, server_default="draft")
    request_id: Mapped[uuid.UUID | None] = _fk("approval_requests.id")
    reject_reason: Mapped[str | None] = mapped_column(String(1000))
    bank_account_id: Mapped[uuid.UUID | None] = _fk("bank_accounts.id")
    disbursed_by: Mapped[uuid.UUID | None] = _fk("users.id")
    disbursed_at: Mapped[date | None] = mapped_column(Date)
    disbursement_journal_id: Mapped[uuid.UUID | None] = _fk("journal_entries.id")
    spent: Mapped[Decimal] = _money()
    settlement_note: Mapped[str | None] = mapped_column(Text)
    settlement_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_by: Mapped[uuid.UUID | None] = _fk("users.id")
    settled_at: Mapped[date | None] = mapped_column(Date)
    settlement_journal_id: Mapped[uuid.UUID | None] = _fk("journal_entries.id")
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CashAdvanceLine(Base):
    """Settlement line: what was spent, per cost element (and WBS on a project), with its
    receipt photo (attachment on the cash advance)."""

    __tablename__ = "cash_advance_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    advance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cash_advances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    spent_on: Mapped[date] = mapped_column(Date, nullable=False)
    cost_element: Mapped[str] = mapped_column(
        String(20), ForeignKey("cost_elements.code", ondelete="RESTRICT"), nullable=False
    )
    wbs_code: Mapped[str | None] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal] = _money()
    attachment_id: Mapped[uuid.UUID | None] = _fk("attachments.id")
