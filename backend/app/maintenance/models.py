"""Asset maintenance per GEK-MNT-001 (PROCESS.md · Maintenance; prompt 05b).

- PM task library per equipment type and frequency, imported from the GEK PM plan workbook.
- PM schedules per asset and task: calendar or operating-hour triggers (hours from approved
  DORs) create work orders with FRM-MNT checklists.
- Corrective work orders from DOR breakdowns; downtime log; allocations of assets to projects
  (refused while a mandatory certificate is expired) with pre-mobilisation / post-job
  inspections.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin

FREQUENCIES = ("daily", "weekly", "monthly", "annual", "hours", "per_job")
CALENDAR_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "annual": 365}
WO_KINDS = ("preventive", "corrective", "inspection_pre", "inspection_post")
WO_STATUSES = ("open", "in_progress", "done", "cancelled")


def _asset() -> Mapped[str]:
    return mapped_column(
        String(30), ForeignKey("assets.code", ondelete="RESTRICT"), nullable=False, index=True
    )


class PmTask(EntityMixin, Base):
    __tablename__ = "pm_tasks"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    equipment_type_code: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("equipment_types.code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    interval_hours: Mapped[int | None] = mapped_column(Integer)
    form_code: Mapped[str | None] = mapped_column(String(30))  # FRM-MNT-xx
    checklist: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    est_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class PmSchedule(Base):
    """Where an asset stands for one task: last done (date / hour meter) and next due."""

    __tablename__ = "pm_schedules"
    __table_args__ = (Index("uq_pm_schedule", "asset_code", "task_code", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_code: Mapped[str] = _asset()
    task_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("pm_tasks.code", ondelete="CASCADE"), nullable=False
    )
    last_done_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_done_hours: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    next_due_date: Mapped[date | None] = mapped_column(Date)
    next_due_hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class AssetAllocation(EntityMixin, Base):
    __tablename__ = "asset_allocations"
    __table_args__ = (Index("ix_asset_allocations_asset", "asset_code", "released_at"),)

    asset_code: Mapped[str] = _asset()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    released_at: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(300))


class WorkOrder(EntityMixin, Base):
    __tablename__ = "work_orders"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    asset_code: Mapped[str] = _asset()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    task_code: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("pm_tasks.code", ondelete="RESTRICT")
    )
    form_code: Mapped[str | None] = mapped_column(String(30))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT")
    )
    dor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dors.id", ondelete="RESTRICT")
    )
    trigger: Mapped[str | None] = mapped_column(String(200))
    due_date: Mapped[date | None] = mapped_column(Date)
    due_hours: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # [{"item": "...", "result": "ok" | "nok" | "na" | null, "note": "..."}]
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    labour_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default="0")
    result: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_date: Mapped[date | None] = mapped_column(Date)
    signed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    signature_name: Mapped[str | None] = mapped_column(String(120))
    parts_value: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )


class WorkOrderPart(Base):
    """Spare part issued from stock to a work order (moving-average cost)."""

    __tablename__ = "work_order_parts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    wo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    item_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("items.code", ondelete="RESTRICT"), nullable=False
    )
    warehouse_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("warehouses.code", ondelete="RESTRICT"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Downtime(EntityMixin, Base):
    __tablename__ = "downtime_log"

    asset_code: Mapped[str] = _asset()
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    wo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="RESTRICT")
    )
    dor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dors.id", ondelete="RESTRICT")
    )
