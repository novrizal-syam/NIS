"""CAPEX (08; PROCESS.md · CAPEX).

draft -> submitted (DOA capex: Director; > Rp 5 M also RUPS) [awaiting_rups while the RUPS
step is active] -> approved (locked CAPEX plan: a `capex` project with one budget line)
-> in_execution (first AUC posting) -> commissioned (BAST in DMS) -> capitalised (asset
created, depreciation starts) -> reviewed at 6 and 12 months. Rejected -> draft."""

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


def _money(nullable: bool = False) -> Mapped[Any]:
    return mapped_column(
        Numeric(18, 0), nullable=nullable, server_default=None if nullable else "0"
    )


def _fk(target: str) -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete="RESTRICT"))


class CapexProposal(EntityMixin, Base):
    __tablename__ = "capex_proposals"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    rjpp_ref: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    asset_class: Mapped[str] = mapped_column(String(60), nullable=False)
    equipment_type_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("equipment_types.code", ondelete="RESTRICT")
    )
    amount: Mapped[Decimal] = _money()
    funding: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # equity | loan | lease | mixed
    day_rate: Mapped[Decimal] = _money()
    internal_day_rate: Mapped[Decimal] = _money()
    utilisation_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    opex_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    life_years: Mapped[int] = mapped_column(Integer, nullable=False)
    salvage_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    rental_annual: Mapped[Decimal] = _money()
    lease_monthly: Mapped[Decimal] = _money()
    strategic_fit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    risk: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    tax_group: Mapped[str | None] = mapped_column(String(30))
    discount_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    case: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # calc.CaseOut
    priority_score: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    request_id: Mapped[uuid.UUID | None] = _fk("approval_requests.id")
    reject_reason: Mapped[str | None] = mapped_column(String(1000))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    budget: Mapped[Decimal] = _money()  # approved amount incl. approved change requests
    project_id: Mapped[uuid.UUID | None] = _fk("projects.id")
    commissioned_on: Mapped[date | None] = mapped_column(Date)
    bast_attachment_id: Mapped[uuid.UUID | None] = _fk("attachments.id")
    asset_code: Mapped[str | None] = mapped_column(String(30))
    capitalised_on: Mapped[date | None] = mapped_column(Date)
    capitalised_cost: Mapped[Decimal] = _money()
    capitalisation_journal_id: Mapped[uuid.UUID | None] = _fk("journal_entries.id")


class CapexChange(EntityMixin, Base):
    """CAPEX change request: more budget for an approved proposal (DOA capex on the new total)."""

    __tablename__ = "capex_changes"

    number: Mapped[str] = mapped_column(String(25), nullable=False, unique=True)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capex_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = _money()
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="submitted")
    request_id: Mapped[uuid.UUID | None] = _fk("approval_requests.id")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CapexReview(EntityMixin, Base):
    """Post-investment review at 6 and 12 months: actual utilisation, revenue, payback vs case."""

    __tablename__ = "capex_reviews"
    __table_args__ = (UniqueConstraint("proposal_id", "months"),)

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capex_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    months: Mapped[int] = mapped_column(Integer, nullable=False)  # 6 | 12
    actuals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_on: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
