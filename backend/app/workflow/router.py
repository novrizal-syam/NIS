import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth.models import Role, User
from app.auth.principal import CurrentUser, Principal, require
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.core.pagination import PageParams, page_params
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta
from app.workflow import engine, service
from app.workflow.conditions import describe
from app.workflow.models import ApprovalRequest, ApprovalStep, Delegation, DoaRule, DoaRuleChange
from app.workflow.rules_seed import DOC_TYPES
from app.workflow.schemas import (
    BulkIn,
    BulkItemOut,
    ChangeLine,
    DecisionIn,
    DelegationIn,
    DelegationOut,
    DocTypeOut,
    InboxItem,
    InboxPage,
    RejectIn,
    RequestDetail,
    RuleChangeIn,
    RuleChangeOut,
    RuleOut,
    StepOut,
)

router = APIRouter(prefix="/workflow", tags=["workflow"])
Session = Annotated[AsyncSession, Depends(get_session)]
Pages = Annotated[PageParams, Depends(page_params)]


@router.get("/doc-types")
async def doc_types(_: CurrentUser) -> list[DocTypeOut]:
    return [DocTypeOut(code=c, label=label, module=m) for c, (label, m) in DOC_TYPES.items()]


async def _role_names(session: AsyncSession) -> dict[str, str]:
    rows = await session.execute(select(Role.code, Role.name))
    return {code: name for code, name in rows.all()}


def _rule_lines(
    before: dict[str, Any] | None, after: dict[str, Any], role_names: dict[str, str]
) -> list[ChangeLine]:
    def steps(p: dict[str, Any]) -> str:
        return " → ".join(
            f"{s['seq']}. {role_names.get(s['approver_role'], s['approver_role'])}"
            + (f" ({s['label']})" if s.get("label") else "")
            for s in p["steps"]
        )

    fields: list[tuple[str, Any]] = [
        ("Nama aturan", lambda p: p["name"]),
        ("Kondisi", lambda p: describe(p.get("condition"))),
        ("Tahap persetujuan", steps),
        ("Eskalasi (jam)", lambda p: str(p["escalation_hours"])),
        ("Status", lambda p: "Aktif" if p.get("is_active", True) else "Nonaktif"),
    ]
    lines = []
    for label, fn in fields:
        new = fn(after)
        old = fn(before) if before else None
        if old != new:
            lines.append(ChangeLine(label=label, before=old, after=new))
    return lines


# --- inbox ------------------------------------------------------------------------------------


async def _inbox_rows(
    session: AsyncSession, principal: Principal, doc_type: str | None, q: str | None
) -> tuple[Any, Any]:
    cond = await engine.inbox_condition(session, principal)
    filters = [cond]
    if doc_type:
        filters.append(ApprovalRequest.doc_type == doc_type)
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            or_(ApprovalRequest.doc_number.ilike(like), ApprovalRequest.title.ilike(like))
        )
    base = (
        select(ApprovalRequest, ApprovalStep, User.full_name)
        .join(ApprovalStep, ApprovalStep.request_id == ApprovalRequest.id)
        .join(User, User.id == ApprovalRequest.requester_id)
        .where(*filters)
        .distinct(ApprovalRequest.id)
        .order_by(ApprovalRequest.id, ApprovalStep.seq)
    )
    return base, cond


def _inbox_item(
    req: ApprovalRequest,
    step: ApprovalStep,
    requester: str,
    now: datetime,
    role_names: dict[str, str],
) -> InboxItem:
    return InboxItem(
        request_id=req.id,
        doc_type=req.doc_type,
        doc_type_label=DOC_TYPES[req.doc_type][0],
        doc_number=req.doc_number,
        title=req.title,
        amount=req.amount,
        currency=req.currency,
        requester_name=requester,
        submitted_at=req.submitted_at,
        step_label=step.label or role_names.get(step.approver_role, step.approver_role),
        due_at=step.due_at,
        overdue=bool(step.due_at and step.due_at < now),
        escalated=step.escalated_at is not None,
    )


async def _inbox_items(
    session: AsyncSession, principal: Principal, doc_type: str | None, q: str | None
) -> tuple[list[InboxItem], Any]:
    base, cond = await _inbox_rows(session, principal, doc_type, q)
    now = datetime.now(UTC)
    rows = (await session.execute(base)).all()
    role_names = await _role_names(session)
    items = [_inbox_item(r, s, n, now, role_names) for r, s, n in rows]
    items.sort(key=lambda i: i.submitted_at)  # oldest first: work the queue in order
    return items, cond


