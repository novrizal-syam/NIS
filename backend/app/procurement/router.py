import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import Principal, require, scope_filter
from app.core import access
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.master.models import CostElement
from app.procurement import pr_service as svc
from app.procurement.models import PR_STATUSES, PurchaseRequisition
from app.project.models import BudgetChangeRequest, Project, ProjectWbs
from app.services import budget_control as bc
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta
from app.workflow.models import ApprovalRequest, ApprovalStep

router = APIRouter(prefix="/procurement", tags=["procurement"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("procurement", "view"))]
Creator = Annotated[Principal, Depends(require("procurement", "create"))]
Submitter = Annotated[Principal, Depends(require("procurement", "submit"))]
Exporter = Annotated[Principal, Depends(require("procurement", "export"))]


def may(principal: Principal, action: str, pr: PurchaseRequisition) -> bool:
    scope = principal.scope_for("procurement", action)
    if scope is None:
        return False
    if scope == Scope.ALL:
        return True
    if scope == Scope.PROJECT and pr.project_id in principal.project_ids:
        return True
    return pr.requester_id == principal.id


async def _check(
    session: AsyncSession, principal: Principal, entity_id: str, mode: access.Mode
) -> bool:
    try:
        pr = await session.get(PurchaseRequisition, uuid.UUID(entity_id))
    except ValueError:
        return False
    if pr is None:
        return False
    if mode == "read":
        return may(principal, "view", pr)
    return pr.requester_id == principal.id and pr.status in svc.EDITABLE


access.register(svc.DOC, _check)


async def _load(
    session: AsyncSession, principal: Principal, pid: uuid.UUID, lock: bool = False
) -> PurchaseRequisition:
    pr = await session.get(PurchaseRequisition, pid, with_for_update=lock)
    if pr is None or not may(principal, "view", pr):
        raise NotFoundError("NOT_FOUND", "PR tidak ditemukan atau Anda tidak berizin.")
    return pr


def _money(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


async def _rows(session: AsyncSession, items: list[PurchaseRequisition]) -> list[dict[str, Any]]:
    if not items:
        return []
    projects = {
        p.id: p
        for p in (
            await session.execute(
                select(Project).where(Project.id.in_({x.project_id for x in items}))
            )
        ).scalars()
    }
    wbs = dict(
        (
            await session.execute(
                select(ProjectWbs.id, ProjectWbs.code).where(
                    ProjectWbs.id.in_({x.wbs_id for x in items})
                )
            )
        )
        .tuples()
        .all()
    )
    names = dict(
        (
            await session.execute(
                select(User.id, User.full_name).where(User.id.in_({x.requester_id for x in items}))
            )
        )
        .tuples()
        .all()
    )
    return [
        {
            "id": str(x.id),
            "number": x.number,
            "status": x.status,
            "status_label": svc.STATUS_LABELS[x.status],
            "project_id": str(x.project_id),
            "project_number": projects[x.project_id].number,
            "project_name": projects[x.project_id].name,
            "wbs_code": wbs[x.wbs_id],
            "cost_element_code": x.cost_element_code,
            "total": _money(x.total),
            "shortfall": _money(x.shortfall),
            "need_date": x.need_date.isoformat(),
            "requester_id": str(x.requester_id),
            "requester_name": names.get(x.requester_id),
            "submitted_at": x.submitted_at.isoformat() if x.submitted_at else None,
            "created_at": x.created_at.isoformat(),
        }
        for x in items
    ]


def _query(
    principal: Principal,
    action: str,
    status: str | None,
    q: str | None,
    project_id: uuid.UUID | None,
    mine: bool,
) -> Select[Any]:
    stmt = select(PurchaseRequisition).where(
        scope_filter(
            principal,
            "procurement",
            action,
            owner_col=PurchaseRequisition.requester_id,
            project_col=PurchaseRequisition.project_id,
        )
    )
    if status:
        stmt = stmt.where(PurchaseRequisition.status == status)
    if project_id:
        stmt = stmt.where(PurchaseRequisition.project_id == project_id)
    if mine:
        stmt = stmt.where(PurchaseRequisition.requester_id == principal.id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                PurchaseRequisition.number.ilike(like),
                PurchaseRequisition.purpose.ilike(like),
                PurchaseRequisition.delivery_location.ilike(like),
            )
        )
    return stmt


