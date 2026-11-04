import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Scope
from app.auth.principal import Principal, require
from app.core import access
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.core.pagination import PageParams, page_params
from app.master.models import Vendor
from app.procurement import po_service, pr_service, rfq_service
from app.procurement.models import (
    PriceHistory,
    PurchaseOrder,
    PurchaseRequisition,
    Rfq,
    RfqQuote,
)
from app.project.models import Project, ProjectWbs
from app.services import budget_control as bc
from app.services.storage import Storage, get_storage

router = APIRouter(prefix="/procurement", tags=["procurement"])
Session = Annotated[AsyncSession, Depends(get_session)]
Store = Annotated[Storage, Depends(get_storage)]
Viewer = Annotated[Principal, Depends(require("procurement", "view"))]
Creator = Annotated[Principal, Depends(require("procurement", "create"))]
Editor = Annotated[Principal, Depends(require("procurement", "edit"))]
Submitter = Annotated[Principal, Depends(require("procurement", "submit"))]


def _may(principal: Principal, action: str, project_id: uuid.UUID, owner: uuid.UUID | None) -> bool:
    scope = principal.scope_for("procurement", action)
    if scope is None:
        return False
    if scope == Scope.ALL:
        return True
    if scope == Scope.PROJECT and project_id in principal.project_ids:
        return True
    return owner == principal.id


async def _rfq(
    session: AsyncSession,
    principal: Principal,
    rid: uuid.UUID,
    action: str = "view",
    lock: bool = False,
) -> tuple[Rfq, PurchaseRequisition]:
    rfq = await session.get(Rfq, rid, with_for_update=lock)
    pr = await session.get(PurchaseRequisition, rfq.pr_id) if rfq else None
    if rfq is None or pr is None or not _may(principal, action, pr.project_id, rfq.created_by):
        raise NotFoundError("NOT_FOUND", "RFQ tidak ditemukan atau Anda tidak berizin.")
    return rfq, pr


async def _po(
    session: AsyncSession,
    principal: Principal,
    pid: uuid.UUID,
    action: str = "view",
    lock: bool = False,
) -> PurchaseOrder:
    po = await session.get(PurchaseOrder, pid, with_for_update=lock)
    if po is None or not _may(principal, action, po.project_id, po.created_by):
        raise NotFoundError("NOT_FOUND", "PO tidak ditemukan atau Anda tidak berizin.")
    return po


async def _rfq_access(
    session: AsyncSession, principal: Principal, eid: str, mode: access.Mode
) -> bool:
    try:
        await _rfq(session, principal, uuid.UUID(eid), "view" if mode == "read" else "edit")
    except (ValueError, NotFoundError):
        return False
    return True


async def _quote_access(
    session: AsyncSession, principal: Principal, eid: str, mode: access.Mode
) -> bool:
    try:
        q = await session.get(RfqQuote, uuid.UUID(eid))
    except ValueError:
        return False
    return q is not None and await _rfq_access(session, principal, str(q.rfq_id), mode)


async def _po_access(
    session: AsyncSession, principal: Principal, eid: str, mode: access.Mode
) -> bool:
    try:
        await _po(session, principal, uuid.UUID(eid), "view" if mode == "read" else "edit")
    except (ValueError, NotFoundError):
        return False
    return True


access.register("rfq", _rfq_access)
access.register("rfq_quote", _quote_access)
access.register(po_service.DOC, _po_access)


