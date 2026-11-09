"""Inventory, goods receipt and material request (PROCESS.md · GR, MR; ACCOUNTING.md).

Stock is valued at moving-average cost per item per warehouse. `stock_balances.value` (integer
rupiah) is authoritative and `avg_cost` is derived, so the sum of all values always equals the
movements posted to account 1310. `stock_moves` is append-only (database trigger)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _item() -> Mapped[str]:
    return mapped_column(String(30), ForeignKey("items.code", ondelete="RESTRICT"), nullable=False)


def _warehouse(nullable: bool = False) -> Mapped[str]:
    return mapped_column(
        String(20), ForeignKey("warehouses.code", ondelete="RESTRICT"), nullable=nullable
    )


def _qty() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 2), nullable=False)


def _money(nullable: bool = False) -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 0), nullable=nullable, server_default="0")


class StockBalance(Base):
    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint("item_code", "warehouse_code", name="uq_stock_item_warehouse"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    item_code: Mapped[str] = _item()
    warehouse_code: Mapped[str] = _warehouse()
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    value: Mapped[Decimal] = _money()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StockMove(Base):
    """Signed movement: receipt / issue / transfer_out / transfer_in / adjustment."""

    __tablename__ = "stock_moves"
    __table_args__ = (
        Index("ix_stock_moves_item_wh", "item_code", "warehouse_code"),
        Index("ix_stock_moves_doc", "doc_type", "doc_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    item_code: Mapped[str] = _item()
    warehouse_code: Mapped[str] = _warehouse()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    qty: Mapped[Decimal] = _qty()
    value: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    qty_after: Mapped[Decimal] = _qty()
    value_after: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False)
    doc_id: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_number: Mapped[str | None] = mapped_column(String(30))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT")
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )


class StockTransfer(EntityMixin, Base):
    __tablename__ = "stock_transfers"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    from_warehouse: Mapped[str] = _warehouse()
    to_warehouse: Mapped[str] = _warehouse()
    note: Mapped[str | None] = mapped_column(String(500))
    value: Mapped[Decimal] = _money()


class StockTransferLine(Base):
    __tablename__ = "stock_transfer_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    transfer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stock_transfers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_code: Mapped[str] = _item()
    qty: Mapped[Decimal] = _qty()
    value: Mapped[Decimal] = _money()


class StockCount(EntityMixin, Base):
    """Stock opname. Variances need Lead Controller approval (DOA stock_opname) before they
    adjust stock and post to the ledger."""

    __tablename__ = "stock_counts"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    warehouse_code: Mapped[str] = _warehouse()
    count_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    note: Mapped[str | None] = mapped_column(String(500))
    variance_value: Mapped[Decimal] = _money()
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    reject_reason: Mapped[str | None] = mapped_column(String(1000))
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )


class StockCountLine(Base):
    __tablename__ = "stock_count_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    count_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stock_counts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_code: Mapped[str] = _item()
    system_qty: Mapped[Decimal] = _qty()
    counted_qty: Mapped[Decimal] = _qty()
    unit_cost: Mapped[Decimal] = _money()
    variance_value: Mapped[Decimal] = _money()
    reason: Mapped[str | None] = mapped_column(String(300))


class GoodsReceipt(EntityMixin, Base):
    """GR against an issued PO: draft -> posted (needs a photo or BAST attachment).

    kind goods: received by the Warehouse Head; service: by the project owner."""

    __tablename__ = "goods_receipts"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # goods | service
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    warehouse_code: Mapped[str | None] = _warehouse(nullable=True)
    delivery_note: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = _money()
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )


class GoodsReceiptLine(Base):
    """References the PO line by `seq` (PO revisions rewrite line rows, not their seq)."""

    __tablename__ = "goods_receipt_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    gr_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goods_receipts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    po_line_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    qty: Mapped[Decimal] = _qty()
    uom: Mapped[str] = mapped_column(String(10), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    to_stock: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))


class MaterialRequest(EntityMixin, Base):
    """MR by a Field Engineer: site stock first, then base; shortfall becomes a PR.

    status: issued (all from stock) | partial (issued + PR) | pr_created (nothing in stock)."""

    __tablename__ = "material_requests"

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
    site_warehouse: Mapped[str] = _warehouse()
    base_warehouse: Mapped[str] = _warehouse()
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    need_date: Mapped[date] = mapped_column(Date, nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    issued_value: Mapped[Decimal] = _money()
    pr_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_requisitions.id", ondelete="RESTRICT")
    )
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )


class MaterialRequestLine(Base):
    __tablename__ = "material_request_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    mr_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("material_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code: Mapped[str] = _item()
    qty: Mapped[Decimal] = _qty()
    from_site: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    from_base: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    shortfall: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    value: Mapped[Decimal] = _money()
