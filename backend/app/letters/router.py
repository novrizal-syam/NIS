"""Letters API (09): incoming register + disposisi, outgoing drafts, templates, sent log."""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import CurrentUser, Principal, require
from app.core import access
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.dms.models import Attachment
from app.letters import service as svc
from app.letters.models import IncomingLetter, LetterDisposition, LetterTemplate, OutgoingLetter
from app.services.storage import Storage, get_storage

router = APIRouter(prefix="/letters", tags=["letters"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("letters", "view"))]
Creator = Annotated[Principal, Depends(require("letters", "create"))]
Submitter = Annotated[Principal, Depends(require("letters", "submit"))]


def _all(p: Principal) -> bool:
    return p.scope_for("letters", "view") == Scope.ALL


async def _is_pic(session: AsyncSession, p: Principal, letter_id: uuid.UUID) -> bool:
    return (
        await session.execute(
            select(LetterDisposition.id).where(
                LetterDisposition.letter_id == letter_id, LetterDisposition.pic_id == p.id
            )
        )
    ).first() is not None


async def _can_read_in(session: AsyncSession, p: Principal, letter: IncomingLetter) -> bool:
    return _all(p) or await _is_pic(session, p, letter.id)


async def _in_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    try:
        letter = await session.get(IncomingLetter, uuid.UUID(eid))
    except ValueError:
        return False
    if letter is None:
        return False
    if mode == "read":
        return await _can_read_in(session, p, letter)
    return p.can("letters", "edit")


async def _out_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    return p.can("letters", "view" if mode == "read" else "edit")


access.register(svc.IN_DOC, _in_access)
access.register(svc.OUT_DOC, _out_access)


def _in_out(x: IncomingLetter) -> dict[str, Any]:
    return {
        "id": str(x.id),
        "number": x.number,
        "received_on": x.received_on.isoformat(),
        "sender": x.sender,
        "sender_ref": x.sender_ref,
        "letter_date": x.letter_date.isoformat() if x.letter_date else None,
        "subject": x.subject,
        "summary": x.summary,
        "confidential": x.confidential,
        "status": x.status,
        "file_id": str(x.file_id) if x.file_id else None,
        "close_note": x.close_note,
    }


def _out_out(x: OutgoingLetter) -> dict[str, Any]:
    return {
        "id": str(x.id),
        "number": x.number,
        "status": x.status,
        "department": x.department,
        "to": x.to,
        "subject": x.subject,
        "body": x.body,
        "letter_date": x.letter_date.isoformat(),
        "template_code": x.template_code,
        "signer_name": x.signer_name,
        "needs_meterai": x.needs_meterai,
        "request_id": str(x.request_id) if x.request_id else None,
        "reject_reason": x.reject_reason,
        "esign_ref": x.esign_ref,
        "emeterai_ref": x.emeterai_ref,
        "sent_at": x.sent_at.isoformat() if x.sent_at else None,
        "sent_via": x.sent_via,
        "sent_to": x.sent_to,
        "file_id": str(x.file_id) if x.file_id else None,
        "in_reply_to": str(x.in_reply_to) if x.in_reply_to else None,
    }


# ---------------------------------------------------------------- incoming


class IncomingIn(BaseModel):
    received_on: date
    sender: str = Field(min_length=2, max_length=300)
    sender_ref: str | None = Field(default=None, max_length=120)
    letter_date: date | None = None
    subject: str = Field(min_length=2, max_length=300)
    summary: str | None = Field(default=None, max_length=5000)
    confidential: bool = False
    project_id: uuid.UUID | None = None