def _m(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


# ---------------------------------------------------------------- vendors & price history


@router.get("/vendor-categories")
async def vendor_categories(_: Viewer, session: Session) -> list[str]:
    rows = await session.execute(select(Vendor.category).distinct().order_by(Vendor.category))
    return list(rows.scalars())


@router.get("/rfq-vendors")
async def rfq_vendors(_: Viewer, session: Session, category: str) -> list[dict[str, Any]]:
    """Vendors of a category; excluded ones carry the reason (not selectable)."""
    return [
        {
            "code": v.code,
            "name": v.name,
            "rating": _m(v.rating),
            "status": v.status,
            "excluded": reason,
        }
        for v, reason in await rfq_service.eligible_vendors(session, category)
    ]


@router.get("/price-history")
async def price_history(
    _: Viewer,
    session: Session,
    item_code: str | None = None,
    q: str | None = None,
    vendor_code: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(PriceHistory, Vendor.name).join(Vendor, Vendor.code == PriceHistory.vendor_code)
    if item_code:
        stmt = stmt.where(PriceHistory.item_code == item_code)
    if vendor_code:
        stmt = stmt.where(PriceHistory.vendor_code == vendor_code)
    if q and q.strip():
        stmt = stmt.where(PriceHistory.description.ilike(f"%{q.strip()}%"))
    rows = await session.execute(stmt.order_by(PriceHistory.at.desc()).limit(200))
    return [
        {
            "item_code": h.item_code,
            "description": h.description,
            "vendor_code": h.vendor_code,
            "vendor_name": name,
            "uom": h.uom,
            "unit_price": _m(h.unit_price),
            "source": h.source,
            "doc_number": h.doc_number,
            "at": h.at.isoformat(),
        }
        for h, name in rows.tuples()
    ]


# ---------------------------------------------------------------- RFQ


@router.get("/rfqs")
async def list_rfqs(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    status: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    stmt = select(Rfq, PurchaseRequisition).join(
        PurchaseRequisition, PurchaseRequisition.id == Rfq.pr_id
    )
    if principal.scope_for("procurement", "view") != Scope.ALL:
        stmt = stmt.where(
            or_(
                Rfq.created_by == principal.id,
                PurchaseRequisition.project_id.in_(principal.project_ids or {uuid.uuid4()}),
                PurchaseRequisition.requester_id == principal.id,
            )
        )
    if status:
        stmt = stmt.where(Rfq.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Rfq.number.ilike(like), PurchaseRequisition.number.ilike(like)))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(Rfq.created_at.desc()).offset(paging.offset).limit(paging.page_size)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(r.id),
                "number": r.number,
                "status": r.status,
                "category": r.category,
                "pr_id": str(pr.id),
                "pr_number": pr.number,
                "pr_total": _m(pr.total),
                "awarded_vendor_code": r.awarded_vendor_code,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "created_at": r.created_at.isoformat(),
            }
            for r, pr in rows
        ],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
    }


class RfqIn(BaseModel):
    pr_id: uuid.UUID
    category: str = Field(min_length=1, max_length=30)
    vendor_codes: list[str] = Field(min_length=1, max_length=20)
    due_date: date | None = None


@router.post("/rfqs", status_code=201)
async def create_rfq(body: RfqIn, actor: Creator, session: Session) -> dict[str, Any]:
    pr = await session.get(PurchaseRequisition, body.pr_id, with_for_update=True)
    if pr is None or not _may(actor, "create", pr.project_id, pr.requester_id):
        raise NotFoundError("NOT_FOUND", "PR tidak ditemukan atau Anda tidak berizin.")
    rfq = await rfq_service.create(
        session,
        actor,
        pr,
        category=body.category,
        vendor_codes=body.vendor_codes,
        due_date=body.due_date,
    )
    await session.commit()
    return await _rfq_detail(session, actor, rfq, pr)


