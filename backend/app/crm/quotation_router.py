import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import Principal, require, scope_filter
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.core.types import IDR
from app.crm import quotation_pdf as pdf
from app.crm import quotation_service as svc
from app.crm.models import Opportunity, Quotation
from app.dms import service as dms
from app.dms.models import Attachment
from app.letters import service as letters
from app.letters.models import OutgoingLetter
from app.master.models import CostElement, PriceItem
from app.services import email, email_log
from app.services import email_templates as templates
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta
from app.services.storage import Storage, get_storage
from app.setup import service as settings_store

router = APIRouter(prefix="/quotations", tags=["quotation"])
Session = Annotated[AsyncSession, Depends(get_session)]
Store = Annotated[Storage, Depends(get_storage)]
Viewer = Annotated[Principal, Depends(require("quotation", "view"))]
Creator = Annotated[Principal, Depends(require("quotation", "create"))]
Editor = Annotated[Principal, Depends(require("quotation", "edit"))]
Submitter = Annotated[Principal, Depends(require("quotation", "submit"))]
Exporter = Annotated[Principal, Depends(require("quotation", "export"))]


def may(principal: Principal, action: str, owner_id: uuid.UUID) -> bool:
    scope = principal.scope_for(svc.MODULE, action)
    return scope is not None and (scope == Scope.ALL or owner_id == principal.id)


def ensure(principal: Principal, action: str, owner_id: uuid.UUID) -> None:
    if not may(principal, action, owner_id):
        if action == "view":
            raise NotFoundError("NOT_FOUND", "Penawaran tidak ditemukan atau Anda tidak berizin.")
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin mengubah penawaran ini.")


async def _check(
    session: AsyncSession, principal: Principal, entity_id: str, mode: access.Mode
) -> bool:
    try:
        q = await session.get(Quotation, uuid.UUID(entity_id))
    except ValueError:
        return False
    return q is not None and may(principal, "view" if mode == "read" else "edit", q.owner_id)


access.register("quotation", _check)


async def _load(
    session: AsyncSession, principal: Principal, qid: uuid.UUID, lock: bool = False
) -> tuple[Quotation, Opportunity]:
    q = await session.get(Quotation, qid, with_for_update=lock)
    if q is None:
        raise NotFoundError("NOT_FOUND", "Penawaran tidak ditemukan.")
    ensure(principal, "view", q.owner_id)
    opp = await session.get(Opportunity, q.opportunity_id, with_for_update=lock)
    assert opp is not None
    return q, opp


# ---------------------------------------------------------------- schemas


class QuotationRow(BaseModel):
    id: uuid.UUID
    number: str
    revision: int
    label: str
    status: str
    opportunity_id: uuid.UUID
    opportunity_number: str
    opportunity_title: str
    company_name: str
    owner_name: str | None
    total_price: IDR
    margin_pct: Decimal
    margin_warning: bool
    valid_until: date | None
    submitted_at: datetime | None
    sent_at: datetime | None
    created_at: datetime


async def _rows(session: AsyncSession, items: list[Quotation]) -> list[QuotationRow]:
    if not items:
        return []
    warn = await svc.margin_warning_pct(session)
    opps = {
        o.id: o
        for o in (
            await session.execute(
                select(Opportunity).where(Opportunity.id.in_({q.opportunity_id for q in items}))
            )
        ).scalars()
    }
    names = dict(
        (
            await session.execute(
                select(User.id, User.full_name).where(User.id.in_({q.owner_id for q in items}))
            )
        )
        .tuples()
        .all()
    )
    return [
        QuotationRow(
            id=q.id,
            number=q.number,
            revision=q.revision,
            label=svc.label(q),
            status=q.status,
            opportunity_id=q.opportunity_id,
            opportunity_number=opps[q.opportunity_id].number,
            opportunity_title=opps[q.opportunity_id].title,
            company_name=opps[q.opportunity_id].company_name,
            owner_name=names.get(q.owner_id),
            total_price=q.total_price,
            margin_pct=q.margin_pct,
            margin_warning=q.margin_pct < warn and q.total_price > 0,
            valid_until=q.valid_until,
            submitted_at=q.submitted_at,
            sent_at=q.sent_at,
            created_at=q.created_at,
        )
        for q in items
    ]


# ---------------------------------------------------------------- reference


@router.get("/price-items")
async def price_items(_: Viewer, session: Session) -> list[dict[str, Any]]:
    """The price database (active items) with cost and price for quotation lines."""
    rows = await session.execute(
        select(PriceItem).where(PriceItem.is_active.is_(True)).order_by(PriceItem.code)
    )
    return [
        {
            "code": p.code,
            "name": p.name,
            "unit": p.unit,
            "cost_element_code": p.cost_element_code,
            "unit_cost": format(p.unit_cost, "f"),
            "unit_price": format(p.unit_price, "f"),
        }
        for p in rows.scalars()
    ]


