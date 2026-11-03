"""The one DOA engine (CLAUDE.md rule 3). Every approval in the ERP goes through here.

Document modules call `submit()` inside the transaction that moves their document to
"Submitted" and register `on_approved` / `on_rejected` hooks with `register_document()`.
Engine functions never commit; the caller does, so document and approval stay consistent.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth.models import Role, User, UserRole
from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.services import audit
from app.services.audit import AuditAction
from app.services.numbering import today_jakarta
from app.workflow.conditions import evaluate
from app.workflow.models import ApprovalRequest, ApprovalStep, Delegation, DoaRule
from app.workflow.rules_seed import DOC_TYPES

log = logging.getLogger("app.workflow")

PENDING, APPROVED, REJECTED, CANCELLED = "pending", "approved", "rejected", "cancelled"
WAITING, SKIPPED = "waiting", "skipped"

Hook = Callable[[AsyncSession, ApprovalRequest], Awaitable[None]]
EventHandler = Callable[[AsyncSession, str, ApprovalRequest, list[uuid.UUID]], Awaitable[None]]


@dataclass
class _DocHooks:
    on_approved: Hook | None = None
    on_rejected: Hook | None = None


_hooks: dict[str, _DocHooks] = {}
_event_handlers: list[EventHandler] = []


def register_document(
    doc_type: str, *, on_approved: Hook | None = None, on_rejected: Hook | None = None
) -> None:
    """Document modules: react to the final decision (e.g. PR -> Approved / back to Draft)."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"unknown doc_type {doc_type!r}")
    _hooks[doc_type] = _DocHooks(on_approved, on_rejected)


def on_event(handler: EventHandler) -> None:
    """Subscribe to engine events (submitted, step_activated, approved, rejected, cancelled,
    escalated). The notification module uses this; recipients are user ids."""
    _event_handlers.append(handler)


async def _emit(
    session: AsyncSession, event: str, request: ApprovalRequest, recipients: list[uuid.UUID]
) -> None:
    for handler in _event_handlers:
        await handler(session, event, request, sorted(set(recipients), key=str))


def _now() -> datetime:
    return datetime.now(UTC)


def doc_label(doc_type: str) -> str:
    return DOC_TYPES[doc_type][0]


# --- rule selection ---------------------------------------------------------------------------


async def select_rule(session: AsyncSession, doc_type: str, ctx: dict[str, Any]) -> DoaRule | None:
    rules = (
        await session.execute(
            select(DoaRule)
            .where(DoaRule.doc_type == doc_type, DoaRule.is_active.is_(True))
            .order_by(DoaRule.priority, DoaRule.created_at)
        )
    ).scalars()
    for rule in rules:
        if rule.steps and evaluate(rule.condition, ctx):
            return rule
    return None


def _snapshot(rule: DoaRule) -> dict[str, Any]:
    return {
        "rule_id": str(rule.id),
        "name": rule.name,
        "condition": rule.condition,
        "escalation_hours": rule.escalation_hours,
        "escalate_to_role": rule.escalate_to_role,
        "steps": [
            {"seq": s.seq, "role": s.approver_role, "label": s.label, "scope": s.approver_scope}
            for s in rule.steps
        ],
    }


def _jsonable(ctx: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, Decimal | uuid.UUID | date) else v) for k, v in ctx.items()}


# --- who may act ------------------------------------------------------------------------------


async def holders_of_role(session: AsyncSession, role_code: str) -> list[uuid.UUID]:
    rows = await session.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            Role.code == role_code,
            Role.is_active.is_(True),
            User.is_active.is_(True),
            UserRole.active_now(),
        )
    )
    return list(rows.scalars())


def _own_roles(principal: Principal) -> set[str]:
    # An active role (role switcher) limits what the user acts as.
    return {principal.active_role} if principal.active_role else principal.role_codes


async def _active_delegations(
    session: AsyncSession, delegate_id: uuid.UUID, today: date
) -> list[tuple[str, uuid.UUID]]:
    """(role_code, delegator_id) pairs the user may currently act for."""
    rows = await session.execute(
        select(Delegation.role_code, Delegation.delegator_id, Role.code)
        .join(UserRole, UserRole.user_id == Delegation.delegator_id)
        .join(Role, Role.id == UserRole.role_id)
        .join(User, User.id == Delegation.delegator_id)
        .where(
            Delegation.delegate_id == delegate_id,
            Delegation.revoked_at.is_(None),
            Delegation.start_date <= today,
            Delegation.end_date >= today,
            User.is_active.is_(True),
            UserRole.active_now(),
            or_(Delegation.role_code.is_(None), Delegation.role_code == Role.code),
        )
    )
    return [(role_code, delegator) for _, delegator, role_code in rows.all()]


