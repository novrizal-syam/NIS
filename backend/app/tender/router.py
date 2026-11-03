import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import Principal, require, scope_filter
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.crm.models import Opportunity
from app.services import audit
from app.services.audit import AuditAction
from app.tender import service
from app.tender.models import Tender, TenderClarification, TenderDocument

router = APIRouter(prefix="/tenders", tags=["tender"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("tender", "view"))]
Creator = Annotated[Principal, Depends(require("tender", "create"))]
Editor = Annotated[Principal, Depends(require("tender", "edit"))]
Submitter = Annotated[Principal, Depends(require("tender", "submit"))]

Method = Literal["open", "limited", "selection", "direct"]
Channel = Literal["eproc", "civd", "hardcopy", "email"]
Result = Literal["won", "lost", "disqualified", "cancelled"]


def may(principal: Principal, action: str, owner_id: uuid.UUID) -> bool:
    scope = principal.scope_for("tender", action)
    return scope is not None and (scope == Scope.ALL or owner_id == principal.id)


def ensure(principal: Principal, action: str, tender: Tender) -> None:
    if not may(principal, action, tender.owner_id):
        if action == "view":
            raise NotFoundError("NOT_FOUND", "Tender tidak ditemukan atau Anda tidak berizin.")
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin mengubah tender ini.")


async def _tender_access(
    session: AsyncSession, principal: Principal, entity_id: str, mode: access.Mode
) -> bool:
    try:
        t = await session.get(Tender, uuid.UUID(entity_id))
    except ValueError:
        return False
    return t is not None and may(principal, "view" if mode == "read" else "edit", t.owner_id)


async def _document_access(
    session: AsyncSession, principal: Principal, entity_id: str, mode: access.Mode
) -> bool:
    try:
        d = await session.get(TenderDocument, uuid.UUID(entity_id))
    except ValueError:
        return False
    if d is None:
        return False
    return await _tender_access(session, principal, str(d.tender_id), mode)


access.register("tender", _tender_access)
access.register(service.DOC_ENTITY, _document_access)


async def _load(
    session: AsyncSession, principal: Principal, tid: uuid.UUID, lock: bool = False
) -> tuple[Tender, Opportunity]:
    t = await session.get(Tender, tid, with_for_update=lock)
    if t is None:
        raise NotFoundError("NOT_FOUND", "Tender tidak ditemukan.")
    ensure(principal, "view", t)
    opp = await session.get(Opportunity, t.opportunity_id, with_for_update=lock)
    assert opp is not None
    return t, opp


def _iso(v: Any) -> Any:
    return v.isoformat() if v is not None else None


def _money(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


def _summary(t: Tender, opp: Opportunity, owner: str | None) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "opportunity_id": str(opp.id),
        "opportunity_number": opp.number,
        "opportunity_title": opp.title,
        "opportunity_stage": opp.stage,
        "company_name": opp.company_name,
        "owner_name": owner,
        "tender_number": t.tender_number,
        "method": t.method,
        "closing_at": _iso(t.closing_at),
        "price": _money(t.price),
        "package_status": t.package_status,
        "submitted_at": _iso(t.submitted_at),
        "result": t.result,
    }


async def _names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return dict(rows.tuples().all())


def _query(principal: Principal, q: str | None, open_only: bool) -> Select[Any]:
    stmt = (
        select(Tender, Opportunity)
        .join(Opportunity, Opportunity.id == Tender.opportunity_id)
        .where(scope_filter(principal, "tender", "view", owner_col=Tender.owner_id))
    )
    if open_only:
        stmt = stmt.where(Tender.result.is_(None))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Tender.tender_number.ilike(like),
                Opportunity.number.ilike(like),
                Opportunity.title.ilike(like),
                Opportunity.company_name.ilike(like),
            )
        )
    return stmt


