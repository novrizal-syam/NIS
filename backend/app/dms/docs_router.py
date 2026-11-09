"""DMS API (09): library, full-text search, share links, controlled documents."""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import CurrentUser, Principal, require
from app.core import access
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.dms import controlled as ctl
from app.dms import library as lib
from app.dms import watermark
from app.dms.models import (
    AccessLog,
    Attachment,
    ControlledDocument,
    DocumentRevision,
    LibraryDocument,
    ShareLink,
)
from app.services.storage import Storage, get_storage

router = APIRouter(prefix="/dms", tags=["dms"])
public_router = APIRouter(prefix="/public", tags=["dms"])
Session = Annotated[AsyncSession, Depends(get_session)]
Store = Annotated[Storage, Depends(get_storage)]
Viewer = Annotated[Principal, Depends(require("dms", "view"))]
Creator = Annotated[Principal, Depends(require("dms", "create"))]
Editor = Annotated[Principal, Depends(require("dms", "edit"))]


def _ctl_writer(p: Principal, doc: ControlledDocument | None = None) -> bool:
    return p.scope_for("dms", "edit") == Scope.ALL or (doc is not None and doc.owner_id == p.id)


async def _ctl_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    try:
        doc = await session.get(ControlledDocument, uuid.UUID(eid))
    except ValueError:
        return False
    if doc is None:
        return False
    return p.can("dms", "view") if mode == "read" else _ctl_writer(p, doc)


access.register(ctl.DOC, _ctl_access)


def _doc_out(d: LibraryDocument) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "category": d.category,
        "category_label": lib.CATEGORIES.get(d.category, d.category),
        "title": d.title,
        "folder": d.folder,
        "tags": d.tags,
        "description": d.description,
        "project_id": str(d.project_id) if d.project_id else None,
        "allowed_roles": d.allowed_roles,
        "issued_on": d.issued_on.isoformat() if d.issued_on else None,
        "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
        "retention_until": d.retention_until.isoformat(),
        "legal_hold": d.legal_hold,
        "legal_hold_reason": d.legal_hold_reason,
        "archived": d.archived_at is not None,
        "created_by": str(d.created_by) if d.created_by else None,
    }


# ---------------------------------------------------------------- library


class DocIn(BaseModel):
    category: str = Field(min_length=2, max_length=20)
    title: str = Field(min_length=2, max_length=300)
    folder: str | None = Field(default=None, max_length=300)
    tags: list[str] = Field(default_factory=list, max_length=20)
    description: str | None = Field(default=None, max_length=5000)
    project_id: uuid.UUID | None = None
    allowed_roles: list[str] = Field(default_factory=list, max_length=20)
    issued_on: date | None = None
    expiry_date: date | None = None


@router.get("/categories")
async def categories(_: Viewer) -> list[dict[str, str]]:
    return [{"value": k, "label": v} for k, v in lib.CATEGORIES.items()]


@router.get("/library")
async def list_library(
    p: Viewer,
    session: Session,
    category: str | None = None,
    tag: str | None = None,
    folder: str | None = None,
    expiring: bool = False,
) -> list[dict[str, Any]]:
    stmt = select(LibraryDocument).where(LibraryDocument.archived_at.is_(None))
    if category:
        stmt = stmt.where(LibraryDocument.category == category)
    if tag:
        stmt = stmt.where(LibraryDocument.tags.contains([tag.lower()]))
    if folder:
        stmt = stmt.where(LibraryDocument.folder.ilike(f"{folder}%"))
    if expiring:
        stmt = stmt.where(LibraryDocument.expiry_date.is_not(None)).order_by(
            LibraryDocument.expiry_date
        )
    rows = (await session.execute(stmt.order_by(LibraryDocument.title).limit(500))).scalars()
    return [_doc_out(d) for d in rows if lib.can_read(p, d)]


async def _doc(session: AsyncSession, p: Principal, did: uuid.UUID) -> LibraryDocument:
    d = await session.get(LibraryDocument, did)
    if d is None or not lib.can_read(p, d):
        raise NotFoundError("NOT_FOUND", "Dokumen tidak ditemukan.")
    return d


@router.post("/library")
async def create_doc(body: DocIn, actor: Creator, session: Session) -> dict[str, Any]:
    d = await lib.create(session, actor, body.model_dump())
    await session.commit()
    return _doc_out(d)


@router.get("/library/{did}")
async def get_doc(did: uuid.UUID, p: Viewer, session: Session) -> dict[str, Any]:
    d = await _doc(session, p, did)
    files = list(
        (
            await session.execute(
                select(Attachment.id).where(
                    Attachment.entity_type == lib.DOC, Attachment.entity_id == str(d.id)
                )
            )
        ).scalars()
    )
    log = await lib.access_log(session, files) if lib.can_write(p, d) else []
    names = dict((await session.execute(select(User.id, User.full_name))).tuples().all())
    return {
        **_doc_out(d),
        "can_write": lib.can_write(p, d),
        "access_log": [
            {
                "at": x.at.isoformat(),
                "user": names.get(x.user_id, "Tautan publik") if x.user_id else "Tautan publik",
                "action": x.action,
                "detail": x.detail,
            }
            for x in log
        ],
    }


