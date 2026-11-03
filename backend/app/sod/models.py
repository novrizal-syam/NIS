import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class SodRule(EntityMixin, Base):
    """Two roles that must not be held by the same person (stored with role_a < role_b)."""

    __tablename__ = "sod_rules"
    __table_args__ = (UniqueConstraint("role_a", "role_b"),)

    role_a: Mapped[str] = mapped_column(String(50), nullable=False)
    role_b: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class SodException(EntityMixin, Base):
    """A user allowed to hold a conflicting pair, approved by the Director. Reviewed monthly
    by the Lead Controller."""

    __tablename__ = "sod_exceptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pairs: Mapped[list[list[str]]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    # The role change that is applied once approved.
    change: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # pending | approved | rejected | revoked
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    review_note: Mapped[str | None] = mapped_column(String(500))
