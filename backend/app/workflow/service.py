"""Delegations and DOA rule changes (rule changes are themselves approved by the engine)."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.auth.principal import Principal
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.services import audit
from app.services.audit import AuditAction
from app.workflow import engine
from app.workflow.conditions import validate
from app.workflow.models import ApprovalRequest, Delegation, DoaRule, DoaRuleChange, DoaRuleStep
from app.workflow.rules_seed import DOC_TYPES


async def create_delegation(
    session: AsyncSession,
    principal: Principal,
    *,
    delegate_id: uuid.UUID,
    role_code: str | None,
    start_date: date,
    end_date: date,
    reason: str,
) -> Delegation:
    if delegate_id == principal.id:
        raise AppError("DELEGATE_SELF", "Delegasi harus kepada orang lain.", status_code=422)
    if end_date < start_date:
        raise AppError(
            "INVALID_PERIOD", "Tanggal selesai tidak boleh sebelum tanggal mulai.", status_code=422
        )
    if role_code and role_code not in principal.role_codes:
        raise ForbiddenError(
            "ROLE_NOT_ASSIGNED", "Anda hanya dapat mendelegasikan peran Anda sendiri."
        )
    delegate = await session.get(User, delegate_id)
    if delegate is None or not delegate.is_active:
        raise AppError("DELEGATE_INVALID", "Penerima delegasi tidak ditemukan atau tidak aktif.")
    d = Delegation(
        delegator_id=principal.id,
        delegate_id=delegate_id,
        role_code=role_code,
        start_date=start_date,
        end_date=end_date,
        reason=reason.strip(),
        created_by=principal.id,
    )
    session.add(d)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="doa_delegation",
        entity_id=d.id,
        actor_id=principal.id,
        after={
            "delegate": delegate.email,
            "role": role_code or "semua peran",
            "start": start_date,
            "end": end_date,
            "reason": d.reason,
        },
    )
    return d


async def revoke_delegation(
    session: AsyncSession, principal: Principal, delegation_id: uuid.UUID
) -> None:
    d = await session.get(Delegation, delegation_id)
    if d is None or d.delegator_id != principal.id:
        raise NotFoundError("DELEGATION_NOT_FOUND", "Delegasi tidak ditemukan.")
    if d.revoked_at is None:
        d.revoked_at = datetime.now(UTC)
        await audit.record(
            session,
            action="revoke",
            entity_type="doa_delegation",
            entity_id=d.id,
            actor_id=principal.id,
        )


# --- rule changes -----------------------------------------------------------------------------


def rule_payload(rule: DoaRule) -> dict[str, Any]:
    return {
        "doc_type": rule.doc_type,
        "name": rule.name,
        "priority": rule.priority,
        "condition": rule.condition,
        "escalation_hours": rule.escalation_hours,
        "escalate_to_role": rule.escalate_to_role,
        "is_active": rule.is_active,
        "note": rule.note,
        "steps": [
            {
                "seq": s.seq,
                "approver_role": s.approver_role,
                "label": s.label,
                "approver_scope": s.approver_scope,
            }
            for s in rule.steps
        ],
    }


async def _validate_payload(session: AsyncSession, payload: dict[str, Any]) -> None:
    if payload["doc_type"] not in DOC_TYPES:
        raise AppError("UNKNOWN_DOC_TYPE", "Jenis dokumen tidak dikenal.", status_code=422)
    validate(payload.get("condition"))
    steps = payload.get("steps") or []
    if not steps:
        raise AppError(
            "STEPS_REQUIRED", "Aturan wajib punya minimal satu tahap persetujuan.", status_code=422
        )
    roles = {s["approver_role"] for s in steps}
    if payload.get("escalate_to_role"):
        roles.add(payload["escalate_to_role"])
    known = set((await session.execute(select(Role.code).where(Role.code.in_(roles)))).scalars())
    if roles - known:
        raise AppError(
            "UNKNOWN_ROLE",
            f"Peran tidak dikenal: {', '.join(sorted(roles - known))}.",
            status_code=422,
        )


async def propose_rule_change(
    session: AsyncSession,
    principal: Principal,
    *,
    rule_id: uuid.UUID | None,
    payload: dict[str, Any],
    reason: str,
) -> tuple[DoaRuleChange, ApprovalRequest]:
    await _validate_payload(session, payload)
    before = None
    if rule_id is not None:
        rule = await session.get(DoaRule, rule_id)
        if rule is None:
            raise NotFoundError("RULE_NOT_FOUND", "Aturan DOA tidak ditemukan.")
        before = rule_payload(rule)
    change = DoaRuleChange(
        rule_id=rule_id, payload=payload, reason=reason.strip(), created_by=principal.id
    )
    session.add(change)
    await session.flush()
    label = DOC_TYPES[payload["doc_type"]][0]
    request = await engine.submit(
        session,
        principal,
        doc_type="doa_change",
        doc_id=change.id,
        doc_number=f"DOA-{str(change.id)[:8].upper()}",
        title=f"{'Ubah' if rule_id else 'Tambah'} aturan {label}: {payload['name']}",
        context={"before": before, "after": payload, "reason": change.reason},
    )
    return change, request


async def _apply_change(session: AsyncSession, request: ApprovalRequest) -> None:
    change = await session.get(DoaRuleChange, uuid.UUID(request.doc_id))
    assert change is not None
    p = change.payload
    if change.rule_id:
        rule = await session.get(DoaRule, change.rule_id)
        assert rule is not None
        before = rule_payload(rule)
        rule.steps.clear()
        await session.flush()
    else:
        rule = DoaRule(doc_type=p["doc_type"], created_by=change.created_by)
        session.add(rule)
        before = None
    for key in (
        "name",
        "priority",
        "condition",
        "escalation_hours",
        "escalate_to_role",
        "is_active",
        "note",
    ):
        if key in p:
            setattr(rule, key, p[key])
    rule.steps.extend(
        DoaRuleStep(
            seq=s["seq"],
            approver_role=s["approver_role"],
            label=s.get("label", ""),
            approver_scope=s.get("approver_scope", "all"),
        )
        for s in p["steps"]
    )
    change.status, change.applied_at = "applied", datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE if before else AuditAction.CREATE,
        entity_type="doa_rule",
        entity_id=rule.id,
        actor_id=request.steps[-1].acted_by if request.steps else None,
        before=before,
        after=rule_payload(rule),
        note=f"Disetujui melalui {request.doc_number}",
    )


async def _reject_change(session: AsyncSession, request: ApprovalRequest) -> None:
    change = await session.get(DoaRuleChange, uuid.UUID(request.doc_id))
    if change is not None:
        change.status = request.status  # rejected or cancelled


engine.register_document("doa_change", on_approved=_apply_change, on_rejected=_reject_change)