@router.put("/library/{did}")
async def update_doc(
    did: uuid.UUID, body: DocIn, actor: Creator, session: Session
) -> dict[str, Any]:
    d = await lib.update(
        session, actor, await _doc(session, actor, did), body.model_dump(exclude={"category"})
    )
    await session.commit()
    return _doc_out(d)


class HoldIn(BaseModel):
    hold: bool
    reason: str | None = Field(default=None, max_length=500)


@router.post("/library/{did}/legal-hold")
async def legal_hold(
    did: uuid.UUID, body: HoldIn, actor: Viewer, session: Session
) -> dict[str, Any]:
    d = await lib.set_legal_hold(
        session, actor, await _doc(session, actor, did), body.hold, body.reason
    )
    await session.commit()
    return _doc_out(d)


@router.post("/library/{did}/archive")
async def archive_doc(did: uuid.UUID, actor: Creator, session: Session) -> dict[str, Any]:
    d = await _doc(session, actor, did)
    await lib.archive(session, actor, d)
    await session.commit()
    return _doc_out(d)


@router.get("/search")
async def search(
    p: Viewer, session: Session, q: str, category: str | None = None, tag: str | None = None
) -> list[dict[str, Any]]:
    return await lib.search(session, p, q, category=category, tag=tag)


# ---------------------------------------------------------------- share links


class ShareIn(BaseModel):
    days: int = Field(ge=1, le=lib.MAX_SHARE_DAYS)
    note: str | None = Field(default=None, max_length=200)


@router.post("/files/{attachment_id}/share")
async def share(
    attachment_id: uuid.UUID, body: ShareIn, actor: Creator, session: Session
) -> dict[str, Any]:
    att = await session.get(Attachment, attachment_id)
    if att is None:
        raise NotFoundError("ATTACHMENT_NOT_FOUND", "Lampiran tidak ditemukan.")
    await access.require(session, actor, att.entity_type, att.entity_id, "write")
    link, token = await lib.share(session, actor, att, body.days, body.note)
    await session.commit()
    return {
        "id": str(link.id),
        "url": f"/api/public/share/{token}",
        "expires_at": link.expires_at.isoformat(),
    }


@router.post("/share-links/{lid}/revoke", status_code=204)
async def revoke(lid: uuid.UUID, actor: Creator, session: Session) -> Response:
    link = await session.get(ShareLink, lid)
    if link is None:
        raise NotFoundError("NOT_FOUND", "Tautan tidak ditemukan.")
    att = await session.get(Attachment, link.attachment_id)
    if att is None:
        raise NotFoundError("NOT_FOUND", "Tautan tidak ditemukan.")
    await access.require(session, actor, att.entity_type, att.entity_id, "write")
    await lib.revoke_share(session, actor, link)
    await session.commit()
    return Response(status_code=204)


@public_router.get("/share/{token}")
async def public_share(token: str, session: Session, storage: Store) -> Response:
    _, att = await lib.resolve_share(session, token)
    obj = await storage.get(att.storage_key)
    await session.commit()
    return Response(
        obj.data,
        media_type=att.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(att.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


# ---------------------------------------------------------------- controlled documents


class ControlledIn(BaseModel):
    code: str = Field(min_length=3, max_length=40)
    title: str = Field(min_length=3, max_length=300)
    kind: Literal["sop", "form", "manual", "policy"]
    system: str | None = Field(default=None, max_length=30)
    department: str | None = Field(default=None, max_length=10)
    owner_id: uuid.UUID | None = None
    review_months: int = Field(default=12, ge=1, le=60)
    affected_roles: list[str] = Field(default_factory=list, max_length=30)


def _rev_out(r: DocumentRevision) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "revision": r.revision,
        "status": r.status,
        "change_summary": r.change_summary,
        "attachment_id": str(r.attachment_id) if r.attachment_id else None,
        "effective_date": r.effective_date.isoformat() if r.effective_date else None,
        "request_id": str(r.request_id) if r.request_id else None,
        "reject_reason": r.reject_reason,
    }


def _ctl_out(d: ControlledDocument) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "code": d.code,
        "title": d.title,
        "kind": d.kind,
        "system": d.system,
        "department": d.department,
        "owner_id": str(d.owner_id) if d.owner_id else None,
        "review_months": d.review_months,
        "affected_roles": d.affected_roles,
        "current_revision": d.current_revision,
        "effective_date": d.effective_date.isoformat() if d.effective_date else None,
        "next_review": d.next_review.isoformat() if d.next_review else None,
    }