@router.get("/config")
async def config(_: Viewer, session: Session) -> dict[str, Any]:
    elements = await session.execute(
        select(CostElement.code, CostElement.name)
        .where(CostElement.code != "CONTINGENCY")
        .order_by(CostElement.code)
    )
    return {
        "margin_warning_pct": str(await svc.margin_warning_pct(session)),
        "email_configured": email.provider() is not None,
        "cost_elements": [{"code": c, "name": n} for c, n in elements.tuples()],
        "default_cost_element": svc.DEFAULT_COST_ELEMENT,
    }


# ---------------------------------------------------------------- list / export


def _query(
    principal: Principal,
    action: str,
    status: str | None,
    q: str | None,
    opportunity_id: uuid.UUID | None,
    all_revisions: bool,
) -> Select[tuple[Quotation]]:
    stmt = (
        select(Quotation)
        .join(Opportunity, Opportunity.id == Quotation.opportunity_id)
        .where(scope_filter(principal, "quotation", action, owner_col=Quotation.owner_id))
    )
    if not all_revisions:  # the list shows the latest revision of each quotation
        inner = (
            select(Quotation.number, func.max(Quotation.revision).label("rev"))
            .group_by(Quotation.number)
            .subquery()
        )
        stmt = stmt.join(
            inner, (inner.c.number == Quotation.number) & (inner.c.rev == Quotation.revision)
        )
    if status:
        stmt = stmt.where(Quotation.status == status)
    if opportunity_id:
        stmt = stmt.where(Quotation.opportunity_id == opportunity_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Quotation.number.ilike(like),
                Opportunity.number.ilike(like),
                Opportunity.title.ilike(like),
                Opportunity.company_name.ilike(like),
            )
        )
    return stmt