@router.get("/prs")
async def list_prs(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    status: str | None = None,
    q: str | None = None,
    project_id: uuid.UUID | None = None,
    mine: bool = False,
) -> dict[str, Any]:
    base = _query(principal, "view", None, q, project_id, mine).subquery()
    counts = dict.fromkeys(PR_STATUSES, 0)
    counts.update(
        dict(
            (await session.execute(select(base.c.status, func.count()).group_by(base.c.status)))
            .tuples()
            .all()
        )
    )
    stmt = _query(principal, "view", status, q, project_id, mine)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    items = (
        await session.execute(
            stmt.order_by(PurchaseRequisition.created_at.desc())
            .offset(paging.offset)
            .limit(paging.page_size)
        )
    ).scalars()
    return {
        "items": await _rows(session, list(items)),
        "total": total,
        "counts": counts,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/prs/export")
async def export_prs(
    principal: Exporter, session: Session, status: str | None = None, q: str | None = None
) -> StreamingResponse:
    stmt = _query(principal, "export", status, q, None, False).order_by(PurchaseRequisition.number)
    rows = await _rows(session, list((await session.execute(stmt)).scalars()))
    columns = [
        Column("Nomor", "number", width=14),
        Column("Status", "status_label", width=22),
        Column("Proyek", "project_number", width=14),
        Column("WBS", "wbs_code", width=10),
        Column("Elemen biaya", "cost_element_code", width=14),
        Column("Total", "total", "idr"),
        Column("Kekurangan anggaran", "shortfall", "idr"),
        Column("Dibutuhkan", "need", "date"),
        Column("Pemohon", "requester_name", width=22),
    ]
    return xlsx_response(
        f"pr-{today_jakarta():%Y%m%d}.xlsx",
        "PR",
        columns,
        ({**r, "need": date.fromisoformat(r["need_date"])} for r in rows),
    )


@router.get("/prs/form-options")
async def form_options(principal: Creator, session: Session) -> dict[str, Any]:
    """Locked projects the user may raise PRs on, with WBS and cost elements."""
    stmt = select(Project).where(Project.status == "locked").order_by(Project.number)
    if principal.scope_for("procurement", "create") == Scope.PROJECT:
        stmt = stmt.where(Project.id.in_(principal.project_ids or {uuid.uuid4()}))
    projects = list((await session.execute(stmt)).scalars())
    wbs: dict[uuid.UUID, list[dict[str, str]]] = {}
    if projects:
        for w in (
            await session.execute(
                select(ProjectWbs)
                .where(ProjectWbs.project_id.in_([p.id for p in projects]))
                .order_by(ProjectWbs.seq)
            )
        ).scalars():
            wbs.setdefault(w.project_id, []).append({"code": w.code, "name": w.name})
    elements = await session.execute(
        select(CostElement.code, CostElement.name)
        .where(CostElement.code != bc.CONTINGENCY)
        .order_by(CostElement.code)
    )
    return {
        "projects": [
            {"id": str(p.id), "number": p.number, "name": p.name, "wbs": wbs.get(p.id, [])}
            for p in projects
        ],
        "cost_elements": [{"code": c, "name": n} for c, n in elements.tuples()],
    }


async def _detail(
    session: AsyncSession, principal: Principal, pr: PurchaseRequisition
) -> dict[str, Any]:
    row = (await _rows(session, [pr]))[0]
    bal = await bc.available(session, svc.line_of(pr))
    held = await bc.held(session, svc.line_of(pr), svc.DOC, str(pr.id))
    history: list[dict[str, Any]] = []
    if pr.request_id:
        req = await session.get(ApprovalRequest, pr.request_id)
        steps = (
            await session.execute(
                select(ApprovalStep, User.full_name)
                .outerjoin(User, User.id == ApprovalStep.acted_by)
                .where(ApprovalStep.request_id == pr.request_id)
                .order_by(ApprovalStep.seq)
            )
        ).all()
        history = [
            {
                "approver_role": s.approver_role,
                "label": s.label,
                "status": s.status,
                "acted_by": name,
                "acted_at": s.acted_at.isoformat() if s.acted_at else None,
                "comment": s.comment,
            }
            for s, name in steps
        ]
        row["request_status"] = req.status if req else None
    bcr = await session.get(BudgetChangeRequest, pr.bcr_id) if pr.bcr_id else None
    raised = (
        await session.execute(
            select(BudgetChangeRequest.number, BudgetChangeRequest.status)
            .where(
                BudgetChangeRequest.ref_doc_type == svc.DOC,
                BudgetChangeRequest.ref_doc_id == str(pr.id),
            )
            .order_by(BudgetChangeRequest.created_at.desc())
        )
    ).first()
    lines = await svc.lines_of(session, pr.id)
    mine = pr.requester_id == principal.id
    from app.procurement.models import PurchaseOrder, Rfq  # local: keeps the PR router small

    rfq = (
        await session.execute(
            select(Rfq.id, Rfq.number).where(Rfq.pr_id == pr.id, Rfq.status != "cancelled")
        )
    ).first()
    po = (
        await session.execute(
            select(PurchaseOrder.id, PurchaseOrder.number).where(
                PurchaseOrder.pr_id == pr.id, PurchaseOrder.status != "cancelled"
            )
        )
    ).first()
    return {
        **row,
        "delivery_location": pr.delivery_location,
        "purpose": pr.purpose,
        "block_message": pr.block_message,
        "bcr_suggestion": _money(svc.bcr_suggestion(pr.shortfall)) if pr.shortfall else None,
        "reject_reason": pr.reject_reason,
        "cancel_reason": pr.cancel_reason,
        "request_id": str(pr.request_id) if pr.request_id else None,
        "approved_at": pr.approved_at.isoformat() if pr.approved_at else None,
        "linked_bcr": {"number": bcr.number, "status": bcr.status}
        if bcr
        else ({"number": raised[0], "status": raised[1]} if raised else None),
        "budget": {
            "budget": _money(bal.budget),
            "pre_commit": _money(bal.pre_commit),
            "commit": _money(bal.commit),
            "actual": _money(bal.actual),
            "available": _money(bal.available),
            "used_pct": str(bal.used_pct),
            "held_by_pr": _money(held["pre_commit"]),
        },
        "approvals": history,
        "can_edit": mine and pr.status in svc.EDITABLE,
        "can_submit": mine and pr.status in svc.EDITABLE,
        "can_cancel": mine and pr.status not in ("cancelled", "ordered"),
        "can_request_bcr": pr.status == "blocked",
        "can_rfq": pr.status == "approved"
        and rfq is None
        and principal.can("procurement", "create"),
        "rfq": {"id": str(rfq[0]), "number": rfq[1]} if rfq else None,
        "po": {"id": str(po[0]), "number": po[1]} if po else None,
        "lines": [
            {
                "item_code": x.item_code,
                "description": x.description,
                "qty": format(x.qty.normalize(), "f"),
                "uom": x.uom,
                "est_price": _money(x.est_price),
                "amount": _money(x.amount),
            }
            for x in lines
        ],
    }


@router.get("/prs/{pid}")
async def get_pr(pid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _detail(session, principal, await _load(session, principal, pid))


class LineBody(BaseModel):
    item_code: str | None = Field(default=None, max_length=30)
    description: str = Field(min_length=2, max_length=300)
    qty: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    uom: str = Field(min_length=1, max_length=10)
    est_price: Decimal = Field(ge=0, max_digits=18, decimal_places=0)

    @field_validator("item_code", mode="before")
    @classmethod
    def _blank(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


class PrBody(BaseModel):
    project_id: uuid.UUID
    wbs_code: str = Field(min_length=1, max_length=20)
    cost_element_code: str = Field(min_length=1, max_length=20)
    need_date: date
    delivery_location: str = Field(min_length=2, max_length=200)
    purpose: str | None = Field(default=None, max_length=4000)
    lines: list[LineBody] = Field(min_length=1, max_length=200)


def _lines(body: PrBody) -> list[svc.LineIn]:
    return [
        svc.LineIn(x.item_code, x.description.strip(), x.qty, x.uom.strip(), x.est_price)
        for x in body.lines
    ]


@router.post("/prs", status_code=201)
async def create_pr(body: PrBody, actor: Creator, session: Session) -> dict[str, Any]:
    pr = await svc.create(
        session,
        actor,
        project_id=body.project_id,
        wbs_code=body.wbs_code.upper(),
        cost_element_code=body.cost_element_code,
        need_date=body.need_date,
        delivery_location=body.delivery_location.strip(),
        purpose=body.purpose,
        lines=_lines(body),
    )
    await session.commit()
    return await _detail(session, actor, pr)


@router.put("/prs/{pid}")
async def update_pr(
    pid: uuid.UUID, body: PrBody, actor: Creator, session: Session
) -> dict[str, Any]:
    pr = await _load(session, actor, pid, lock=True)
    if pr.requester_id != actor.id:
        raise ForbiddenError("NOT_REQUESTER", "Hanya pemohon yang dapat mengubah PR ini.")
    await svc.update(
        session,
        actor,
        pr,
        wbs_code=body.wbs_code.upper(),
        cost_element_code=body.cost_element_code,
        need_date=body.need_date,
        delivery_location=body.delivery_location.strip(),
        purpose=body.purpose,
        lines=_lines(body),
    )
    await session.commit()
    return await _detail(session, actor, pr)


@router.post("/prs/{pid}/submit")
async def submit_pr(pid: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    pr = await _load(session, actor, pid, lock=True)
    await svc.submit(session, actor, pr)
    await session.commit()
    return await _detail(session, actor, pr)


class CancelBody(BaseModel):
    reason: str = Field(max_length=500)


@router.post("/prs/{pid}/cancel")
async def cancel_pr(
    pid: uuid.UUID, body: CancelBody, actor: Creator, session: Session
) -> dict[str, Any]:
    pr = await _load(session, actor, pid, lock=True)
    await svc.cancel(session, actor, pr, body.reason)
    await session.commit()
    return await _detail(session, actor, pr)
