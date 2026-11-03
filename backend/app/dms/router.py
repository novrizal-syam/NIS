import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import CurrentUser, Principal, ensure_onboarded, get_principal_allow_pending
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, NotFoundError
from app.dms import service
from app.dms.models import Attachment
from app.services.storage import Storage, get_storage

router = APIRouter(prefix="/attachments", tags=["dms"])
Session = Annotated[AsyncSession, Depends(get_session)]
Store = Annotated[Storage, Depends(get_storage)]
PendingUser = Annotated[Principal, Depends(get_principal_allow_pending)]


def _onboarding_exception(principal: Principal, entity_type: str, entity_id: str) -> None:
    """Users still onboarding may only handle their own profile photo/signature."""
    if not (entity_type == "user_profile" and entity_id == str(principal.id)):
        ensure_onboarded(principal)


class AttachmentOut(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    version: int
    versions: int
    filename: str
    content_type: str
    size: int
    uploaded_by: str
    uploaded_at: datetime
    note: str | None


async def _names(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    rows = await session.execute(
        select(User.id, User.full_name).where(User.id.in_({i for i in ids if i}))
    )
    return {uid: name for uid, name in rows.all()}


def _out(a: Attachment, versions: int, names: dict[uuid.UUID, str]) -> AttachmentOut:
    return AttachmentOut(
        id=a.id,
        group_id=a.group_id,
        version=a.version,
        versions=versions,
        filename=a.filename,
        content_type=a.content_type,
        size=a.size,
        uploaded_by=names.get(a.created_by, "-") if a.created_by else "-",
        uploaded_at=a.uploaded_at,
        note=a.note,
    )


async def _get(
    session: AsyncSession, principal: CurrentUser, attachment_id: uuid.UUID, mode: access.Mode
) -> Attachment:
    att = await session.get(Attachment, attachment_id)
    if att is None:
        raise NotFoundError("ATTACHMENT_NOT_FOUND", "Lampiran tidak ditemukan.")
    await access.require(session, principal, att.entity_type, att.entity_id, mode)
    return att


@router.get("")
async def list_attachments(
    entity_type: str, entity_id: str, principal: CurrentUser, session: Session
) -> list[AttachmentOut]:
    await access.require(session, principal, entity_type, entity_id, "read")
    rows = await service.latest(session, entity_type, entity_id)
    names = await _names(session, {a.created_by for a, _ in rows})
    return [_out(a, n, names) for a, n in rows]


@router.get("/{attachment_id}/versions")
async def versions(
    attachment_id: uuid.UUID, principal: CurrentUser, session: Session
) -> list[AttachmentOut]:
    att = await _get(session, principal, attachment_id, "read")
    rows = (
        (
            await session.execute(
                select(Attachment)
                .where(Attachment.group_id == att.group_id)
                .order_by(Attachment.version.desc())
            )
        )
        .scalars()
        .all()
    )
    names = await _names(session, {r.created_by for r in rows})
    return [_out(r, len(rows), names) for r in rows]


@router.post("", status_code=201)
async def upload(
    principal: PendingUser,
    session: Session,
    storage: Store,
    entity_type: Annotated[str, Form(max_length=40)],
    entity_id: Annotated[str, Form(max_length=64)],
    file: Annotated[UploadFile, File()],
    replaces: Annotated[uuid.UUID | None, Form()] = None,
    note: Annotated[str | None, Form(max_length=300)] = None,
) -> AttachmentOut:
    _onboarding_exception(principal, entity_type, entity_id)
    await access.require(session, principal, entity_type, entity_id, "write")
    data = await file.read(service.MAX_BYTES + 1)
    att = await service.upload(
        session,
        storage,
        principal,
        entity_type=entity_type,
        entity_id=entity_id,
        filename=file.filename or "lampiran",
        data=data,
        replaces=replaces,
        note=note,
    )
    await session.commit()
    return _out(att, att.version, await _names(session, {principal.id}))


@router.get("/{attachment_id}/content")
async def content(
    attachment_id: uuid.UUID,
    principal: PendingUser,
    session: Session,
    storage: Store,
    download: bool = False,
) -> Response:
    """Streams through the API (not a public link) so permissions apply to every view."""
    att = await session.get(Attachment, attachment_id)
    if att is not None:
        _onboarding_exception(principal, att.entity_type, att.entity_id)
    att = await _get(session, principal, attachment_id, "read")
    obj = await storage.get(att.storage_key)
    disposition = "attachment" if download else "inline"
    return Response(
        obj.data,
        media_type=att.content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(att.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/{attachment_id}/archive", status_code=204)
async def archive(attachment_id: uuid.UUID, principal: CurrentUser, session: Session) -> Response:
    att = await _get(session, principal, attachment_id, "write")
    if att.archived_at is not None:
        raise AppError("ALREADY_ARCHIVED", "Lampiran sudah diarsipkan.", status_code=409)
    await service.archive(session, principal, att)
    await session.commit()
    return Response(status_code=204)