@router.get("/incoming")
async def list_incoming(
    p: CurrentUser, session: Session, status: str | None = None, q: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(IncomingLetter).order_by(
        IncomingLetter.received_on.desc(), IncomingLetter.number.desc()
    )
    if not _all(p):
        stmt = stmt.where(
            IncomingLetter.id.in_(
                select(LetterDisposition.letter_id).where(LetterDisposition.pic_id == p.id)
            )
        )
    if status:
        stmt = stmt.where(IncomingLetter.status == status)
    if q:
        like = f"%{q}%"
        files = select(Attachment.entity_id).where(
            Attachment.entity_type == svc.IN_DOC, Attachment.text_content.ilike(like)
        )
        stmt = stmt.where(
            IncomingLetter.subject.ilike(like)
            | IncomingLetter.sender.ilike(like)
            | IncomingLetter.number.ilike(like)
            | IncomingLetter.summary.ilike(like)
            | cast(IncomingLetter.id, String).in_(files)
        )
    return [_in_out(x) for x in (await session.execute(stmt.limit(300))).scalars()]


@router.post("/incoming")
async def register(body: IncomingIn, actor: Creator, session: Session) -> dict[str, Any]:
    x = await svc.register_incoming(session, actor, body.model_dump())
    await session.commit()
    return _in_out(x)


async def _incoming(session: AsyncSession, p: Principal, lid: uuid.UUID) -> IncomingLetter:
    x = await session.get(IncomingLetter, lid)
    if x is None or not await _can_read_in(session, p, x):
        raise NotFoundError("NOT_FOUND", "Surat tidak ditemukan.")
    return x


@router.get("/incoming/{lid}")
async def get_incoming(lid: uuid.UUID, p: CurrentUser, session: Session) -> dict[str, Any]:
    x = await _incoming(session, p, lid)
    names = dict((await session.execute(select(User.id, User.full_name))).tuples().all())
    replies = (
        await session.execute(select(OutgoingLetter).where(OutgoingLetter.in_reply_to == x.id))
    ).scalars()
    return {
        **_in_out(x),
        "dispositions": [
            {
                "id": str(d.id),
                "pic_id": str(d.pic_id),
                "pic": names.get(d.pic_id),
                "instruction": d.instruction,
                "deadline": d.deadline.isoformat(),
                "status": d.status,
                "done_note": d.done_note,
            }
            for d in await svc.dispositions(session, x.id)
        ],
        "replies": [_out_out(r) for r in replies],
    }


class ScanIn(BaseModel):
    attachment_id: uuid.UUID


@router.post("/incoming/{lid}/scan")
async def set_scan(
    lid: uuid.UUID, body: ScanIn, actor: Creator, session: Session
) -> dict[str, Any]:
    x = await _incoming(session, actor, lid)
    att = await session.get(Attachment, body.attachment_id)
    if att is None:
        raise NotFoundError("NOT_FOUND", "File tidak ditemukan.")
    await svc.attach_scan(session, actor, x, att)
    await session.commit()
    return _in_out(x)


class DisposeIn(BaseModel):
    pic_id: uuid.UUID
    instruction: str = Field(min_length=3, max_length=1000)
    deadline: date


@router.post("/incoming/{lid}/dispositions")
async def dispose(
    lid: uuid.UUID, body: DisposeIn, actor: Creator, session: Session
) -> dict[str, Any]:
    x = await _incoming(session, actor, lid)
    d = await svc.dispose(
        session, actor, x, pic_id=body.pic_id, instruction=body.instruction, deadline=body.deadline
    )
    await session.commit()
    return {"id": str(d.id), "status": d.status}


class NoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


@router.post("/dispositions/{did}/done")
async def disposition_done(
    did: uuid.UUID, body: NoteIn, p: CurrentUser, session: Session
) -> dict[str, Any]:
    d = await session.get(LetterDisposition, did, with_for_update=True)
    if d is None:
        raise NotFoundError("NOT_FOUND", "Disposisi tidak ditemukan.")
    await svc.complete_disposition(session, p, d, body.note)
    await session.commit()
    return {"id": str(d.id), "status": d.status}


class CloseIn(BaseModel):
    reply_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)


@router.post("/incoming/{lid}/close")
async def close(lid: uuid.UUID, body: CloseIn, actor: Creator, session: Session) -> dict[str, Any]:
    x = await _incoming(session, actor, lid)
    await svc.close_incoming(session, actor, x, reply_id=body.reply_id, note=body.note)
    await session.commit()
    return _in_out(x)