@router.get("/controlled")
async def list_controlled(
    _: Viewer,
    session: Session,
    kind: str | None = None,
    system: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(ControlledDocument).order_by(ControlledDocument.code)
    if kind:
        stmt = stmt.where(ControlledDocument.kind == kind)
    if system:
        stmt = stmt.where(ControlledDocument.system == system)
    if q:
        stmt = stmt.where(
            ControlledDocument.code.ilike(f"%{q}%") | ControlledDocument.title.ilike(f"%{q}%")
        )
    return [_ctl_out(d) for d in (await session.execute(stmt.limit(1000))).scalars()]


@router.post("/controlled")
async def create_controlled(body: ControlledIn, actor: Editor, session: Session) -> dict[str, Any]:
    if not _ctl_writer(actor):
        raise ForbiddenError(
            "PERMISSION_DENIED", "Hanya pengelola dokumen yang dapat mendaftarkan."
        )
    d = await ctl.create(session, actor, body.model_dump())
    await session.commit()
    return _ctl_out(d)


@router.post("/controlled/import")
async def import_controlled(
    actor: Editor, session: Session, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    if not _ctl_writer(actor):
        raise ForbiddenError("PERMISSION_DENIED", "Hanya pengelola dokumen yang dapat mengimpor.")
    out = await ctl.import_register(session, actor, await file.read())
    await session.commit()
    return out


async def _ctl(session: AsyncSession, did: uuid.UUID) -> ControlledDocument:
    d = await session.get(ControlledDocument, did)
    if d is None:
        raise NotFoundError("NOT_FOUND", "Dokumen terkendali tidak ditemukan.")
    return d


@router.get("/controlled/{did}")
async def get_controlled(did: uuid.UUID, p: Viewer, session: Session) -> dict[str, Any]:
    d = await _ctl(session, did)
    revs = await ctl.revisions(session, d.id)
    writer = _ctl_writer(p, d)
    return {
        **_ctl_out(d),
        "can_write": writer,
        # Readers see the effective revision; managers see the history too.
        "revisions": [_rev_out(r) for r in revs if writer or r.status == "effective"],
    }


class RevisionIn(BaseModel):
    change_summary: str = Field(min_length=5, max_length=1000)
    attachment_id: uuid.UUID
    effective_date: date | None = None


@router.post("/controlled/{did}/revisions")
async def draft_revision(
    did: uuid.UUID, body: RevisionIn, actor: Editor, session: Session
) -> dict[str, Any]:
    d = await _ctl(session, did)
    if not _ctl_writer(actor, d):
        raise ForbiddenError("PERMISSION_DENIED", "Anda bukan pemilik dokumen ini.")
    r = await ctl.draft_revision(
        session,
        actor,
        d,
        change_summary=body.change_summary,
        attachment_id=body.attachment_id,
        effective_date=body.effective_date,
    )
    await session.commit()
    return _rev_out(r)


@router.post("/controlled/{did}/revisions/{rid}/submit")
async def submit_revision(
    did: uuid.UUID, rid: uuid.UUID, actor: Editor, session: Session
) -> dict[str, Any]:
    d = await _ctl(session, did)
    r = await session.get(DocumentRevision, rid, with_for_update=True)
    if r is None or r.document_id != d.id:
        raise NotFoundError("NOT_FOUND", "Revisi tidak ditemukan.")
    if not _ctl_writer(actor, d):
        raise ForbiddenError("PERMISSION_DENIED", "Anda bukan pemilik dokumen ini.")
    req = await ctl.submit(session, actor, d, r)
    await session.commit()
    return {**_rev_out(r), "request_id": str(req.id)}


WATERMARKS = {"effective": "SALINAN TERKENDALI", "uncontrolled": "TIDAK TERKENDALI"}


@router.get("/controlled/{did}/revisions/{rid}/pdf")
async def revision_pdf(
    did: uuid.UUID, rid: uuid.UUID, p: CurrentUser, session: Session, storage: Store
) -> Response:
    d = await _ctl(session, did)
    r = await session.get(DocumentRevision, rid)
    if r is None or r.document_id != d.id or r.attachment_id is None:
        raise NotFoundError("NOT_FOUND", "Revisi tidak ditemukan.")
    if not p.can("dms", "view") or (r.status != "effective" and not _ctl_writer(p, d)):
        raise NotFoundError("NOT_FOUND", "Revisi tidak ditemukan.")
    att = await session.get(Attachment, r.attachment_id)
    assert att is not None
    obj = await storage.get(att.storage_key)
    headline = WATERMARKS.get(r.status, "DRAF - BELUM BERLAKU")
    stamped = watermark.stamp(
        obj.data,
        headline,
        f"{d.code} Rev.{r.revision} · dicetak {p.user.full_name} "
        f"{datetime.now(UTC):%d/%m/%Y %H:%M} UTC · salinan cetak tidak terkendali",
    )
    session.add(AccessLog(attachment_id=att.id, user_id=p.id, action="download", detail=headline))
    await session.commit()
    return Response(
        stamped,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"inline; filename*=UTF-8''{quote(f'{d.code}-Rev{r.revision}.pdf')}"
            ),
            "Cache-Control": "private, no-store",
        },
    )
