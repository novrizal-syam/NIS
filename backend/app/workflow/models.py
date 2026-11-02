"""DOA engine tables: rules (with ordered steps), approval requests and their steps,
delegations, and rule-change proposals (approved through the engine itself)."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import Base, EntityMixin


class DoaRule(EntityMixin, Base):
    __tablename__ = "doa_rules"

    doc_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Lower number is checked first; the first active rule whose condition matches wins.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    condition: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    escalation_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default="48")
    escalate_to_role: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    note: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")

    steps: Mapped[list["DoaRuleStep"]] = relationship(
        back_populates="rule",
        order_by="DoaRuleStep.seq",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DoaRuleStep(Base):
    """Steps with the same `seq` run in parallel; higher `seq` waits for lower ones."""

    __tablename__ = "doa_rule_steps"
    __table_args__ = (UniqueConstraint("rule_id", "seq", "approver_role"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doa_rules.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    # all = any holder of the role; project = holder assigned to the document's project.
    approver_scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="all")

    rule: Mapped[DoaRule] = relationship(back_populates="steps")


class ApprovalRequest(EntityMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        # One open request per document at a time.
        Index(
            "uq_approval_requests_open_doc",
            "doc_type",
            "doc_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    doc_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    doc_id: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_number: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="IDR")
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doa_rules.id", ondelete="SET NULL")
    )
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    current_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list["ApprovalStep"]] = relationship(
        back_populates="request",
        order_by="(ApprovalStep.seq, ApprovalStep.approver_role)",
        lazy="selectin",
    )


class ApprovalStep(Base):
    __tablename__ = "approval_steps"
    __table_args__ = (Index("ix_approval_steps_open", "status", "approver_role"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    approver_scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="all")
    # waiting -> pending -> approved | rejected | skipped
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    acted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    on_behalf_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    request: Mapped[ApprovalRequest] = relationship(back_populates="steps")


class Delegation(EntityMixin, Base):
    """While active, `delegate_id` may act on steps addressed to `role_code` held by
    `delegator_id` (all of the delegator's roles when role_code is null)."""

    __tablename__ = "doa_delegations"

    delegator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delegate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_code: Mapped[str | None] = mapped_column(String(50))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DoaRuleChange(EntityMixin, Base):
    """Proposed rule change. Applied only after a `doa_change` approval (Director)."""

    __tablename__ = "doa_rule_changes"

    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doa_rules.id", ondelete="CASCADE")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
