"""Append-only audit log: who did what, when, with before/after snapshots."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.logging import request_id_var
from app.core.models import Base


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    REJECT = "reject"
    POST = "post"
    REVERSE = "reverse"
    LOGIN = "login"


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_actor_at", "actor_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    changed: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        # Keep exact money values; never round-trip through float.
        return str(value)
    if isinstance(value, uuid.UUID | datetime | date):
        return str(value) if isinstance(value, uuid.UUID) else value.isoformat()
    return value


def _changed_keys(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    b, a = before or {}, after or {}
    return sorted(k for k in set(b) | set(a) if b.get(k) != a.get(k))


async def record(
    session: AsyncSession,
    *,
    action: AuditAction | str,
    entity_type: str,
    entity_id: uuid.UUID | str,
    actor_id: uuid.UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    note: str | None = None,
) -> AuditLog:
    """Add an audit row in the caller's transaction (it commits or rolls back with the change)."""
    before_j = _jsonable(before) if before is not None else None
    after_j = _jsonable(after) if after is not None else None
    entry = AuditLog(
        actor_id=actor_id,
        action=str(action),
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=before_j,
        after=after_j,
        changed=_changed_keys(before_j, after_j) or None,
        request_id=request_id_var.get(),
        note=note,
    )
    session.add(entry)
    await session.flush()
    return entry
