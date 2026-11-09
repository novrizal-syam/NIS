"""Master data. References use stable business codes (e.g. department_code) so CSV
import/export and the UI never deal with UUIDs; codes cannot be changed once created."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


def _active() -> Mapped[bool]:
    return mapped_column(Boolean, nullable=False, server_default=text("true"))


def _docs() -> Mapped[list[dict[str, Any]]]:
    # [{"name": ..., "number": ..., "expiry_date": "YYYY-MM-DD"}]
    return mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class Department(EntityMixin, Base):
    __tablename__ = "departments"

    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = _active()


class CostCenter(EntityMixin, Base):
    __tablename__ = "cost_centers"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    department_code: Mapped[str | None] = mapped_column(
        String(10), ForeignKey("departments.code", ondelete="RESTRICT")
    )
    is_active: Mapped[bool] = _active()


class Client(EntityMixin, Base):
    __tablename__ = "clients"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    npwp: Mapped[str | None] = mapped_column(String(25))
    csms_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="none")
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    currency: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("currencies.code", ondelete="RESTRICT"),
        nullable=False,
        server_default="IDR",
    )
    address: Mapped[str | None] = mapped_column(String(500))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = _active()


class Vendor(EntityMixin, Base):
    __tablename__ = "vendors"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    npwp: Mapped[str | None] = mapped_column(String(25))
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    # qualified | csms_pending | blacklisted (CSMS pending / blacklisted are excluded from RFQ)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="qualified")
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    bank_name: Mapped[str | None] = mapped_column(String(60))
    bank_account_no: Mapped[str | None] = mapped_column(String(40))
    bank_account_name: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(500))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    legal_docs: Mapped[list[dict[str, Any]]] = _docs()
    is_active: Mapped[bool] = _active()


class Employee(EntityMixin, Base):
    __tablename__ = "employees"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[str] = mapped_column(String(120), nullable=False)
    department_code: Mapped[str | None] = mapped_column(
        String(10), ForeignKey("departments.code", ondelete="RESTRICT")
    )
    is_field: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    join_date: Mapped[date | None] = mapped_column(Date)
    # Sensitive (UU 27/2022 PDP): stripped without permission.
    basic_salary: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    nik: Mapped[str | None] = mapped_column(String(16))
    npwp: Mapped[str | None] = mapped_column(String(25))
    bank_name: Mapped[str | None] = mapped_column(String(60))
    bank_account_no: Mapped[str | None] = mapped_column(String(40))
    ptkp_status: Mapped[str] = mapped_column(String(5), nullable=False, server_default="TK/0")
    bpjs_kesehatan_no: Mapped[str | None] = mapped_column(String(20))
    bpjs_tk_no: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    certificates: Mapped[list[dict[str, Any]]] = _docs()
    is_active: Mapped[bool] = _active()


class Item(EntityMixin, Base):
    __tablename__ = "items"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    uom: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0"
    )
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    is_active: Mapped[bool] = _active()


class Warehouse(EntityMixin, Base):
    __tablename__ = "warehouses"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # base | site
    location: Mapped[str | None] = mapped_column(String(200))
    project_code: Mapped[str | None] = mapped_column(String(30))  # FK once projects exist
    is_active: Mapped[bool] = _active()


class Asset(EntityMixin, Base):
    __tablename__ = "assets"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(60), nullable=False)
    criticality: Mapped[str] = mapped_column(String(1), nullable=False)  # A | B | C
    internal_day_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 0), nullable=False, server_default="0"
    )
    serial_no: Mapped[str | None] = mapped_column(String(60))
    certificates: Mapped[list[dict[str, Any]]] = _docs()
    is_active: Mapped[bool] = _active()


class Account(EntityMixin, Base):
    __tablename__ = "accounts"

    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # asset | liability | equity | revenue | expense
    account_type: Mapped[str] = mapped_column(String(10), nullable=False)
    normal_balance: Mapped[str] = mapped_column(String(6), nullable=False)  # debit | credit
    is_postable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_active: Mapped[bool] = _active()


class CostElement(EntityMixin, Base):
    __tablename__ = "cost_elements"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Null for Contingency (locked reserve, never posted directly).
    account_code: Mapped[str | None] = mapped_column(
        String(10), ForeignKey("accounts.code", ondelete="RESTRICT")
    )
    is_active: Mapped[bool] = _active()


class FiscalPeriod(EntityMixin, Base):
    __tablename__ = "fiscal_periods"
    __table_args__ = (UniqueConstraint("year", "month"),)

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # future | open | closed

    @property
    def code(self) -> str:
        return f"{self.year}-{self.month:02d}"


class PriceItem(EntityMixin, Base):
    """Price database for quotations: what GEK sells and what it costs."""

    __tablename__ = "price_items"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    cost_element_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("cost_elements.code", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = _active()


class Currency(EntityMixin, Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(3), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    decimals: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = _active()


class FxRate(EntityMixin, Base):
    """IDR per 1 unit of `currency` on `rate_date` (e.g. BI middle rate)."""

    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("currency", "rate_date"),)

    currency: Mapped[str] = mapped_column(
        String(3), ForeignKey("currencies.code", ondelete="RESTRICT"), nullable=False
    )
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="BI")

    @property
    def code(self) -> str:
        return f"{self.currency}-{self.rate_date.isoformat()}"
