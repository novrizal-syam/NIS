"""Data breach log (UU 27/2022 PDP art. 46: notify data subjects and the authority within
3 x 24 hours of becoming aware of a breach)."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class DataBreach(EntityMixin, Base):
    """reported -> investigating -> notified (subjects and authority) -> closed."""

    __tablename__ = "data_breaches"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # nik | salary | bank_account | tax_id | contact | health | other
    data_categories: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False)
    affected_count: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, server_default="medium")
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="reported")
    containment: Mapped[str | None] = mapped_column(Text)
    subjects_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authority_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authority_reference: Mapped[str | None] = mapped_column(String(120))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lessons: Mapped[str | None] = mapped_column(Text)
