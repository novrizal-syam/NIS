"""Procurement documents. 04a: purchase requisitions (RFQ, PO, GR, invoices come later)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin

# draft -> (submit) blocked | awaiting_approval -> approved | rejected(->draft) ; cancelled
PR_STATUSES = ("draft", "blocked", "awaiting_approval", "approved", "cancelled")


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
