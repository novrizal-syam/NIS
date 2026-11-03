"""Lead to contract, first part: leads, opportunities and bid/no-bid decisions
(docs/domain/PROCESS.md · Lead to contract)."""

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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


def _user_fk(nullable: bool = False) -> Mapped[Any]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=nullable,
        index=True,
    )


def _client_fk() -> Mapped[Any]:
    return mapped_column(
        String(20), ForeignKey("clients.code", ondelete="RESTRICT"), nullable=True, index=True
    )


class Lead(EntityMixin, Base):
    """New -> Contacted -> Qualified | Disqualified (reason)."""

    __tablename__ = "crm_leads"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    # Either an existing client (master data) or a free-text prospect name.
    client_code: Mapped[str | None] = _client_fk()
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    need: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="new")
    disqualify_reason: Mapped[str | None] = mapped_column(String(500))
    # {"budget": bool, "technical_fit": bool, "start_6m": bool, "decision_maker": bool,
    #  "csms": bool}
    qualification: Mapped[dict[str, bool]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    owner_id: Mapped[uuid.UUID] = _user_fk()
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Opportunity(EntityMixin, Base):
    """Qualified -> Quotation -> Submitted -> Won | Lost. Qualified -> Quotation only through an
    approved bid decision."""

    __tablename__ = "crm_opportunities"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_leads.id", ondelete="RESTRICT"),
        unique=True,
    )
    client_code: Mapped[str | None] = _client_fk()
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[uuid.UUID] = _user_fk()
    value: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    probability: Mapped[int] = mapped_column(Integer, nullable=False, server_default="20")
    expected_close: Mapped[date | None] = mapped_column(Date)
    is_tender: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    stage: Mapped[str] = mapped_column(String(20), nullable=False, server_default="qualified")
    # none | pending | bid | no_bid  (latest bid decision outcome)
    bid_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="none")
    lost_reason: Mapped[str | None] = mapped_column(String(500))
    stage_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    won_at: Mapped[date | None] = mapped_column(Date)
    lost_at: Mapped[date | None] = mapped_column(Date)


class BidDecision(EntityMixin, Base):
    """Six scores 1-5; percent = average / 5. The proposer recommends bid or no-bid and the
    Director decides through the DOA engine (doc_type bid_decision)."""

    __tablename__ = "crm_bid_decisions"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scores: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    recommendation: Mapped[str] = mapped_column(String(10), nullable=False)  # bid | no_bid
    proposal: Mapped[str] = mapped_column(String(10), nullable=False)  # bid | no_bid
    note: Mapped[str | None] = mapped_column(String(1000))
    # pending | approved | rejected | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(String(1000))


class Quotation(EntityMixin, Base):
    """One revision of a quotation. Revisions share `number` (QT-26-001) and count up from 0;
    only the latest revision can change, older ones are the history.

    Draft -> Submitted -> Approved | Rejected; Approved -> Sent ("Kirim ke klien").
    A new revision (from Approved, Rejected or Sent) marks the previous one Superseded.
    Totals and margin are computed in the backend (services: crm.quotation_service)."""

    __tablename__ = "crm_quotations"
    __table_args__ = (UniqueConstraint("number", "revision"),)

    number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = _user_fk()
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 0), nullable=False, server_default="0"
    )
    total_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    margin: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    margin_pct: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, server_default="0")
    valid_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    terms: Mapped[str | None] = mapped_column(Text)
    revision_reason: Mapped[str | None] = mapped_column(String(500))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(String(1000))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    letter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outgoing_letters.id", ondelete="RESTRICT")
    )
    sent_to_email: Mapped[str | None] = mapped_column(String(254))


class QuotationLine(Base):
    __tablename__ = "crm_quotation_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    quotation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_quotations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    price_item_code: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("price_items.code", ondelete="RESTRICT")
    )
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    line_cost: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    line_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
