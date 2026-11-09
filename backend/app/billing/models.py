"""Order to cash (PROCESS.md · Order to cash; prompt 06).

Service ticket: awaiting_signature -> signed (disputed lines removed, revenue reversed)
                -> invoiced | cancelled (before signing)
Invoice: draft -> faktur_issued (journal 1210/1220/2210) -> sent -> paid | cancelled (draft)
Receipt: cash + PPh 23 withheld allocated to invoices (journal 1110 + 1410 / 1210).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


def _money(nullable: bool = False) -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 0), nullable=nullable, server_default="0")


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class ServiceTicket(EntityMixin, Base):
    __tablename__ = "service_tickets"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="awaiting_signature"
    )
    gross_value: Mapped[Decimal] = _money()
    disputed_value: Mapped[Decimal] = _money()
    value: Mapped[Decimal] = _money()  # billable = gross - disputed
    signer_name: Mapped[str | None] = mapped_column(String(120))
    signer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    sign_method: Mapped[str | None] = mapped_column(String(10))  # tablet | link
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acceptance_no: Mapped[str | None] = mapped_column(String(60))  # BAST / SES
    signature_attachment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    signed_pdf_attachment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    psre_provider: Mapped[str | None] = mapped_column(String(30))
    psre_ref: Mapped[str | None] = mapped_column(String(120))
    link_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    link_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    link_email: Mapped[str | None] = mapped_column(String(254))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reversal_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )


class TicketDor(Base):
    """A DOR is billed on at most one (live) ticket."""

    __tablename__ = "ticket_dors"
    __table_args__ = (Index("uq_ticket_dor", "dor_id", unique=True),)

    id: Mapped[uuid.UUID] = _pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dors.id", ondelete="RESTRICT"), nullable=False
    )


class TicketLine(Base):
    __tablename__ = "ticket_lines"

    id: Mapped[uuid.UUID] = _pk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    dor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dors.id", ondelete="RESTRICT"), nullable=False
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # equipment | personnel | consumable
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    disputed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    dispute_reason: Mapped[str | None] = mapped_column(String(500))
    disputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CustomerInvoice(EntityMixin, Base):
    __tablename__ = "customer_invoices"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    # Nullable for opening-balance AR items (07a).
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    client_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("clients.code", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    subtotal: Mapped[Decimal] = _money()
    dpp_other: Mapped[Decimal] = _money()  # DPP nilai lain = 11/12 x subtotal
    ppn_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="12")
    ppn: Mapped[Decimal] = _money()
    total: Mapped[Decimal] = _money()
    pph23_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="2")
    pph23_expected: Mapped[Decimal] = _money()
    net_cash: Mapped[Decimal] = _money()
    stamp_duty: Mapped[Decimal] = _money()
    # Contract currency. IDR columns hold the IDR value at `fx_rate` (rate on the invoice date);
    # for USD the foreign total and what was settled in USD are kept too (07a).
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="IDR")
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="1")
    total_foreign: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    paid_foreign: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0"
    )
    is_opening: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    faktur_number: Mapped[str | None] = mapped_column(String(30), unique=True)
    faktur_date: Mapped[date | None] = mapped_column(Date)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_to: Mapped[str | None] = mapped_column(String(254))
    paid_amount: Mapped[Decimal] = _money()
    pph23_withheld: Mapped[Decimal] = _money()
    paid_at: Mapped[date | None] = mapped_column(Date)
    pack_attachment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    note: Mapped[str | None] = mapped_column(Text)


class InvoiceTicket(Base):
    __tablename__ = "invoice_tickets"
    __table_args__ = (Index("uq_invoice_ticket", "ticket_id", unique=True),)

    id: Mapped[uuid.UUID] = _pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_tickets.id", ondelete="RESTRICT"), nullable=False
    )


class Receipt(EntityMixin, Base):
    __tablename__ = "customer_receipts"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    client_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("clients.code", ondelete="RESTRICT"), index=True
    )
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    cash: Mapped[Decimal] = _money()
    pph23: Mapped[Decimal] = _money()
    bank_ref: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )


class ReceiptAllocation(Base):
    __tablename__ = "receipt_allocations"

    id: Mapped[uuid.UUID] = _pk()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_receipts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cash: Mapped[Decimal] = _money()
    pph23: Mapped[Decimal] = _money()
    cash_foreign: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    fx_difference: Mapped[Decimal] = _money()  # loss > 0, gain < 0 (7100)
    bukti_potong_no: Mapped[str | None] = mapped_column(String(60))


class BankLine(EntityMixin, Base):
    """Credit line from a bank statement import (CSV or MT940)."""

    __tablename__ = "bank_lines"
    __table_args__ = (Index("uq_bank_line", "fingerprint", unique=True),)

    import_ref: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    value_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unmatched")
    suggested_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    match_rule: Mapped[str | None] = mapped_column(String(40))
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
