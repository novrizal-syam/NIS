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