async def _resolve_actor(
    session: AsyncSession, principal: Principal, request: ApprovalRequest, step: ApprovalStep
) -> tuple[bool, uuid.UUID | None]:
    """Can the user act on this step? Returns (allowed, on_behalf_of delegator)."""
    if step.approver_scope == "project" and request.project_id not in principal.project_ids:
        return False, None
    module = DOC_TYPES[request.doc_type][1]
    if step.approver_role in _own_roles(principal) and principal.can(module, "approve"):
        return True, None
    for role_code, delegator in await _active_delegations(session, principal.id, today_jakarta()):
        if role_code == step.approver_role and delegator != request.requester_id:
            return True, delegator
    return False, None


# --- lifecycle --------------------------------------------------------------------------------


async def submit(
    session: AsyncSession,
    principal: Principal,
    *,
    doc_type: str,
    doc_id: uuid.UUID | str,
    doc_number: str,
    title: str,
    amount: Decimal | int | None = None,
    currency: str = "IDR",
    context: dict[str, Any] | None = None,
    project_id: uuid.UUID | None = None,
) -> ApprovalRequest:
    if doc_type not in DOC_TYPES:
        raise AppError("UNKNOWN_DOC_TYPE", f"Jenis dokumen '{doc_type}' tidak dikenal.")
    ctx = {**(context or {}), "amount": amount}
    rule = await select_rule(session, doc_type, ctx)
    if rule is None:
        raise AppError(
            "NO_DOA_RULE",
            f"Tidak ada aturan DOA yang cocok untuk {doc_label(doc_type)}. Hubungi admin.",
            status_code=422,
        )
    open_req = await session.execute(
        select(ApprovalRequest.id).where(
            ApprovalRequest.doc_type == doc_type,
            ApprovalRequest.doc_id == str(doc_id),
            ApprovalRequest.status == PENDING,
        )
    )
    if open_req.first():
        raise ConflictError("ALREADY_SUBMITTED", f"{doc_number} sudah menunggu persetujuan.")

    now = _now()
    request = ApprovalRequest(
        doc_type=doc_type,
        doc_id=str(doc_id),
        doc_number=doc_number,
        title=title,
        amount=Decimal(amount) if amount is not None else None,
        currency=currency,
        context=_jsonable(ctx),
        project_id=project_id,
        requester_id=principal.id,
        rule_id=rule.id,
        rule_snapshot=_snapshot(rule),
        status=PENDING,
        current_seq=min(s.seq for s in rule.steps),
        submitted_at=now,
        created_by=principal.id,
    )
    session.add(request)
    await session.flush()
    for s in rule.steps:
        active = s.seq == request.current_seq
        session.add(
            ApprovalStep(
                request_id=request.id,
                seq=s.seq,
                approver_role=s.approver_role,
                label=s.label,
                approver_scope=s.approver_scope,
                status=PENDING if active else WAITING,
                activated_at=now if active else None,
                due_at=now + timedelta(hours=rule.escalation_hours) if active else None,
            )
        )
    await session.flush()
    await session.refresh(request, ["steps"])
    await audit.record(
        session,
        action="submit",
        entity_type="approval_request",
        entity_id=request.id,
        actor_id=principal.id,
        after={
            "doc_type": doc_type,
            "doc_number": doc_number,
            "rule": rule.name,
            "amount": request.amount,
        },
    )
    await _emit(session, "submitted", request, await _step_recipients(session, request))
    return request


async def _step_recipients(session: AsyncSession, request: ApprovalRequest) -> list[uuid.UUID]:
    users: list[uuid.UUID] = []
    for step in request.steps:
        if step.status == PENDING:
            users += await holders_of_role(session, step.approver_role)
    return [u for u in users if u != request.requester_id]