@router.get("")
async def list_tenders(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    q: str | None = None,
    open_only: bool = False,
    opportunity_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    stmt = _query(principal, q, open_only)
    if opportunity_id:
        stmt = stmt.where(Tender.opportunity_id == opportunity_id)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(Tender.closing_at.asc().nulls_last())
            .offset(paging.offset)
            .limit(paging.page_size)
        )
    ).all()
    names = await _names(session, {t.owner_id for t, _ in rows})
    return {
        "items": [_summary(t, o, names.get(t.owner_id)) for t, o in rows],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/closing-soon")
async def closing_soon(principal: Viewer, session: Session, days: int = 7) -> list[dict[str, Any]]:
    """Open tenders closing within `days` days (dashboard)."""
    now = datetime.now().astimezone()
    stmt = (
        _query(principal, None, True)
        .where(Tender.closing_at >= now, Tender.closing_at <= now + timedelta(days=days))
        .order_by(Tender.closing_at)
        .limit(50)
    )
    rows = (await session.execute(stmt)).all()
    names = await _names(session, {t.owner_id for t, _ in rows})
    out = []
    for t, o in rows:
        state = service.readiness(t, await service.documents(session, t))
        out.append({**_summary(t, o, names.get(t.owner_id)), "missing": len(state["missing"])})
    return out


async def _detail(
    session: AsyncSession, principal: Principal, t: Tender, opp: Opportunity
) -> dict[str, Any]:
    docs = await service.documents(session, t)
    state = service.readiness(t, docs)
    clar = (
        await session.execute(
            select(TenderClarification)
            .where(TenderClarification.tender_id == t.id)
            .order_by(TenderClarification.asked_at)
        )
    ).scalars()
    names = await _names(session, {t.owner_id})
    can_edit = may(principal, "edit", t.owner_id) and t.result is None
    return {
        **_summary(t, opp, names.get(t.owner_id)),
        "aanwijzing_at": _iso(t.aanwijzing_at),
        "clarification_deadline": _iso(t.clarification_deadline),
        "opening_at": _iso(t.opening_at),
        "bid_validity_until": _iso(t.bid_validity_until),
        "bid_bond_required": t.bid_bond_required,
        "bid_bond_amount": _money(t.bid_bond_amount),
        "bid_bond_number": t.bid_bond_number,
        "tkdn_required_pct": _money(t.tkdn_required_pct),
        "tkdn_offered_pct": _money(t.tkdn_offered_pct),
        "request_id": str(t.request_id) if t.request_id else None,
        "submission_channel": t.submission_channel,
        "receipt_number": t.receipt_number,
        "result_at": _iso(t.result_at),
        "rank": t.rank,
        "winner_name": t.winner_name,
        "winning_price": _money(t.winning_price),
        "lessons_learned": t.lessons_learned,
        "readiness": state,
        "can_edit": can_edit,
        "can_submit_package": may(principal, "submit", t.owner_id)
        and t.package_status in ("none", "rejected")
        and t.result is None,
        "documents": [
            {
                "id": str(d.doc.id),
                "section": d.doc.section,
                "name": d.doc.name,
                "mandatory": d.doc.mandatory,
                "not_applicable": d.doc.not_applicable,
                "expiry_date": _iso(d.doc.expiry_date),
                "note": d.doc.note,
                "files": d.files,
                "status": d.status,
                "expired": d.expired,
            }
            for d in docs
        ],
        "clarifications": [
            {
                "id": str(c.id),
                "question": c.question,
                "asked_at": c.asked_at.isoformat(),
                "reference": c.reference,
                "answer": c.answer,
                "answered_at": _iso(c.answered_at),
            }
            for c in clar
        ],
    }


@router.get("/{tid}")
async def get_tender(tid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    t, opp = await _load(session, principal, tid)
    return await _detail(session, principal, t, opp)


class CreateIn(BaseModel):
    opportunity_id: uuid.UUID


@router.post("", status_code=201)
async def create(body: CreateIn, actor: Creator, session: Session) -> dict[str, Any]:
    opp = await session.get(Opportunity, body.opportunity_id)
    if opp is None or not may(actor, "create", opp.owner_id):
        raise NotFoundError("NOT_FOUND", "Opportunity tidak ditemukan atau Anda tidak berizin.")
    t = await service.create(session, actor, opp)
    await session.commit()
    return await _detail(session, actor, t, opp)


class TenderIn(BaseModel):
    tender_number: str | None = Field(default=None, max_length=80)
    method: Method = "open"
    aanwijzing_at: datetime | None = None
    clarification_deadline: datetime | None = None
    closing_at: datetime | None = None
    opening_at: datetime | None = None
    bid_validity_until: date | None = None
    bid_bond_required: bool = False
    bid_bond_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    bid_bond_number: str | None = Field(default=None, max_length=80)
    tkdn_required_pct: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    tkdn_offered_pct: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)

    @field_validator("aanwijzing_at", "clarification_deadline", "closing_at", "opening_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("Waktu harus menyertakan zona waktu.")
        return v


FIELDS = tuple(TenderIn.model_fields)


@router.put("/{tid}")
async def update(tid: uuid.UUID, body: TenderIn, actor: Editor, session: Session) -> dict[str, Any]:
    t, opp = await _load(session, actor, tid, lock=True)
    ensure(actor, "edit", t)
    if t.result:
        raise ConflictError("TENDER_CLOSED", "Hasil tender sudah dicatat.")
    if t.package_status in ("pending", "approved") and body.price != t.price:
        raise ConflictError(
            "PACKAGE_LOCKED", "Harga terkunci selama paket menunggu/sudah disetujui."
        )
    if body.closing_at and body.opening_at and body.opening_at < body.closing_at:
        raise AppError(
            "DATES_INVALID", "Pembukaan penawaran tidak boleh sebelum penutupan.", status_code=422
        )
    if (
        body.clarification_deadline
        and body.closing_at
        and body.clarification_deadline > body.closing_at
    ):
        raise AppError(
            "DATES_INVALID", "Batas klarifikasi harus sebelum penutupan.", status_code=422
        )
    before = {k: getattr(t, k) for k in FIELDS}
    for k in FIELDS:
        setattr(t, k, getattr(body, k))
    t.tender_number = (body.tender_number or "").strip() or None
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="tender",
        entity_id=t.id,
        actor_id=actor.id,
        before=before,
        after={k: getattr(t, k) for k in FIELDS},
    )
    await session.commit()
    return await _detail(session, actor, t, opp)


class DocIn(BaseModel):
    section: Literal["admin", "technical", "commercial"]
    name: str = Field(min_length=2, max_length=200)
    mandatory: bool = True
    not_applicable: bool = False
    expiry_date: date | None = None
    note: str | None = Field(default=None, max_length=300)


def _editable(t: Tender) -> None:
    if t.result:
        raise ConflictError("TENDER_CLOSED", "Hasil tender sudah dicatat.")
    if t.package_status == "pending":
        raise ConflictError(
            "PACKAGE_PENDING", "Checklist terkunci selama paket menunggu persetujuan."
        )


@router.post("/{tid}/documents", status_code=201)
async def add_document(
    tid: uuid.UUID, body: DocIn, actor: Editor, session: Session
) -> dict[str, Any]:
    t, opp = await _load(session, actor, tid, lock=True)
    ensure(actor, "edit", t)
    _editable(t)
    seq = (
        await session.execute(
            select(func.coalesce(func.max(TenderDocument.seq), 0)).where(
                TenderDocument.tender_id == t.id
            )
        )
    ).scalar_one() + 1
    doc = TenderDocument(tender_id=t.id, seq=seq, **body.model_dump())
    session.add(doc)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="tender",
        entity_id=t.id,
        actor_id=actor.id,
        after={"document": doc.name, "section": doc.section, "mandatory": doc.mandatory},
    )
    await session.commit()
    return await _detail(session, actor, t, opp)


