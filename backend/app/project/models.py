"""Projects and their budget (PROCESS.md · Project & budget). Budget editing, review and
locking come in phase 03; here a Draft project is created from a won opportunity."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
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
    # Budget approval (DOA project_budget)
    budget_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    budget_comment: Mapped[str | None] = mapped_column(String(1000))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectMember(Base):
    """Project team (field engineers, site staff). Members get the project in their
    project-scoped grants, like the project manager."""

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ProjectWbs(Base):
    """Work breakdown: default EXEC (Execution); MOB, DEMOB and per well (WELL-01 ...)."""

    __tablename__ = "project_wbs"
    __table_args__ = (UniqueConstraint("project_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)


class ProjectBudgetLine(Base):
    """Current budget: cost element x WBS. Editable only while the project is Draft; after
    lock it changes only through a BCR (phase 03c). `version` = budget version it belongs to."""

    __tablename__ = "project_budget_lines"
    __table_args__ = (UniqueConstraint("project_id", "version", "wbs_id", "cost_element_code"),)

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
    wbs_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_wbs.id", ondelete="RESTRICT"), nullable=False
    )
    cost_element_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("cost_elements.code", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # quotation | contingency | manual
    # Contingency: a locked reserve, released only through a BCR, never posted directly.
    locked_reserve: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class BudgetVersion(EntityMixin, Base):
    """Approved budget snapshot. v0 = baseline at lock; v1, v2 ... from BCRs. Immutable
    (database trigger rejects UPDATE; DELETE only for demo data)."""

    __tablename__ = "budget_versions"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # baseline | bcr
    revenue: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    margin_pct: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # BCR versions: what changed and why.
    note: Mapped[str | None] = mapped_column(String(1000))
    bcr_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("budget_change_requests.id", ondelete="RESTRICT")
    )


class BudgetChangeRequest(EntityMixin, Base):
    """BCR on a Locked project (PROCESS.md · BCR). Source: contingency_release |
    budget_increase | transfer. Approval (DOA bcr) creates the next budget version."""

    __tablename__ = "budget_change_requests"

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
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    # Transfer: the line the amount comes from. Contingency release: the contingency line.
    from_wbs_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_wbs.id", ondelete="RESTRICT")
    )
    from_cost_element_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("cost_elements.code", ondelete="RESTRICT")
    )
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    justification: Mapped[str] = mapped_column(String(2000), nullable=False)
    # Client variation order: revenue (contract value) increase, routes to the Director.
    revenue_change: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    increase_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    ref_doc_type: Mapped[str | None] = mapped_column(String(40))
    ref_doc_id: Mapped[str | None] = mapped_column(String(64))
    # submitted | approved | rejected | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="submitted")
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(String(1000))
    version: Mapped[int | None] = mapped_column(Integer)


class BudgetVersionLine(Base):
    __tablename__ = "budget_version_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budget_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wbs_code: Mapped[str] = mapped_column(String(20), nullable=False)
    wbs_name: Mapped[str] = mapped_column(String(120), nullable=False)
    cost_element_code: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    locked_reserve: Mapped[bool] = mapped_column(Boolean, nullable=False)


class BudgetLedgerEntry(Base):
    """Append-only budget consumption (CLAUDE.md rule 8; services/budget_control.py only).

    `kind` is the operation (pre_commit | commit | actual | release); `bucket` is the balance the
    row changes (pre_commit | commit | actual) and `amount` is signed. One operation may write
    several rows, e.g. a PO commit adds to `commit` and removes the PR's `pre_commit`.
    Balances are sums, never stored. A database trigger rejects UPDATE and DELETE."""

    __tablename__ = "budget_ledger"
    __table_args__ = (
        Index("ix_budget_ledger_line", "project_id", "wbs_id", "cost_element_code"),
        Index("ix_budget_ledger_doc", "doc_type", "doc_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    wbs_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_wbs.id", ondelete="RESTRICT"), nullable=False
    )
    cost_element_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("cost_elements.code", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    bucket: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False)
    doc_id: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
