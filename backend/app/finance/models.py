"""General ledger: journal entries and lines (ACCOUNTING.md; CLAUDE.md rule 7).

Only `services/ledger.post_journal()` writes here. Entries are never edited or deleted, only
reversed: a database trigger rejects UPDATE and DELETE on both tables (the single exception is
setting `reversed_by` once on the original entry when it is reversed)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (Index("ix_journal_entries_source", "source_type", "source_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # YYYY-MM
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_number: Mapped[str | None] = mapped_column(String(40))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    reversal_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id")
    )
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    is_demo: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))


class JournalLine(Base):
    """One debit or one credit with the reporting dimensions (ACCOUNTING.md)."""

    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)", name="one_side"
        ),
        Index("ix_journal_lines_account", "account_code"),
        Index("ix_journal_lines_project", "project_id", "wbs_id", "cost_element_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(
        String(10), ForeignKey("accounts.code", ondelete="RESTRICT"), nullable=False
    )
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    memo: Mapped[str | None] = mapped_column(String(300))
    # Dimensions
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT")
    )
    wbs_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_wbs.id", ondelete="RESTRICT")
    )
    cost_element_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("cost_elements.code", ondelete="RESTRICT")
    )
    cost_center_code: Mapped[str | None] = mapped_column(String(20))
    asset_code: Mapped[str | None] = mapped_column(String(30))
    partner_type: Mapped[str | None] = mapped_column(String(10))  # client | vendor | employee
    partner_code: Mapped[str | None] = mapped_column(String(30))


class VendorInvoice(EntityMixin, Base):
    """Vendor invoice against a PO (PROCESS.md · Vendor invoice; 3-way match).

    draft --match--> approved (payable; journal posted) | exception (not payable)
    exception --correction / credit note--> draft --match--> ...
    draft | exception --cancel--> cancelled
    """

    __tablename__ = "vendor_invoices"
    __table_args__ = (
        # One live invoice per vendor invoice number (a cancelled one may be re-entered).
        Index(
            "uq_vendor_invoice_no",
            "vendor_code",
            func.upper(text("invoice_no")),
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
    )

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    vendor_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("vendors.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_no: Mapped[str] = mapped_column(String(60), nullable=False)
    tax_invoice_no: Mapped[str | None] = mapped_column(String(30))
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # goods | service
    term_days: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    dpp: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    ppn: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    pph23_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    pph23: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    payable: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    match_result: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    exception_reason: Mapped[str | None] = mapped_column(String(1000))
    note: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )


class VendorInvoiceLine(Base):
    """Invoiced quantity and price per PO line (by seq, like GR lines)."""

    __tablename__ = "vendor_invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendor_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    po_line_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)


class VendorCreditNote(EntityMixin, Base):
    """Credit note from the vendor that resolves a match exception (reduces the invoice)."""

    __tablename__ = "vendor_credit_notes"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendor_invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    credit_note_no: Mapped[str] = mapped_column(String(60), nullable=False)
    note_date: Mapped[date] = mapped_column(Date, nullable=False)
    dpp: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    ppn: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
