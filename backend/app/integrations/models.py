"""WhatsApp outbox (10b)."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class WhatsAppMessage(EntityMixin, Base):
    """queued (live mode, delivered by job `whatsapp`) -> sent | failed;
    manual (no API credentials: staff open the wa.me link and mark it sent)."""

    __tablename__ = "whatsapp_outbox"

    to_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str | None] = mapped_column(String(40))
    link: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    provider_ref: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
