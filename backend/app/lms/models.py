"""Learning (09 LMS): positions and competency matrix, course catalogue, classroom sessions,
assignments (incl. read-and-acknowledge of controlled documents), training budget."""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class Position(EntityMixin, Base):
    """Job description (e.g. the 19 positions of GEK's organisation)."""

    __tablename__ = "positions"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Course(EntityMixin, Base):
    __tablename__ = "courses"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # video | pdf | quiz | scorm | classroom | practical
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    duration_hours: Mapped[Decimal] = mapped_column(
        Numeric(6, 1), nullable=False, server_default="1"
    )
    validity_months: Mapped[int | None] = mapped_column(Integer)  # None = does not expire
    # Completing the course renews this employee certificate (mobilisation gate), e.g. "H2S".
    certificate_name: Mapped[str | None] = mapped_column(String(120))
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    pass_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="70")
    # Quiz: [{"q": str, "options": [str], "answer": int}]
    questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Requirement(Base):
    """Competency matrix: a position needs a course (mandatory or recommended)."""

    __tablename__ = "competency_requirements"
    __table_args__ = (UniqueConstraint("position_code", "course_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    position_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("positions.code", ondelete="CASCADE"), nullable=False
    )
    course_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("courses.code", ondelete="CASCADE"), nullable=False
    )
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class CourseSession(EntityMixin, Base):
    """Classroom or supervised practical session with attendance."""

    __tablename__ = "course_sessions"

    course_code: Mapped[str] = mapped_column(
        String(30), ForeignKey("courses.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    trainer: Mapped[str | None] = mapped_column(String(120))
    supervisor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    capacity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="planned")
    # [{"employee_code", "attended", "passed", "score"}]
    attendance: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )


class Assignment(EntityMixin, Base):
    """Training to do: a course, or reading and acknowledging a controlled document revision.

    assigned -> completed | cancelled. Reason: onboarding | matrix | certificate_expiry |
    sop_revision | manual."""

    __tablename__ = "training_assignments"
    __table_args__ = (
        Index("uq_training_assignment_key", "dedupe_key", unique=True),
        Index("ix_training_assignment_owner", "employee_code", "user_id", "status"),
    )

    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # course | acknowledge
    employee_code: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("employees.code", ondelete="RESTRICT")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    course_code: Mapped[str | None] = mapped_column(
        String(30), ForeignKey("courses.code", ondelete="RESTRICT")
    )
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="RESTRICT")
    )
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="assigned")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False, server_default="0")
    evidence_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id", ondelete="RESTRICT")
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(500))


class TrainingBudget(EntityMixin, Base):
    __tablename__ = "training_budgets"
    __table_args__ = (UniqueConstraint("year", "department_code"),)

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    department_code: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0), nullable=False)