async def _rfq_detail(
    session: AsyncSession, principal: Principal, rfq: Rfq, pr: PurchaseRequisition
) -> dict[str, Any]:
    quotes = await rfq_service.quotes_of(session, rfq.id)
    vendors = {
        v.code: v
        for v in (
            await session.execute(
                select(Vendor).where(Vendor.code.in_([q.vendor_code for q in quotes]))
            )
        ).scalars()
    }
    ranked = await rfq_service.scores(session, rfq)
    by_vendor = {s.vendor_code: s for s in ranked}
    po = (
        await session.execute(
            select(PurchaseOrder.id, PurchaseOrder.number).where(PurchaseOrder.rfq_id == rfq.id)
        )
    ).first()
    pr_lines = await pr_service.lines_of(session, pr.id)
    editable = _may(principal, "edit", pr.project_id, rfq.created_by)
    return {
        "id": str(rfq.id),
        "number": rfq.number,
        "status": rfq.status,
        "category": rfq.category,
        "due_date": rfq.due_date.isoformat() if rfq.due_date else None,
        "pr_id": str(pr.id),
        "pr_number": pr.number,
        "pr_total": _m(pr.total),
        "awarded_vendor_code": rfq.awarded_vendor_code,
        "award_reason": rfq.award_reason,
        "pending_vendor_code": rfq.pending_vendor_code,
        "request_id": str(rfq.request_id) if rfq.request_id else None,
        "best_vendor_code": ranked[0].vendor_code if ranked else None,
        "weights": {k: str(v) for k, v in (await rfq_service.weights(session)).items()},
        "po": {"id": str(po[0]), "number": po[1]} if po else None,
        "can_edit": editable and rfq.status == "open",
        "can_create_po": editable and rfq.status == "awarded" and po is None,
        "pr_lines": [
            {
                "seq": x.seq,
                "item_code": x.item_code,
                "description": x.description,
                "qty": format(x.qty.normalize(), "f"),
                "uom": x.uom,
                "est_price": _m(x.est_price),
            }
            for x in pr_lines
        ],
        "quotes": [
            {
                "id": str(q.id),
                "vendor_code": q.vendor_code,
                "vendor_name": vendors[q.vendor_code].name
                if q.vendor_code in vendors
                else q.vendor_code,
                "rating": _m(vendors[q.vendor_code].rating) if q.vendor_code in vendors else None,
                "status": q.status,
                "total": _m(q.total),
                "delivery_days": q.delivery_days,
                "payment_terms": q.payment_terms,
                "valid_until": q.valid_until.isoformat() if q.valid_until else None,
                "note": q.note,
                "lines": [
                    {"seq": ql.seq, "unit_price": _m(ql.unit_price), "amount": _m(ql.amount)}
                    for ql in await rfq_service.quote_lines(session, q.id)
                ],
                "score": rfq_service.score_dict(by_vendor[q.vendor_code])
                if q.vendor_code in by_vendor
                else None,
            }
            for q in quotes
        ],
    }


