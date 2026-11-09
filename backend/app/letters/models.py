import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class OutgoingLetter(EntityMixin, Base):
    """Every numbered letter GEK sends. The number comes from services/numbering.next_letter
    in the same transaction, so numbers are gap-free per department and year."""

    __tablename__ = "outgoing_letters"
    __table_args__ = (Index("ix_outgoing_letters_entity", "entity_type", "entity_id"),)

    # Assigned at approval (gap-free); drafts have none.
    number: Mapped[str | None] = mapped_column(String(40), unique=True)
    department: Mapped[str] = mapped_column(String(10), nullable=False)
    to: Mapped[str] = mapped_column(String(300), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    letter_date: Mapped[date] = mapped_column(Date, nullable=False)
    # The signed/sent file in the DMS.
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id", ondelete="RESTRICT")
    )
    # The business record the letter belongs to (e.g. quotation).
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    # 09: drafted letters - draft -> awaiting_approval (DOA outgoing_letter, Director)
    # -> approved (number, PDF, e-sign, e-Meterai) -> sent. Letters reserved by other modules
    # (quotation) are created as `sent`.
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="sent")
    template_code: Mapped[str | None] = mapped_column(String(30))
    body: Mapped[str | None] = mapped_column(Text)
    signer_name: Mapped[str | None] = mapped_column(String(120))
    needs_meterai: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    reject_reason: Mapped[str | None] = mapped_column(String(1000))
    esign_ref: Mapped[str | None] = mapped_column(String(80))
    emeterai_ref: Mapped[str | None] = mapped_column(String(80))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_via: Mapped[str | None] = mapped_column(String(30))  # email | courier | hand | portal
    sent_to: Mapped[str | None] = mapped_column(String(300))
    in_reply_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incoming_letters.id", ondelete="RESTRICT")
    )


class LetterTemplate(EntityMixin, Base):
    """Outgoing letter template; {placeholders} are filled when drafting."""

    __tablename__ = "letter_templates"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class IncomingLetter(EntityMixin, Base):
    """Registered -> routed (disposisi) -> closed (reply letter linked or closed with note)."""

    __tablename__ = "incoming_letters"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    sender: Mapped[str] = mapped_column(String(300), nullable=False)
    sender_ref: Mapped[str | None] = mapped_column(String(120))
    letter_date: Mapped[date | None] = mapped_column(Date)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    confidential: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="registered")
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id", ondelete="RESTRICT")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_note: Mapped[str | None] = mapped_column(String(1000))


class LetterDisposition(EntityMixin, Base):
    """Disposisi: who handles an incoming letter, what to do and by when."""

    __tablename__ = "letter_dispositions"

    letter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incoming_letters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    instruction: Mapped[str] = mapped_column(String(1000), nullable=False)
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_note: Mapped[str | None] = mapped_column(String(1000))