# ---------------------------------------------------------------- outgoing


class OutgoingIn(BaseModel):
    department: str = Field(min_length=2, max_length=10)
    to: str = Field(min_length=2, max_length=300)
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=20000)
    template_code: str | None = Field(default=None, max_length=30)
    values: dict[str, str] = Field(default_factory=dict)
    signer_name: str | None = Field(default=None, max_length=120)
    needs_meterai: bool = False
    in_reply_to: uuid.UUID | None = None


@router.get("/outgoing")
async def list_outgoing(
    _: Viewer, session: Session, status: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(OutgoingLetter).order_by(OutgoingLetter.created_at.desc())
    if status:
        stmt = stmt.where(OutgoingLetter.status == status)
    return [_out_out(x) for x in (await session.execute(stmt.limit(300))).scalars()]


@router.post("/outgoing")
async def draft(body: OutgoingIn, actor: Creator, session: Session) -> dict[str, Any]:
    x = await svc.draft_outgoing(session, actor, body.model_dump())
    await session.commit()
    return _out_out(x)


async def _outgoing(session: AsyncSession, lid: uuid.UUID) -> OutgoingLetter:
    x = await session.get(OutgoingLetter, lid, with_for_update=True)
    if x is None:
        raise NotFoundError("NOT_FOUND", "Surat tidak ditemukan.")
    return x


@router.get("/outgoing/{lid}")
async def get_outgoing(lid: uuid.UUID, _: Viewer, session: Session) -> dict[str, Any]:
    return _out_out(await _outgoing(session, lid))


@router.post("/outgoing/{lid}/submit")
async def submit(lid: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    x = await _outgoing(session, lid)
    req = await svc.submit_outgoing(session, actor, x)
    await session.commit()
    return {**_out_out(x), "request_id": str(req.id)}


class SendIn(BaseModel):
    via: Literal["email", "courier", "hand", "portal"]
    sent_to: str | None = Field(default=None, max_length=300)


@router.post("/outgoing/{lid}/send")
async def send(
    lid: uuid.UUID,
    body: SendIn,
    actor: Creator,
    session: Session,
    storage: Annotated[Storage, Depends(get_storage)],
) -> dict[str, Any]:
    x = await svc.send_outgoing(
        session, storage, actor, await _outgoing(session, lid), via=body.via, sent_to=body.sent_to
    )
    await session.commit()
    return _out_out(x)


# ---------------------------------------------------------------- templates


class TemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=120)
    subject: str = Field(min_length=2, max_length=300)
    body: str = Field(min_length=2, max_length=20000)
    is_active: bool = True


@router.get("/templates")
async def templates(_: Viewer, session: Session) -> list[dict[str, Any]]:
    rows = (await session.execute(select(LetterTemplate).order_by(LetterTemplate.code))).scalars()
    return [
        {
            "code": t.code,
            "name": t.name,
            "subject": t.subject,
            "body": t.body,
            "is_active": t.is_active,
            "placeholders": sorted(set(svc._PLACEHOLDER.findall(t.subject + t.body))),
        }
        for t in rows
    ]


@router.put("/templates/{code}")
async def save_template(
    code: str, body: TemplateIn, actor: Creator, session: Session
) -> dict[str, Any]:
    t = (
        await session.execute(select(LetterTemplate).where(LetterTemplate.code == code))
    ).scalar_one_or_none()
    if t is None:
        t = LetterTemplate(
            code=body.code,
            created_by=actor.id,
            name=body.name,
            subject=body.subject,
            body=body.body,
        )
        session.add(t)
    t.name, t.subject, t.body, t.is_active = body.name, body.subject, body.body, body.is_active
    await session.commit()
    return {"code": t.code}


@router.get("/people")
async def people(_: Viewer, session: Session) -> list[dict[str, str]]:
    """Active users to pick as disposisi PIC."""
    rows = (
        await session.execute(
            select(User.id, User.full_name).where(User.is_active.is_(True)).order_by(User.full_name)
        )
    ).all()
    return [{"id": str(i), "name": n} for i, n in rows]