@router.get("/rfqs/{rid}")
async def get_rfq(rid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    rfq, pr = await _rfq(session, principal, rid)
    return await _rfq_detail(session, principal, rfq, pr)


class QuoteIn(BaseModel):
    unit_prices: dict[int, Decimal] = Field(default_factory=dict)
    delivery_days: int = Field(default=0, ge=0, le=3650)
    payment_terms: str | None = Field(default=None, max_length=200)
    valid_until: date | None = None
    note: str | None = Field(default=None, max_length=1000)
    declined: bool = False

    @field_validator("unit_prices")
    @classmethod
    def _whole(cls, v: dict[int, Decimal]) -> dict[int, Decimal]:
        for price in v.values():
            if price != price.to_integral_value():
                raise ValueError("Harga harus rupiah bulat.")
        return v


@router.put("/rfqs/{rid}/quotes/{qid}")
async def record_quote(
    rid: uuid.UUID, qid: uuid.UUID, body: QuoteIn, actor: Editor, session: Session
) -> dict[str, Any]:
    rfq, pr = await _rfq(session, actor, rid, "edit", lock=True)
    quote = await session.get(RfqQuote, qid)
    if quote is None or quote.rfq_id != rfq.id:
        raise NotFoundError("NOT_FOUND", "Penawaran vendor tidak ditemukan.")
    await rfq_service.record_quote(
        session,
        actor,
        rfq,
        quote,
        unit_prices=body.unit_prices,
        delivery_days=body.delivery_days,
        payment_terms=body.payment_terms,
        valid_until=body.valid_until,
        note=body.note,
        declined=body.declined,
    )
    await session.commit()
    return await _rfq_detail(session, actor, rfq, pr)


class AwardIn(BaseModel):
    vendor_code: str = Field(min_length=1, max_length=20)
    reason: str | None = Field(default=None, max_length=1000)


@router.post("/rfqs/{rid}/award")
async def award(
    rid: uuid.UUID, body: AwardIn, actor: Submitter, session: Session
) -> dict[str, Any]:
    rfq, pr = await _rfq(session, actor, rid, "submit", lock=True)
    request = await rfq_service.award(session, actor, rfq, body.vendor_code, body.reason)
    await session.commit()
    return {**(await _rfq_detail(session, actor, rfq, pr)), "approval_needed": request is not None}


@router.post("/rfqs/{rid}/po", status_code=201)
async def create_po(rid: uuid.UUID, actor: Creator, session: Session) -> dict[str, Any]:
    rfq, _ = await _rfq(session, actor, rid, "create", lock=True)
    po = await po_service.create_from_award(session, actor, rfq)
    await session.commit()
    return await _po_detail(session, actor, po)


# ---------------------------------------------------------------- PO


async def _po_detail(
    session: AsyncSession, principal: Principal, po: PurchaseOrder
) -> dict[str, Any]:
    vendor = (
        await session.execute(select(Vendor).where(Vendor.code == po.vendor_code))
    ).scalar_one()
    project = await session.get(Project, po.project_id)
    wbs = await session.get(ProjectWbs, po.wbs_id)
    pr = await session.get(PurchaseRequisition, po.pr_id)
    rfq = await session.get(Rfq, po.rfq_id) if po.rfq_id else None
    assert project is not None and wbs is not None and pr is not None
    bal = await bc.available(session, po_service.line_of(po))
    held = await bc.held(session, po_service.line_of(po), po_service.DOC, str(po.id))
    editable = _may(principal, "edit", po.project_id, po.created_by)
    return {
        "id": str(po.id),
        "number": po.number,
        "revision": po.revision,
        "status": po.status,
        "vendor_code": po.vendor_code,
        "vendor_name": vendor.name,
        "project_id": str(project.id),
        "project_number": project.number,
        "wbs_code": wbs.code,
        "cost_element_code": po.cost_element_code,
        "pr_id": str(pr.id),
        "pr_number": pr.number,
        "rfq_id": str(rfq.id) if rfq else None,
        "rfq_number": rfq.number if rfq else None,
        "subtotal": _m(po.subtotal),
        "ppn_pct": str(po.ppn_pct),
        "ppn_amount": _m(po.ppn_amount),
        "total": _m(po.total),
        "delivery_date": po.delivery_date.isoformat() if po.delivery_date else None,
        "delivery_location": po.delivery_location,
        "payment_terms": po.payment_terms,
        "terms": po.terms,
        "issued_at": po.issued_at.isoformat() if po.issued_at else None,
        "revision_reason": po.revision_reason,
        "pending_revision": po.pending_revision,
        "request_id": str(po.request_id) if po.request_id else None,
        "budget": {
            "available": _m(bal.available),
            "commit_by_po": _m(held["commit"]),
            "budget": _m(bal.budget),
            "used_pct": str(bal.used_pct),
        },
        "can_edit": editable and po.status == "draft",
        "can_issue": editable and po.status == "draft",
        "can_revise": editable and po.status == "issued",
        "lines": [
            {
                "seq": x.seq,
                "item_code": x.item_code,
                "description": x.description,
                "qty": format(x.qty.normalize(), "f"),
                "uom": x.uom,
                "unit_price": _m(x.unit_price),
                "amount": _m(x.amount),
            }
            for x in await po_service.lines_of(session, po.id)
        ],
    }


@router.get("/pos")
async def list_pos(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    status: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    stmt = select(PurchaseOrder, Vendor.name).join(Vendor, Vendor.code == PurchaseOrder.vendor_code)
    if principal.scope_for("procurement", "view") != Scope.ALL:
        stmt = stmt.where(
            or_(
                PurchaseOrder.created_by == principal.id,
                PurchaseOrder.project_id.in_(principal.project_ids or {uuid.uuid4()}),
            )
        )
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(PurchaseOrder.number.ilike(like), Vendor.name.ilike(like)))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(PurchaseOrder.created_at.desc())
            .offset(paging.offset)
            .limit(paging.page_size)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(po.id),
                "number": po.number,
                "revision": po.revision,
                "status": po.status,
                "vendor_name": name,
                "subtotal": _m(po.subtotal),
                "total": _m(po.total),
                "delivery_date": po.delivery_date.isoformat() if po.delivery_date else None,
                "issued_at": po.issued_at.isoformat() if po.issued_at else None,
            }
            for po, name in rows
        ],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/pos/{pid}")