@router.get("")
async def list_quotations(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    status: str | None = None,
    q: str | None = None,
    opportunity_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    base = _query(principal, "view", None, q, opportunity_id, False).subquery()
    counts = {s: 0 for s in svc.STATUSES}
    counts.update(
        dict(
            (await session.execute(select(base.c.status, func.count()).group_by(base.c.status)))
            .tuples()
            .all()
        )
    )
    stmt = _query(principal, "view", status, q, opportunity_id, False)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    items = (
        await session.execute(
            stmt.order_by(Quotation.created_at.desc()).offset(paging.offset).limit(paging.page_size)
        )
    ).scalars()
    return {
        "items": await _rows(session, list(items)),
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
        "counts": counts,
    }


@router.get("/export")
async def export(
    principal: Exporter, session: Session, status: str | None = None, q: str | None = None
) -> StreamingResponse:
    stmt = _query(principal, "export", status, q, None, True).order_by(
        Quotation.number, Quotation.revision
    )
    rows = await _rows(session, list((await session.execute(stmt)).scalars()))
    columns = [
        Column("Nomor", "label", width=18),
        Column("Opportunity", "opportunity_number", width=14),
        Column("Judul", "opportunity_title", width=36),
        Column("Klien", "company_name", width=30),
        Column("Status", "status_label", width=20),
        Column("Total", "total_price", "idr"),
        Column("Margin (%)", "margin_pct", "number", width=10),
        Column("Berlaku s.d.", "valid_until", "date"),
        Column("Dikirim", "sent_at", "datetime"),
        Column("Pemilik", "owner_name", width=22),
    ]
    return xlsx_response(
        f"penawaran-{today_jakarta():%Y%m%d}.xlsx",
        "Penawaran",
        columns,
        ({**r.model_dump(), "status_label": svc.STATUS_LABELS[r.status]} for r in rows),
    )


# ---------------------------------------------------------------- detail


async def _detail(session: AsyncSession, principal: Principal, q: Quotation) -> dict[str, Any]:
    opp = await session.get(Opportunity, q.opportunity_id)
    assert opp is not None
    row = (await _rows(session, [q]))[0]
    lines = await svc.lines_of(session, q.id)
    history = await svc.revisions(session, q.number)
    latest = history[0].revision
    letter = await session.get(OutgoingLetter, q.letter_id) if q.letter_id else None
    contact, contact_email = await svc.client_contact(session, opp)
    can_edit = may(principal, "edit", q.owner_id)
    can_submit = may(principal, "submit", q.owner_id)
    return {
        **row.model_dump(mode="json"),
        "subtotal": format(q.subtotal, "f"),
        "discount_pct": format(q.discount_pct, "f"),
        "discount_amount": format(q.discount_amount, "f"),
        "total_cost": format(q.total_cost, "f"),
        "margin": format(q.margin, "f"),
        "notes": q.notes,
        "terms": q.terms,
        "revision_reason": q.revision_reason,
        "request_id": str(q.request_id) if q.request_id else None,
        "decision_comment": q.decision_comment,
        "opportunity_stage": opp.stage,
        "contact_name": contact,
        "contact_email": contact_email,
        "sent_to_email": q.sent_to_email,
        "letter": {
            "number": letter.number,
            "date": letter.letter_date.isoformat(),
            "file_id": str(letter.file_id) if letter.file_id else None,
        }
        if letter
        else None,
        "is_latest": q.revision == latest,
        "can_edit": can_edit and q.status == "draft",
        "can_submit": can_submit and q.status == "draft",
        "can_revise": can_edit and q.revision == latest and q.status in svc.REVISABLE,
        "can_send": can_submit and q.revision == latest and q.status == "approved",
        "lines": [
            {
                "id": str(x.id),
                "seq": x.seq,
                "price_item_code": x.price_item_code,
                "cost_element_code": x.cost_element_code,
                "description": x.description,
                "unit": x.unit,
                "qty": format(x.qty.normalize(), "f"),
                "unit_cost": format(x.unit_cost, "f"),
                "unit_price": format(x.unit_price, "f"),
                "line_cost": format(x.line_cost, "f"),
                "line_price": format(x.line_price, "f"),
            }
            for x in lines
        ],
        "revisions": [
            {
                "id": str(r.id),
                "revision": r.revision,
                "status": r.status,
                "total_price": format(r.total_price, "f"),
                "margin_pct": format(r.margin_pct, "f"),
                "reason": r.revision_reason,
                "created_at": r.created_at.isoformat(),
            }
            for r in history
        ],
    }


@router.get("/{qid}")
async def get_quotation(qid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    q, _ = await _load(session, principal, qid)
    return await _detail(session, principal, q)


class CreateIn(BaseModel):
    opportunity_id: uuid.UUID


@router.post("", status_code=201)
async def create(body: CreateIn, actor: Creator, session: Session) -> dict[str, Any]:
    opp = await session.get(Opportunity, body.opportunity_id, with_for_update=True)
    if opp is None or not may(actor, "create", opp.owner_id):
        raise NotFoundError("NOT_FOUND", "Opportunity tidak ditemukan atau Anda tidak berizin.")
    q = await svc.create(session, actor, opp)
    await session.commit()
    return await _detail(session, actor, q)


class LineBody(BaseModel):
    price_item_code: str | None = Field(default=None, max_length=30)
    cost_element_code: str | None = Field(default=None, max_length=20)
    description: str = Field(min_length=2, max_length=300)
    unit: str = Field(min_length=1, max_length=20)
    qty: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    unit_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=0)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=0)

    @field_validator("price_item_code", "cost_element_code", mode="before")
    @classmethod
    def _blank(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


class DraftIn(BaseModel):
    discount_pct: Decimal = Field(default=Decimal(0), ge=0, le=100, decimal_places=2)
    valid_until: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    terms: str | None = Field(default=None, max_length=4000)
    lines: list[LineBody] = Field(default_factory=list, max_length=200)


@router.put("/{qid}")
async def save(qid: uuid.UUID, body: DraftIn, actor: Editor, session: Session) -> dict[str, Any]:
    q, _ = await _load(session, actor, qid, lock=True)
    ensure(actor, "edit", q.owner_id)
    await svc.save_draft(
        session,
        actor,
        q,
        lines=[
            svc.LineIn(
                price_item_code=x.price_item_code,
                cost_element_code=x.cost_element_code,
                description=x.description.strip(),
                unit=x.unit.strip(),
                qty=x.qty,
                unit_cost=x.unit_cost,
                unit_price=x.unit_price,
            )
            for x in body.lines
        ],
        discount_pct=body.discount_pct,
        valid_until=body.valid_until,
        notes=(body.notes or "").strip() or None,
        terms=(body.terms or "").strip() or None,
    )
    await session.commit()
    return await _detail(session, actor, q)


@router.post("/{qid}/submit")
async def submit(qid: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    q, opp = await _load(session, actor, qid, lock=True)
    ensure(actor, "submit", q.owner_id)
    request = await svc.submit(session, actor, q, opp)
    await session.commit()
    return {
        **(await _detail(session, actor, q)),
        "approver": request.steps[0].approver_role if request.steps else None,
    }


class ReviseIn(BaseModel):
    reason: str = Field(max_length=500)


@router.post("/{qid}/revise", status_code=201)
async def revise(qid: uuid.UUID, body: ReviseIn, actor: Editor, session: Session) -> dict[str, Any]:
    q, opp = await _load(session, actor, qid, lock=True)
    ensure(actor, "edit", q.owner_id)
    new = await svc.revise(session, actor, q, opp, body.reason)
    await session.commit()
    return await _detail(session, actor, new)


# ---------------------------------------------------------------- PDF / send


async def _letterhead(session: AsyncSession, storage: Storage) -> pdf.Letterhead:
    company = {
        **settings_store.DEFAULT_COMPANY,
        **(await settings_store.get(session, settings_store.COMPANY, {}) or {}),
    }
    logo = None
    logo_id = company.get("logo_attachment_id")
    if logo_id:
        att = await session.get(Attachment, uuid.UUID(str(logo_id)))
        if att is not None and att.content_type in ("image/png", "image/jpeg"):
            try:
                logo = (await storage.get(att.storage_key)).data
            except NotFoundError:
                logo = None
    return pdf.Letterhead(company=company, logo=logo)


async def _render(
    session: AsyncSession,
    storage: Storage,
    q: Quotation,
    opp: Opportunity,
    *,
    letter_number: str | None,
    letter_date: date,
    signer: str,
) -> bytes:
    contact, _ = await svc.client_contact(session, opp)
    return pdf.render(
        await _letterhead(session, storage),
        q,
        await svc.lines_of(session, q.id),
        opp,
        pdf.Recipient(company=opp.company_name, contact=contact),
        letter_number=letter_number,
        letter_date=letter_date,
        signer=signer,
    )


def _filename(q: Quotation) -> str:
    return f"Penawaran-{q.number}-Rev{q.revision}.pdf"


@router.get("/{qid}/pdf")
async def preview_pdf(
    qid: uuid.UUID, principal: Viewer, session: Session, storage: Store
) -> Response:
    """The sent letter if there is one; otherwise a draft preview (no letter number)."""
    q, opp = await _load(session, principal, qid)
    letter = await session.get(OutgoingLetter, q.letter_id) if q.letter_id else None
    if letter and letter.file_id:
        att = await session.get(Attachment, letter.file_id)
        assert att is not None
        data = (await storage.get(att.storage_key)).data
    else:
        data = await _render(
            session,
            storage,
            q,
            opp,
            letter_number=None,
            letter_date=today_jakarta(),
            signer=principal.user.full_name,
        )
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{_filename(q)}"'},
    )


class SendIn(BaseModel):
    send_email: bool = False
    to_email: EmailStr | None = None
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("to_email", mode="before")
    @classmethod
    def _blank(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


@router.post("/{qid}/send")
async def send(
    qid: uuid.UUID,
    body: SendIn,
    actor: Submitter,
    session: Session,
    storage: Store,
    background: BackgroundTasks,
) -> dict[str, Any]:
    """'Kirim ke klien': numbered letter + PDF in the DMS + optional email; stage -> Submitted."""
    q, opp = await _load(session, actor, qid, lock=True)
    ensure(actor, "submit", q.owner_id)
    svc.ensure_sendable(q, opp, await svc.latest_revision(session, q.number))
    contact, contact_email = await svc.client_contact(session, opp)
    to_email = str(body.to_email) if body.to_email else contact_email
    if body.send_email and not to_email:
        raise AppError(
            "EMAIL_REQUIRED", "Isi email kontak klien untuk mengirim lewat email.", status_code=422
        )
    subject = f"Penawaran Harga - {opp.title}"
    letter = await letters.reserve(
        session,
        actor,
        department=svc.LETTER_DEPT,
        to=f"{opp.company_name}" + (f" (Up. {contact})" if contact else ""),
        subject=subject,
        entity_type="quotation",
        entity_id=str(q.id),
        is_demo=q.is_demo,
    )
    signer = actor.user.full_name
    data = await _render(
        session,
        storage,
        q,
        opp,
        letter_number=letter.number,
        letter_date=letter.letter_date,
        signer=signer,
    )
    att = await dms.upload(
        session,
        storage,
        actor,
        entity_type="quotation",
        entity_id=str(q.id),
        filename=_filename(q),
        data=data,
        note=f"Surat {letter.number}",
    )
    letter.file_id = att.id
    await svc.mark_sent(
        session,
        actor,
        q,
        opp,
        letter_id=letter.id,
        email_to=to_email if body.send_email else None,
    )
    await session.commit()

    email_status = "skipped"
    if body.send_email and to_email:
        company = (await _letterhead(session, storage)).company
        message = templates.quotation_to_client(
            contact=contact,
            company=opp.company_name,
            sender_company=str(company.get("legal_name", "")),
            subject=f"{subject} ({letter.number})",
            letter=letter.number,
            message=body.message,
            signer=signer,
        )
        attachment = email.Attachment(_filename(q), data, "application/pdf")
        background.add_task(email_log.deliver, "quotation", to_email, message, None, (attachment,))
        email_status = "queued" if email.provider() else "not_configured"
    return {
        **(await _detail(session, actor, q)),
        "letter_number": letter.number,
        "file_id": str(att.id),
        "email_status": email_status,
    }
