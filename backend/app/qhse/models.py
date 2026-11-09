"""QHSE (PROCESS.md · QHSE; prompt 05b): HIRADC/JSA, permits to work, inspections,
observations, incidents with investigation, CAPA; statistics from DOR man-hours."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin

INCIDENT_CATEGORIES = (
    "near_miss",
    "first_aid",
    "medical_treatment",
    "restricted_work",
    "lost_time",
    "fatality",
    "property_damage",
    "environmental",
)
RECORDABLE = ("medical_treatment", "restricted_work", "lost_time", "fatality")
LOST_TIME = ("lost_time", "fatality")
PERMIT_TYPES = (
    "hot_work",
    "confined_space",
    "work_at_height",
    "electrical",
    "lifting",
    "excavation",
    "general",
)


def _project(nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=nullable,
        index=True,
    )


def _user(nullable: bool = True) -> Mapped[uuid.UUID | None]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=nullable
    )


def _json_list() -> Mapped[list[dict[str, Any]]]:
    return mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class RiskAssessment(EntityMixin, Base):
    """HIRADC (project) or JSA (task). Rows: activity, hazard, likelihood x severity (1-5),
    controls, residual likelihood x severity."""

    __tablename__ = "qhse_risk_assessments"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = _project()
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # hiradc | jsa
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    hazards: Mapped[list[dict[str, Any]]] = _json_list()
    approved_by: Mapped[uuid.UUID | None] = _user()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Permit(EntityMixin, Base):
    __tablename__ = "qhse_permits"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = _project()
    permit_type: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    work_description: Mapped[str] = mapped_column(Text, nullable=False)
    precautions: Mapped[list[dict[str, Any]]] = _json_list()
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # requested | approved | closed | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="requested")
    approved_by: Mapped[uuid.UUID | None] = _user()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Inspection(EntityMixin, Base):
    __tablename__ = "qhse_inspections"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID | None] = _project(nullable=True)
    inspection_type: Mapped[str] = mapped_column(String(60), nullable=False)
    inspection_date: Mapped[date] = mapped_column(Date, nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    checklist: Mapped[list[dict[str, Any]]] = _json_list()
    findings: Mapped[str | None] = mapped_column(Text)


class Observation(EntityMixin, Base):
    __tablename__ = "qhse_observations"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID | None] = _project(nullable=True)
    obs_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken: Mapped[str | None] = mapped_column(Text)


class Incident(EntityMixin, Base):
    __tablename__ = "qhse_incidents"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID | None] = _project(nullable=True)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    lost_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # reported | investigating | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="reported")
    root_cause: Mapped[str | None] = mapped_column(Text)
    investigation: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Capa(EntityMixin, Base):
    """Corrective / preventive action with an owner and a due date."""

    __tablename__ = "qhse_capas"

    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    project_id: Mapped[uuid.UUID | None] = _project(nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # open | done | verified
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    completion_note: Mapped[str | None] = mapped_column(Text)
    done_by: Mapped[uuid.UUID | None] = _user()
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = _user()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
