import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, EntityMixin


class Attachment(EntityMixin, Base):
    """One version of a file attached to any record. Versions of the same file share
    `group_id`; files are archived, never deleted (retention)."""

    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_entity", "entity_type", "entity_id"),
        Index("ix_attachments_group", "group_id", "version", unique=True),
    )

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    note: Mapped[str | None] = mapped_column(String(300))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Text layer of PDFs (or OCR output) for full-text search (09).
    text_content: Mapped[str | None] = mapped_column(Text)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccessLog(Base):
    """Every view/download of a stored file and every share-link use (09)."""

    __tablename__ = "dms_access_log"
    __table_args__ = (Index("ix_dms_access_attachment", "attachment_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # view | download | share
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    detail: Mapped[str | None] = mapped_column(String(200))


class LibraryDocument(EntityMixin, Base):
    """Library entry (company legal documents, contracts, certificates, OEM manuals, MSDS,
    project folders, reusable tender documents, restricted HR files). Files and versions are
    attachments with entity_type `library_doc`."""

    __tablename__ = "library_documents"

    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    folder: Mapped[str | None] = mapped_column(String(300))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, server_default="{}")
    description: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )
    # Empty = everyone with DMS access; otherwise only these role codes (plus Super Admin).
    allowed_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, server_default="{}"
    )
    issued_on: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    retention_until: Mapped[date] = mapped_column(Date, nullable=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    legal_hold_reason: Mapped[str | None] = mapped_column(String(500))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShareLink(Base):
    """Time-limited public link to one file version (token stored hashed)."""

    __tablename__ = "dms_share_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    downloads: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    note: Mapped[str | None] = mapped_column(String(200))


class ControlledDocument(EntityMixin, Base):
    """Controlled document (SOP, form, manual, policy) in a management system such as
    GEK-BPM-001 or GEK-MNT-001."""

    __tablename__ = "controlled_documents"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # sop | form | manual | policy
    system: Mapped[str | None] = mapped_column(String(30))  # e.g. GEK-BPM-001
    department: Mapped[str | None] = mapped_column(String(10))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    review_months: Mapped[int] = mapped_column(Integer, nullable=False, server_default="12")
    # Role codes whose holders must read and acknowledge a new effective revision.
    affected_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, server_default="{}"
    )
    current_revision: Mapped[int | None] = mapped_column(Integer)
    effective_date: Mapped[date | None] = mapped_column(Date)
    next_review: Mapped[date | None] = mapped_column(Date)


class DocumentRevision(EntityMixin, Base):
    """draft -> awaiting_approval (DOA sop_release, Director) -> effective; the previous
    effective revision becomes uncontrolled. Rejected -> draft."""

    __tablename__ = "document_revisions"
    __table_args__ = (Index("uq_document_revision", "document_id", "revision", unique=True),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("controlled_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    change_summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attachments.id", ondelete="RESTRICT")
    )
    effective_date: Mapped[date | None] = mapped_column(Date)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reject_reason: Mapped[str | None] = mapped_column(String(1000))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
