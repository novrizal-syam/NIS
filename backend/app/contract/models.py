"""Contracts with their rate schedule (PROCESS.md · Lead to contract)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin

# service | equipment | personnel | consumable | mobilisation
RATE_KINDS = ("service", "equipment", "personnel", "consumable", "mobilisation")


class Contract(EntityMixin, Base):
    __tablename__ = "contracts"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crm_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crm_quotations.id", ondelete="RESTRICT")
    )
    client_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("clients.code", ondelete="RESTRICT"), index=True
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="IDR")
    value: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    # Revenue recognised against the contract (filled by approved DORs in phase 05).
    used_value: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    po_number: Mapped[str | None] = mapped_column(String(60))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    # active | completed | terminated
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")


class ContractRate(Base):
    """One line of the rate schedule. Equipment carries operating / standby / breakdown rates
    (breakdown is 0 unless agreed otherwise); consumables are cost + markup %."""

    __tablename__ = "contract_rates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    price_item_code: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("price_items.code", ondelete="RESTRICT")
    )
    cost_element_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("cost_elements.code", ondelete="RESTRICT")
    )
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    standby_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    breakdown_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    markup_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    # Quantity quoted (for reference; usage is measured by DORs).
    quoted_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