async def _lock(session: AsyncSession, request_id: uuid.UUID) -> ApprovalRequest:
    request = (
        await session.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if request is None:
        raise NotFoundError("APPROVAL_NOT_FOUND", "Permintaan persetujuan tidak ditemukan.")
    await session.refresh(request, ["steps"])
    if request.status != PENDING:
        raise ConflictError(
            "APPROVAL_CLOSED",
            f"{request.doc_number} sudah diproses dan tidak menunggu persetujuan.",
        )
    return request


async def _actionable_step(
    session: AsyncSession, principal: Principal, request: ApprovalRequest
) -> tuple[ApprovalStep, uuid.UUID | None]:
    # Segregation of duties: requester never approves their own document (all doc types).
    if request.requester_id == principal.id:
        raise ForbiddenError(
            "SOD_SELF_APPROVAL",
            "Anda tidak dapat menyetujui atau menolak dokumen yang Anda ajukan sendiri.",
        )
    if any(s.acted_by == principal.id for s in request.steps):
        raise ForbiddenError(
            "SOD_ALREADY_ACTED", "Anda sudah memberi keputusan pada tahap lain dokumen ini."
        )
    for step in request.steps:
        if step.seq == request.current_seq and step.status == PENDING:
            allowed, on_behalf = await _resolve_actor(session, principal, request, step)
            if allowed:
                return step, on_behalf
    raise ForbiddenError("NOT_APPROVER", f"{request.doc_number} tidak menunggu persetujuan Anda.")


async def approve(
    session: AsyncSession, principal: Principal, request_id: uuid.UUID, comment: str | None = None
) -> ApprovalRequest:
    request = await _lock(session, request_id)
    step, on_behalf = await _actionable_step(session, principal, request)
    now = _now()
    step.status, step.acted_by, step.on_behalf_of = APPROVED, principal.id, on_behalf
    step.acted_at, step.comment = now, (comment or "").strip() or None

    await audit.record(
        session,
        action=AuditAction.APPROVE,
        entity_type="approval_request",
        entity_id=request.id,
        actor_id=principal.id,
        after={"step": step.label or step.approver_role, "seq": step.seq, "comment": step.comment},
        note=f"atas nama {on_behalf}" if on_behalf else None,
    )

    current = [s for s in request.steps if s.seq == request.current_seq]
    if all(s.status == APPROVED for s in current):
        later = sorted({s.seq for s in request.steps if s.seq > request.current_seq})
        if later:
            request.current_seq = later[0]
            hours = int(request.rule_snapshot.get("escalation_hours", 48))
            for s in request.steps:
                if s.seq == request.current_seq:
                    s.status, s.activated_at = PENDING, now
                    s.due_at = now + timedelta(hours=hours)
            await session.flush()
            await _emit(
                session, "step_activated", request, await _step_recipients(session, request)
            )
        else:
            request.status, request.decided_at = APPROVED, now
            await session.flush()
            hooks = _hooks.get(request.doc_type)
            if hooks and hooks.on_approved:
                await hooks.on_approved(session, request)
            await _emit(session, "approved", request, [request.requester_id])
    await session.flush()
    return request


async def reject(
    session: AsyncSession, principal: Principal, request_id: uuid.UUID, comment: str
) -> ApprovalRequest:
    if not comment or not comment.strip():
        raise AppError(
            "COMMENT_REQUIRED",
            "Alasan penolakan wajib diisi agar pengaju tahu yang harus diperbaiki.",
            status_code=422,
        )
    request = await _lock(session, request_id)
    step, on_behalf = await _actionable_step(session, principal, request)
    now = _now()
    step.status, step.acted_by, step.on_behalf_of = REJECTED, principal.id, on_behalf
    step.acted_at, step.comment = now, comment.strip()
    for s in request.steps:
        if s.status in (PENDING, WAITING):
            s.status = SKIPPED
    request.status, request.decided_at = REJECTED, now
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.REJECT,
        entity_type="approval_request",
        entity_id=request.id,
        actor_id=principal.id,
        after={"step": step.label or step.approver_role, "comment": step.comment},
    )
    hooks = _hooks.get(request.doc_type)
    if hooks and hooks.on_rejected:  # the document goes back to Draft
        await hooks.on_rejected(session, request)
    await _emit(session, "rejected", request, [request.requester_id])
    return request


async def cancel(
    session: AsyncSession, principal: Principal, request_id: uuid.UUID, comment: str | None = None
) -> ApprovalRequest:
    request = await _lock(session, request_id)
    if request.requester_id != principal.id:
        raise ForbiddenError("NOT_REQUESTER", "Hanya pengaju yang dapat menarik pengajuan ini.")
    for s in request.steps:
        if s.status in (PENDING, WAITING):
            s.status = SKIPPED
    request.status, request.decided_at = CANCELLED, _now()
    await session.flush()
    await audit.record(
        session,
        action="cancel",
        entity_type="approval_request",
        entity_id=request.id,
        actor_id=principal.id,
        after={"comment": comment},
    )
    hooks = _hooks.get(request.doc_type)
    if hooks and hooks.on_rejected:
        await hooks.on_rejected(session, request)
    await _emit(session, "cancelled", request, [])
    return request