async def get_po(pid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _po_detail(session, principal, await _po(session, principal, pid))


class PoLineIn(BaseModel):
    seq: int = Field(ge=1)
    item_code: str | None = Field(default=None, max_length=30)
    description: str = Field(min_length=2, max_length=300)
    qty: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    uom: str = Field(min_length=1, max_length=10)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=0)


class PoIn(BaseModel):
    lines: list[PoLineIn] = Field(min_length=1, max_length=200)
    delivery_date: date | None = None
    delivery_location: str = Field(min_length=2, max_length=200)
    payment_terms: str | None = Field(default=None, max_length=200)
    terms: str | None = Field(default=None, max_length=4000)


def _lines(rows: list[PoLineIn]) -> list[po_service.LineIn]:
    return [
        po_service.LineIn(
            x.seq, x.item_code, x.description.strip(), x.qty, x.uom.strip(), x.unit_price
        )
        for x in rows
    ]


@router.put("/pos/{pid}")
async def update_po(pid: uuid.UUID, body: PoIn, actor: Editor, session: Session) -> dict[str, Any]:
    po = await _po(session, actor, pid, "edit", lock=True)
    await po_service.update_draft(
        session,
        actor,
        po,
        lines=_lines(body.lines),
        delivery_date=body.delivery_date,
        delivery_location=body.delivery_location.strip(),
        payment_terms=body.payment_terms,
        terms=body.terms,
    )
    await session.commit()
    return await _po_detail(session, actor, po)


@router.post("/pos/{pid}/issue")
async def issue_po(
    pid: uuid.UUID, actor: Submitter, session: Session, storage: Store
) -> dict[str, Any]:
    po = await _po(session, actor, pid, "submit", lock=True)
    await po_service.issue(session, storage, actor, po)
    await session.commit()
    return await _po_detail(session, actor, po)


class ReviseIn(BaseModel):
    lines: list[PoLineIn] = Field(min_length=1, max_length=200)
    reason: str = Field(max_length=500)


@router.post("/pos/{pid}/revise")
async def revise_po(
    pid: uuid.UUID, body: ReviseIn, actor: Submitter, session: Session, storage: Store
) -> dict[str, Any]:
    po = await _po(session, actor, pid, "submit", lock=True)
    request = await po_service.revise(session, storage, actor, po, _lines(body.lines), body.reason)
    await session.commit()
    return {**(await _po_detail(session, actor, po)), "approval_needed": request is not None}


@router.post("/pos/{pid}/cancel")
async def cancel_po(pid: uuid.UUID, actor: Editor, session: Session) -> dict[str, Any]:
    po = await _po(session, actor, pid, "edit", lock=True)
    await po_service.cancel_draft(session, actor, po)
    await session.commit()
    return await _po_detail(session, actor, po)
