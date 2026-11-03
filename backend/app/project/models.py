"""Projects and their budget (PROCESS.md · Project & budget). Budget editing, review and
locking come in phase 03; here a Draft project is created from a won opportunity."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin

# draft | controller_review | awaiting_approval | locked | closed
PROJECT_STATUSES = ("draft", "controller_review", "awaiting_approval", "locked", "closed")


class Project(EntityMixin, Base):
    __tablename__ = "projects"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="RESTRICT"), unique=True
    )
    client_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("clients.code", ondelete="RESTRICT"), index=True
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="draft")
    revenue: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    budget_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 0), nullable=False, server_default="0"
    )
    contingency_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0"
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    # Sales owner of the source opportunity (data scope "own" for sales roles).
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )


class ProjectBudgetLine(Base):
    """Budget per cost element, version 0 = the draft from the quotation."""

    __tablename__ = "project_budget_lines"
    __table_args__ = (UniqueConstraint("project_id", "version", "cost_element_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_element_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("cost_elements.code", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # quotation | contingency