@router.put("/{tid}/documents/{doc_id}")
async def update_document(
    tid: uuid.UUID, doc_id: uuid.UUID, body: DocIn, actor: Editor, session: Session
) -> dict[str, Any]:
    t, opp = await _load(session, actor, tid, lock=True)
    ensure(actor, "edit", t)
    _editable(t)
    doc = await session.get(TenderDocument, doc_id)
    if doc is None or doc.tender_id != t.id:
        raise NotFoundError("NOT_FOUND", "Dokumen tidak ditemukan.")
    before = {
        "name": doc.name,
        "mandatory": doc.mandatory,
        "not_applicable": doc.not_applicable,
        "expiry_date": doc.expiry_date,
    }
    for k, v in body.model_dump().items():
        setattr(doc, k, v)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="tender",
        entity_id=t.id,
        actor_id=actor.id,
        before={"document": before},
        after={
            "document": {
                "name": doc.name,
                "mandatory": doc.mandatory,
                "not_applicable": doc.not_applicable,
                "expiry_date": doc.expiry_date,
            }
        },
    )
    await session.commit()
    return await _detail(session, actor, t, opp)


@router.delete("/{tid}/documents/{doc_id}")
async def delete_document(
    tid: uuid.UUID, doc_id: uuid.UUID, actor: Editor, session: Session
) -> dict[str, Any]:
    t, opp = await _load(session, actor, tid, lock=True)
    ensure(actor, "edit", t)
    _editable(t)
    doc = await session.get(TenderDocument, doc_id)
    if doc is None or doc.tender_id != t.id:
        raise NotFoundError("NOT_FOUND", "Dokumen tidak ditemukan.")
    states = {str(d.doc.id): d for d in await service.documents(session, t)}
    if states[str(doc.id)].files > 0:
        raise ConflictError(
            "DOCUMENT_HAS_FILES",
            "Dokumen sudah berisi file. Tandai N/A atau arsipkan file dahulu.",
        )
    await session.delete(doc)
    await audit.record(
        session,
        action=AuditAction.DELETE,
        entity_type="tender",
        entity_id=t.id,
        actor_id=actor.id,
        before={"document": doc.name, "section": doc.section},
    )
    await session.commit()
    return await _detail(session, actor, t, opp)


