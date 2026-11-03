import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin

METHODS = ("open", "limited", "selection", "direct")
SECTIONS = ("admin", "technical", "commercial")
RESULTS = ("won", "lost", "disqualified", "cancelled")
CHANNELS = ("eproc", "civd", "hardcopy", "email")


class Tender(EntityMixin, Base):
    __tablename__ = "tenders"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tender_number: Mapped[str | None] = mapped_column(String(80))
    method: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    aanwijzing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clarification_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    opening_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bid_validity_until: Mapped[date | None] = mapped_column(Date)
    bid_bond_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    bid_bond_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    bid_bond_number: Mapped[str | None] = mapped_column(String(80))
    tkdn_required_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tkdn_offered_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    # none | pending | approved | rejected  (DOA tender_package)
    package_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="none")
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    # Submission record
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_channel: Mapped[str | None] = mapped_column(String(20))
    receipt_number: Mapped[str | None] = mapped_column(String(80))
    # Result
    result: Mapped[str | None] = mapped_column(String(20))
    result_at: Mapped[date | None] = mapped_column(Date)
    rank: Mapped[int | None] = mapped_column(Integer)
    winner_name: Mapped[str | None] = mapped_column(String(200))
    winning_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    lessons_learned: Mapped[str | None] = mapped_column(Text)


class TenderDocument(Base):
    """Checklist item. Files are DMS attachments on entity `tender_document`. Effective status:
    N/A when marked; Present when a file is attached and not expired; otherwise Missing."""

    __tablename__ = "tender_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    not_applicable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    expiry_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(300))


class TenderClarification(EntityMixin, Base):
    __tablename__ = "tender_clarifications"

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    answer: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
