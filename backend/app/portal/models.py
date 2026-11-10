"""Vendor invoice submissions through the vendor portal (10c)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class VendorSubmission(EntityMixin, Base):
    """submitted (by the vendor, with the invoice PDF) -> registered (AP created the vendor
    invoice from it) | rejected (with a reason the vendor sees)."""

    __tablename__ = "vendor_submissions"

    vendor_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("vendors.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    po_number: Mapped[str] = mapped_column(String(30), nullable=False)
    invoice_no: Mapped[str] = mapped_column(String(60), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    tax_invoice_no: Mapped[str | None] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="submitted")
    vendor_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendor_invoices.id", ondelete="RESTRICT")
    )
    reject_reason: Mapped[str | None] = mapped_column(String(500))
