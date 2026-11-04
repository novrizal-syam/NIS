"""Procurement documents. 04a: purchase requisitions (RFQ, PO, GR, invoices come later)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin

# draft -> (submit) blocked | awaiting_approval -> approved -> ordered (PO issued) ;
# rejected -> draft ; cancelled
PR_STATUSES = ("draft", "blocked", "awaiting_approval", "approved", "ordered", "cancelled")


class PurchaseRequisition(EntityMixin, Base):
    __tablename__ = "purchase_requisitions"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    wbs_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_wbs.id", ondelete="RESTRICT"), nullable=False
    )
    cost_element_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("cost_elements.code", ondelete="RESTRICT"), nullable=False
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    need_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_location: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="draft", index=True
    )
    total: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    # Budget check result when blocked.
    shortfall: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    block_message: Mapped[str | None] = mapped_column(String(500))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    reject_reason: Mapped[str | None] = mapped_column(String(1000))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    # The BCR that last unblocked this PR (or was raised for it).
    bcr_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("budget_change_requests.id", ondelete="RESTRICT")
    )


class PurchaseRequisitionLine(Base):
    __tablename__ = "purchase_requisition_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    pr_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_requisitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("items.code", ondelete="RESTRICT")
    )
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    uom: Mapped[str] = mapped_column(String(10), nullable=False)
    est_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)


class Rfq(EntityMixin, Base):
    """Request for quotation from an Approved PR to >= 3 qualified vendors of one category.

    open -> awarded (best score, or non-best after DOA rfq_award) ; open -> award_pending ->
    awarded | open (rejected) ; cancelled."""

    __tablename__ = "rfqs"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    pr_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_requisitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    awarded_vendor_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("vendors.code", ondelete="RESTRICT")
    )
    award_reason: Mapped[str | None] = mapped_column(String(1000))
    pending_vendor_code: Mapped[str | None] = mapped_column(String(20))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RfqQuote(EntityMixin, Base):
    """One invited vendor and, once received, its quote (attachments on entity rfq_quote)."""

    __tablename__ = "rfq_quotes"

    rfq_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("vendors.code", ondelete="RESTRICT"), nullable=False
    )
    # invited | quoted | declined
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="invited")
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    delivery_days: Mapped[int | None] = mapped_column(Integer)
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    valid_until: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(1000))
    quoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RfqQuoteLine(Base):
    __tablename__ = "rfq_quote_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rfq_quotes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # PR line seq
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)


class PriceHistory(Base):
    """Quoted and ordered prices per item (or description) and vendor."""

    __tablename__ = "price_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    item_code: Mapped[str | None] = mapped_column(String(30), index=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    vendor_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    uom: Mapped[str] = mapped_column(String(10), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # rfq_quote | po
    doc_number: Mapped[str] = mapped_column(String(30), nullable=False)
    at: Mapped[date] = mapped_column(Date, nullable=False)


class PurchaseOrder(EntityMixin, Base):
    """draft -> issued (release PR pre-commitment, commit PO subtotal) ;
    issued --revise (higher)--> revision_pending (DOA po_revision) -> issued (rev+1) ;
    issued --revise (same/lower)--> issued (rev+1, savings released) ; draft -> cancelled."""

    __tablename__ = "purchase_orders"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rfq_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="RESTRICT"), unique=True
    )
    pr_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_requisitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    vendor_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("vendors.code", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    wbs_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_wbs.id", ondelete="RESTRICT"), nullable=False
    )
    cost_element_code: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    ppn_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="11")
    ppn_amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    delivery_date: Mapped[date | None] = mapped_column(Date)
    delivery_location: Mapped[str] = mapped_column(String(200), nullable=False)
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    terms: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    # A higher-value revision waiting for approval: {"lines": [...], "reason": ...}
    pending_revision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    revision_reason: Mapped[str | None] = mapped_column(String(500))


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    uom: Mapped[str] = mapped_column(String(10), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
