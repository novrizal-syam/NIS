"""Daily Operational Report (PROCESS.md · Execution; prompt 05a).

draft --submit--> submitted --DOA dor (project Superintendent)--> approved
                           \\-> returned (reason) --edit, resubmit--> submitted
Drafts are written from the PWA, also offline: `client_id` makes saves idempotent and
`version` detects conflicting edits from two devices.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin

DOR_STATUSES = ("draft", "submitted", "approved", "returned")


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _dor_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("dors.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _hours() -> Mapped[Decimal]:
    return mapped_column(Numeric(5, 2), nullable=False, server_default="0")


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 0), nullable=False, server_default="0")


class Dor(EntityMixin, Base):
    __tablename__ = "dors"
    __table_args__ = (
        # One live DOR per project per day.
        Index("uq_dor_project_day", "project_id", "report_date", unique=True),
    )

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    wbs_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_wbs.id", ondelete="RESTRICT"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    site_warehouse: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("warehouses.code", ondelete="RESTRICT")
    )
    activities: Mapped[str | None] = mapped_column(Text)
    npt_hours: Mapped[Decimal] = _hours()
    npt_reason: Mapped[str | None] = mapped_column(String(500))
    technical: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    hse: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    revenue: Mapped[Decimal] = _money()
    internal_cost: Mapped[Decimal] = _money()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    return_reason: Mapped[str | None] = mapped_column(String(1000))
    revenue_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    stock_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )


class DorEquipment(Base):
    """One unit's 24 hours: operating + standby + breakdown + rig-up/down = 24."""

    __tablename__ = "dor_equipment"

    id: Mapped[uuid.UUID] = _pk()
    dor_id: Mapped[uuid.UUID] = _dor_fk()
    asset_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("assets.code", ondelete="RESTRICT"), nullable=False
    )
    rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_rates.id", ondelete="RESTRICT")
    )
    operating: Mapped[Decimal] = _hours()
    standby: Mapped[Decimal] = _hours()
    breakdown: Mapped[Decimal] = _hours()
    rig: Mapped[Decimal] = _hours()
    remark: Mapped[str | None] = mapped_column(String(300))
    revenue: Mapped[Decimal] = _money()
    internal_cost: Mapped[Decimal] = _money()


class DorCrew(Base):
    __tablename__ = "dor_crew"

    id: Mapped[uuid.UUID] = _pk()
    dor_id: Mapped[uuid.UUID] = _dor_fk()
    employee_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("employees.code", ondelete="RESTRICT"), nullable=False
    )
    rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_rates.id", ondelete="RESTRICT")
    )
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="12")
    overtime_hours: Mapped[Decimal] = _hours()
    revenue: Mapped[Decimal] = _money()
    internal_cost: Mapped[Decimal] = _money()


class DorConsumable(Base):
    __tablename__ = "dor_consumables"

    id: Mapped[uuid.UUID] = _pk()
    dor_id: Mapped[uuid.UUID] = _dor_fk()
    item_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("items.code", ondelete="RESTRICT"), nullable=False
    )
    rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_rates.id", ondelete="RESTRICT")
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    revenue: Mapped[Decimal] = _money()
    internal_cost: Mapped[Decimal] = _money()


class AssetUsage(Base):
    """Asset operating hours per day from approved DORs (maintenance counters, 05b)."""

    __tablename__ = "asset_usage"

    id: Mapped[uuid.UUID] = _pk()
    asset_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("assets.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    dor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dors.id", ondelete="RESTRICT"), nullable=False
    )
    operating: Mapped[Decimal] = _hours()
    standby: Mapped[Decimal] = _hours()
    breakdown: Mapped[Decimal] = _hours()
    rig: Mapped[Decimal] = _hours()


class HseDaily(Base):
    """HSE statistics per project per day (man-hours, incidents) from approved DORs."""

    __tablename__ = "hse_daily"

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    dor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dors.id", ondelete="RESTRICT"), nullable=False
    )
    manhours: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")
    incidents: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    near_misses: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unsafe_acts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    toolbox_talks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class PayrollDay(Base):
    """Days on site and overtime per employee from approved DORs (payroll input, 07c)."""

    __tablename__ = "payroll_days"
    __table_args__ = (Index("uq_payroll_day_employee", "employee_code", "work_date", unique=True),)

    id: Mapped[uuid.UUID] = _pk()
    employee_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("employees.code", ondelete="RESTRICT"), nullable=False
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    dor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dors.id", ondelete="RESTRICT"), nullable=False
    )
    hours: Mapped[Decimal] = _hours()
    overtime_hours: Mapped[Decimal] = _hours()