@router.get("/inbox")
async def inbox(
    principal: CurrentUser,
    session: Session,
    pages: Pages,
    doc_type: str | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> InboxPage:
    items, cond = await _inbox_items(session, principal, doc_type, q)
    count_rows = await session.execute(
        select(ApprovalRequest.doc_type, func.count(func.distinct(ApprovalRequest.id)))
        .select_from(ApprovalStep)
        .join(ApprovalRequest, ApprovalRequest.id == ApprovalStep.request_id)
        .where(cond)
        .group_by(ApprovalRequest.doc_type)
    )
    return InboxPage(
        items=items[pages.offset : pages.offset + pages.page_size],
        total=len(items),
        page=pages.page,
        page_size=pages.page_size,
        counts={d: int(c) for d, c in count_rows.all()},
    )


@router.get("/inbox/count")
async def inbox_count(principal: CurrentUser, session: Session) -> dict[str, int]:
    return {"count": await engine.inbox_count(session, principal)}


@router.get("/inbox/export")
async def inbox_export(
    principal: CurrentUser, session: Session, doc_type: str | None = None, q: str | None = None
) -> StreamingResponse:
    items, _ = await _inbox_items(session, principal, doc_type, q)
    columns = [
        Column("Nomor", "doc_number", width=16),
        Column("Jenis", "doc_type_label", width=24),
        Column("Judul", "title", width=48),
        Column("Nilai", "amount", "idr"),
        Column("Pengaju", "requester_name", width=24),
        Column("Diajukan", "submitted_at", "datetime"),
        Column("Tahap", "step_label", width=20),
        Column("Batas waktu", "due_at", "datetime"),
    ]
    return xlsx_response(
        f"persetujuan-saya-{today_jakarta():%Y%m%d}.xlsx",
        "Persetujuan Saya",
        columns,
        (i.model_dump() for i in items),
    )


# --- requests ---------------------------------------------------------------------------------


async def _detail(
    session: AsyncSession, principal: Principal, request_id: uuid.UUID
) -> RequestDetail:
    req = await session.get(ApprovalRequest, request_id)
    if req is None:
        raise NotFoundError("APPROVAL_NOT_FOUND", "Permintaan persetujuan tidak ditemukan.")
    await session.refresh(req, ["steps"])
    user_ids = (
        {req.requester_id}
        | {s.acted_by for s in req.steps if s.acted_by}
        | {s.on_behalf_of for s in req.steps if s.on_behalf_of}
    )
    name_rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
    names: dict[uuid.UUID, str] = {uid: name for uid, name in name_rows.all()}
    role_names = await _role_names(session)

    can_act = False
    if req.status == engine.PENDING:
        cond = await engine.inbox_condition(session, principal)
        can_act = bool(
            (
                await session.execute(
                    select(ApprovalStep.id)
                    .join(ApprovalRequest, ApprovalRequest.id == ApprovalStep.request_id)
                    .where(cond, ApprovalRequest.id == req.id)
                    .limit(1)
                )
            ).first()
        )
    involved = principal.id in user_ids or can_act or principal.can("workflow", "view")
    if not involved:
        raise NotFoundError("APPROVAL_NOT_FOUND", "Permintaan persetujuan tidak ditemukan.")
    return RequestDetail(
        id=req.id,
        doc_type=req.doc_type,
        doc_type_label=DOC_TYPES[req.doc_type][0],
        doc_id=req.doc_id,
        doc_number=req.doc_number,
        title=req.title,
        amount=req.amount,
        currency=req.currency,
        status=req.status,
        requester_name=names.get(req.requester_id, "-"),
        submitted_at=req.submitted_at,
        decided_at=req.decided_at,
        rule_name=str(req.rule_snapshot.get("name", "")),
        steps=[
            StepOut(
                seq=s.seq,
                approver_role=s.approver_role,
                approver_role_name=role_names.get(s.approver_role, s.approver_role),
                label=s.label,
                status=s.status,
                acted_by_name=names.get(s.acted_by) if s.acted_by else None,
                on_behalf_of_name=names.get(s.on_behalf_of) if s.on_behalf_of else None,
                acted_at=s.acted_at,
                comment=s.comment,
                due_at=s.due_at,
            )
            for s in req.steps
        ],
        can_act=can_act,
        can_cancel=req.status == engine.PENDING and req.requester_id == principal.id,
        changes=(
            _rule_lines(req.context.get("before"), req.context["after"], role_names)
            if req.doc_type == "doa_change" and req.context.get("after")
            else []
        ),
        change_reason=req.context.get("reason") if req.doc_type == "doa_change" else None,
    )


@router.get("/requests/{request_id}")
async def request_detail(
    request_id: uuid.UUID, principal: CurrentUser, session: Session
) -> RequestDetail:
    return await _detail(session, principal, request_id)


@router.post("/requests/{request_id}/approve")
async def approve(
    request_id: uuid.UUID, body: DecisionIn, principal: CurrentUser, session: Session
) -> RequestDetail:
    await engine.approve(session, principal, request_id, body.comment)
    await session.commit()
    return await _detail(session, principal, request_id)


@router.post("/requests/{request_id}/reject")
async def reject(
    request_id: uuid.UUID, body: RejectIn, principal: CurrentUser, session: Session
) -> RequestDetail:
    await engine.reject(session, principal, request_id, body.comment)
    await session.commit()
    return await _detail(session, principal, request_id)


@router.post("/requests/{request_id}/cancel")
async def cancel(
    request_id: uuid.UUID, body: DecisionIn, principal: CurrentUser, session: Session
) -> RequestDetail:
    await engine.cancel(session, principal, request_id, body.comment)
    await session.commit()
    return await _detail(session, principal, request_id)


@router.post("/approvals/bulk")
async def bulk(body: BulkIn, principal: CurrentUser, session: Session) -> list[BulkItemOut]:
    results = await engine.bulk_approve(
        session, principal, body.request_ids, body.doc_type, body.comment
    )
    await session.commit()
    return [BulkItemOut(**r.__dict__) for r in results]


# --- delegations ------------------------------------------------------------------------------


@router.get("/delegations")
async def delegations(principal: CurrentUser, session: Session) -> list[DelegationOut]:
    delegator, delegate = aliased(User), aliased(User)
    rows = await session.execute(
        select(Delegation, delegator.full_name, delegate.full_name)
        .join(delegator, delegator.id == Delegation.delegator_id)
        .join(delegate, delegate.id == Delegation.delegate_id)
        .where(or_(Delegation.delegator_id == principal.id, Delegation.delegate_id == principal.id))
        .order_by(Delegation.start_date.desc())
    )
    today = today_jakarta()
    return [
        DelegationOut(
            id=d.id,
            delegator_name=a,
            delegate_name=b,
            role_code=d.role_code,
            start_date=d.start_date,
            end_date=d.end_date,
            reason=d.reason,
            active=d.revoked_at is None and d.start_date <= today <= d.end_date,
            can_revoke=d.delegator_id == principal.id
            and d.revoked_at is None
            and d.end_date >= today,
        )
        for d, a, b in rows.all()
    ]


@router.post("/delegations", status_code=201)
async def create_delegation(
    body: DelegationIn, principal: CurrentUser, session: Session
) -> dict[str, str]:
    d = await service.create_delegation(session, principal, **body.model_dump())
    await session.commit()
    return {"id": str(d.id)}


@router.post("/delegations/{delegation_id}/revoke", status_code=204)
async def revoke_delegation(
    delegation_id: uuid.UUID, principal: CurrentUser, session: Session
) -> Response:
    await service.revoke_delegation(session, principal, delegation_id)
    await session.commit()
    return Response(status_code=204)


# --- rules (Settings) -------------------------------------------------------------------------


@router.get("/rules")
async def rules(
    session: Session, _: Annotated[Principal, Depends(require("workflow", "view"))]
) -> list[RuleOut]:
    pending = set(
        (
            await session.execute(
                select(DoaRuleChange.rule_id).where(
                    DoaRuleChange.status == "pending", DoaRuleChange.rule_id.is_not(None)
                )
            )
        ).scalars()
    )
    order = {code: i for i, code in enumerate(DOC_TYPES)}
    rows = (await session.execute(select(DoaRule))).scalars().all()
    rows = sorted(rows, key=lambda r: (order.get(r.doc_type, 999), r.priority))
    return [
        RuleOut(
            id=r.id,
            doc_type=r.doc_type,
            doc_type_label=DOC_TYPES[r.doc_type][0],
            pending_change=r.id in pending,
            **{k: v for k, v in service.rule_payload(r).items() if k != "doc_type"},
        )
        for r in rows
    ]


@router.get("/rule-changes")
async def rule_changes(
    session: Session, _: Annotated[Principal, Depends(require("workflow", "view"))]
) -> list[RuleChangeOut]:
    rows = await session.execute(
        select(DoaRuleChange, ApprovalRequest.id)
        .outerjoin(
            ApprovalRequest,
            (ApprovalRequest.doc_type == "doa_change")
            & (ApprovalRequest.doc_id == func.cast(DoaRuleChange.id, ApprovalRequest.doc_id.type)),
        )
        .order_by(DoaRuleChange.created_at.desc())
        .limit(50)
    )
    return [
        RuleChangeOut(
            id=c.id,
            rule_id=c.rule_id,
            doc_type=c.payload["doc_type"],
            name=c.payload["name"],
            reason=c.reason,
            status=c.status,
            request_id=rid,
            created_at=c.created_at,
        )
        for c, rid in rows.all()
    ]


@router.post("/rule-changes", status_code=201)
async def propose_rule_change(
    body: RuleChangeIn,
    session: Session,
    principal: Annotated[Principal, Depends(require("workflow", "admin"))],
) -> dict[str, str]:
    change, request = await service.propose_rule_change(
        session, principal, rule_id=body.rule_id, payload=body.rule.model_dump(), reason=body.reason
    )
    await session.commit()
    return {
        "change_id": str(change.id),
        "request_id": str(request.id),
        "doc_number": request.doc_number,
    }