class ClarificationIn(BaseModel):
    question: str = Field(min_length=5, max_length=4000)
    asked_at: datetime
    reference: str | None = Field(default=None, max_length=120)
    answer: str | None = Field(default=None, max_length=4000)
    answered_at: datetime | None = None


@router.post("/{tid}/clarifications", status_code=201)
async def add_clarification(
    tid: uuid.UUID, body: ClarificationIn, actor: Editor, session: Session
) -> dict[str, Any]:
    t, opp = await _load(session, actor, tid, lock=True)
    ensure(actor, "edit", t)
    c = TenderClarification(tender_id=t.id, created_by=actor.id, **body.model_dump())
    session.add(c)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="tender",
        entity_id=t.id,
        actor_id=actor.id,
        after={"clarification": c.question[:200], "reference": c.reference},
    )
    await session.commit()
    return await _detail(session, actor, t, opp)


@router.put("/{tid}/clarifications/{cid}")
async def update_clarification(
    tid: uuid.UUID, cid: uuid.UUID, body: ClarificationIn, actor: Editor, session: Session
) -> dict[str, Any]:
    t, opp = await _load(session, actor, tid, lock=True)
    ensure(actor, "edit", t)
    c = await session.get(TenderClarification, cid)
    if c is None or c.tender_id != t.id:
        raise NotFoundError("NOT_FOUND", "Klarifikasi tidak ditemukan.")
    before = {"question": c.question, "answer": c.answer}
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    if c.answer and c.answered_at is None:
        c.answered_at = datetime.now().astimezone()
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="tender",
        entity_id=t.id,
        actor_id=actor.id,
        before={"clarification": before},
        after={"clarification": {"question": c.question, "answer": c.answer}},
    )
    await session.commit()
    return await _detail(session, actor, t, opp)


@router.post("/{tid}/submit-package")
async def submit_package(tid: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    t, opp = await _load(session, actor, tid, lock=True)
    ensure(actor, "submit", t)
    await service.submit_package(session, actor, t, opp)
    await session.commit()
    return await _detail(session, actor, t, opp)


class SubmissionIn(BaseModel):
    submitted_at: datetime
    channel: Channel
    receipt_number: str | None = Field(default=None, max_length=80)


@router.post("/{tid}/submission")
async def submission(
    tid: uuid.UUID, body: SubmissionIn, actor: Editor, session: Session
) -> dict[str, Any]:
    t, opp = await _load(session, actor, tid, lock=True)
    ensure(actor, "edit", t)
    await service.record_submission(
        session,
        actor,
        t,
        submitted_at=body.submitted_at,
        channel=body.channel,
        receipt_number=(body.receipt_number or "").strip() or None,
    )
    await session.commit()
    return await _detail(session, actor, t, opp)


class ResultIn(BaseModel):
    result: Result
    rank: int | None = Field(default=None, ge=1, le=100)
    winner_name: str | None = Field(default=None, max_length=200)
    winning_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    lessons_learned: str | None = Field(default=None, max_length=4000)


@router.post("/{tid}/result")
async def result(tid: uuid.UUID, body: ResultIn, actor: Editor, session: Session) -> dict[str, Any]:
    t, opp = await _load(session, actor, tid, lock=True)
    ensure(actor, "edit", t)
    await service.record_result(session, actor, t, opp, **body.model_dump())
    await session.commit()
    return await _detail(session, actor, t, opp)
