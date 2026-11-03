"""email_log: one row per send attempt (never the token or link). Delivery runs in a
background task with its own database session."""

import logging
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import session_scope
from app.core.models import Base
from app.services import email
from app.services.email_templates import Rendered

log = logging.getLogger("app.email")


class EmailLog(Base):
    __tablename__ = "email_log"
    __table_args__ = (Index("ix_email_log_user_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    to: Mapped[str] = mapped_column(String(254), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # sent | failed | not_configured
    error: Mapped[str | None] = mapped_column(String(500))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


async def deliver(
    kind: str,
    to: str,
    message: Rendered,
    user_id: uuid.UUID | None,
    attachments: tuple[email.Attachment, ...] = (),
) -> email.Result:
    """Send and record the outcome. Meant for BackgroundTasks (runs after the response)."""
    result = await email.send_email(
        to, message.subject, message.html, message.text, attachments=attachments
    )
    async with session_scope() as session:
        session.add(
            EmailLog(to=to, kind=kind, status=result.status, error=result.error, user_id=user_id)
        )
        await session.commit()
    if result.status == "failed":
        log.warning("email_failed", extra={"kind": kind, "error": result.error})
    return result
