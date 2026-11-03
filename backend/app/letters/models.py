import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class OutgoingLetter(EntityMixin, Base):
    """Every numbered letter GEK sends. The number comes from services/numbering.next_letter
    in the same transaction, so numbers are gap-free per department and year."""

    __tablename__ = "outgoing_letters"
    __table_args__ = (Index("ix_outgoing_letters_entity", "entity_type", "entity_id"),)

    number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
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