@dataclass
class BulkResult:
    request_id: uuid.UUID
    ok: bool
    code: str | None = None
    message: str | None = None


async def bulk_approve(
    session: AsyncSession,
    principal: Principal,
    request_ids: list[uuid.UUID],
    doc_type: str,
    comment: str | None = None,
) -> list[BulkResult]:
    """Approve several requests of ONE doc_type; each succeeds or fails on its own."""
    results: list[BulkResult] = []
    for rid in dict.fromkeys(request_ids):
        try:
            async with session.begin_nested():
                req = await session.get(ApprovalRequest, rid)
                if req is not None and req.doc_type != doc_type:
                    raise AppError(
                        "BULK_MIXED_TYPES",
                        "Setujui massal hanya untuk satu jenis dokumen yang sama.",
                    )
                await approve(session, principal, rid, comment)
            results.append(BulkResult(rid, True))
        except AppError as exc:
            results.append(BulkResult(rid, False, exc.code, exc.message))
    return results


async def escalate_overdue(session: AsyncSession, now: datetime | None = None) -> int:
    """Mark overdue pending steps as escalated and notify approvers plus the rule's
    escalation role. Safe to run repeatedly (each step escalates once)."""
    now = now or _now()
    steps = (
        (
            await session.execute(
                select(ApprovalStep)
                .join(ApprovalRequest, ApprovalRequest.id == ApprovalStep.request_id)
                .where(
                    ApprovalStep.status == PENDING,
                    ApprovalStep.escalated_at.is_(None),
                    ApprovalStep.due_at <= now,
                    ApprovalRequest.status == PENDING,
                )
                .with_for_update(skip_locked=True, of=ApprovalStep)
            )
        )
        .scalars()
        .all()
    )
    for step in steps:
        step.escalated_at = now
        request = await session.get(ApprovalRequest, step.request_id)
        assert request is not None
        recipients = await holders_of_role(session, step.approver_role)
        escalate_to = request.rule_snapshot.get("escalate_to_role")
        if escalate_to:
            recipients += await holders_of_role(session, escalate_to)
        await audit.record(
            session,
            action="escalate",
            entity_type="approval_request",
            entity_id=request.id,
            actor_id=None,
            after={"step": step.label or step.approver_role, "escalate_to": escalate_to},
        )
        await _emit(
            session, "escalated", request, [u for u in recipients if u != request.requester_id]
        )
    await session.flush()
    return len(steps)


# --- inbox ------------------------------------------------------------------------------------


async def inbox_condition(session: AsyncSession, principal: Principal) -> Any:
    """SQL condition on (ApprovalStep, ApprovalRequest) for steps waiting for this user."""
    own_roles = _own_roles(principal)
    allowed_types = [d for d, (_, module) in DOC_TYPES.items() if principal.can(module, "approve")]
    delegated = await _active_delegations(session, principal.id, today_jakarta())

    by_role = (
        and_(ApprovalStep.approver_role.in_(own_roles), ApprovalRequest.doc_type.in_(allowed_types))
        if own_roles and allowed_types
        else false()
    )
    via_delegation = [
        and_(ApprovalStep.approver_role == role, ApprovalRequest.requester_id != delegator)
        for role, delegator in delegated
    ]
    scope_ok = (
        or_(
            ApprovalStep.approver_scope != "project",
            ApprovalRequest.project_id.in_(principal.project_ids),
        )
        if principal.project_ids
        else ApprovalStep.approver_scope != "project"
    )
    other = aliased(ApprovalStep)
    already_acted = exists().where(
        other.request_id == ApprovalRequest.id, other.acted_by == principal.id
    )
    return and_(
        ApprovalStep.status == PENDING,
        ApprovalRequest.status == PENDING,
        ApprovalStep.seq == ApprovalRequest.current_seq,
        ApprovalRequest.requester_id != principal.id,
        ~already_acted,
        scope_ok,
        or_(by_role, *via_delegation),
    )


async def inbox_count(session: AsyncSession, principal: Principal) -> int:
    cond = await inbox_condition(session, principal)
    stmt = (
        select(func.count(func.distinct(ApprovalRequest.id)))
        .select_from(ApprovalStep)
        .join(ApprovalRequest, ApprovalRequest.id == ApprovalStep.request_id)
        .where(cond)
    )
    return int((await session.execute(stmt)).scalar_one())
