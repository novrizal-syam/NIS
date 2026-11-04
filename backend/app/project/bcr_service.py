"""Budget Change Request (PROCESS.md · BCR; DOA.md · bcr).

    contingency_release  moves amount from a Contingency line (locked reserve) to the target line
    transfer             moves amount from another line (<= its available) to the target line
    budget_increase      adds amount to the target line (total budget grows)

Approval creates budget version v1, v2 ... (baseline v0 is never touched) and emits
`bcr_approved(project_id, wbs_id, cost_element_code, ref)` for listeners (PRs blocked by budget,
phase 04a). Balances are re-validated under row locks at approval time.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.project import budget_service
from app.project import service as projects
from app.project.models import (
    BudgetChangeRequest,
    BudgetVersion,
    BudgetVersionLine,
    Project,
    ProjectBudgetLine,
    ProjectWbs,
)
from app.services import audit, numbering
from app.services import budget_control as bc
from app.services.audit import AuditAction
from app.workflow import engine
from app.workflow.models import ApprovalRequest

SOURCES = ("contingency_release", "budget_increase", "transfer")
REASONS = ("client_variation", "scope_change", "price_escalation", "estimate_error")
SOURCE_LABELS = {
    "contingency_release": "Pelepasan kontinjensi",
    "budget_increase": "Kenaikan anggaran",
    "transfer": "Transfer",
}


@dataclass(frozen=True)
class BcrRef:
    project_id: uuid.UUID
    wbs_id: uuid.UUID
    cost_element_code: str
    ref_doc_type: str | None
    ref_doc_id: str | None
    bcr_id: uuid.UUID


Listener = Callable[[AsyncSession, BcrRef], Awaitable[None]]
_listeners: list[Listener] = []


def on_bcr_approved(listener: Listener) -> None:
    """Subscribe to `bcr_approved` (e.g. re-check PRs blocked by budget on that line)."""
    _listeners.append(listener)


def _now() -> datetime:
    return datetime.now(UTC)


def _rp(v: Decimal) -> str:
    from app.services.money import format_idr

    return format_idr(v)


async def _line_row(
    session: AsyncSession, project_id: uuid.UUID, wbs_id: uuid.UUID, ce: str, lock: bool
) -> ProjectBudgetLine | None:
    stmt = select(ProjectBudgetLine).where(
        ProjectBudgetLine.project_id == project_id,
        ProjectBudgetLine.wbs_id == wbs_id,
        ProjectBudgetLine.cost_element_code == ce,
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def _contingency_line(
    session: AsyncSession, project_id: uuid.UUID, from_wbs_id: uuid.UUID | None, lock: bool
) -> ProjectBudgetLine | None:
    stmt = select(ProjectBudgetLine).where(
        ProjectBudgetLine.project_id == project_id,
        ProjectBudgetLine.cost_element_code == projects.CONTINGENCY,
    )
    if from_wbs_id is not None:
        stmt = stmt.where(ProjectBudgetLine.wbs_id == from_wbs_id)
    stmt = stmt.order_by(ProjectBudgetLine.amount.desc()).limit(1)
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def _validate_source(
    session: AsyncSession, bcr: BudgetChangeRequest, lock: bool
) -> ProjectBudgetLine | None:
    """Returns the source line (None for an increase); raises when the source is short."""
    if bcr.source == "contingency_release":
        row = await _contingency_line(session, bcr.project_id, bcr.from_wbs_id, lock)
        remaining = row.amount if row is not None else Decimal(0)
        if bcr.amount > remaining:
            raise AppError(
                "CONTINGENCY_INSUFFICIENT",
                f"Kontinjensi tersisa {_rp(remaining)}; tidak dapat melepas {_rp(bcr.amount)}.",
                status_code=422,
                details={"remaining": str(remaining)},
            )
        return row
    if bcr.source == "transfer":
        assert bcr.from_wbs_id is not None and bcr.from_cost_element_code is not None
        row = await _line_row(
            session, bcr.project_id, bcr.from_wbs_id, bcr.from_cost_element_code, lock
        )
        line = bc.Line(bcr.project_id, bcr.from_wbs_id, bcr.from_cost_element_code)
        free = (await bc.available(session, line)).available if row is not None else Decimal(0)
        if bcr.amount > free:
            raise AppError(
                "TRANSFER_EXCEEDS_AVAILABLE",
                f"Tersedia di baris sumber {_rp(max(free, Decimal(0)))}; "
                f"tidak dapat mentransfer {_rp(bcr.amount)}.",
                status_code=422,
                details={"available": str(free)},
            )
        return row
    return None


async def create(
    session: AsyncSession,
    actor: Principal,
    project: Project,
    *,
    wbs_code: str,
    cost_element_code: str,
    amount: Decimal,
    source: str,
    reason: str,
    justification: str,
    from_wbs_code: str | None,
    from_cost_element_code: str | None,
    revenue_change: Decimal | None,
    ref_doc_type: str | None,
    ref_doc_id: str | None,
) -> BudgetChangeRequest:
    if project.status != "locked":
        raise ConflictError(
            "PROJECT_NOT_LOCKED", "BCR hanya untuk proyek yang anggarannya sudah terkunci."
        )
    if source not in SOURCES or reason not in REASONS:
        raise AppError("BCR_INVALID", "Sumber atau alasan BCR tidak dikenal.", status_code=422)
    if amount <= 0 or amount != amount.to_integral_value():
        raise AppError("AMOUNT_INVALID", "Nilai harus rupiah bulat lebih dari 0.", status_code=422)
    if cost_element_code == projects.CONTINGENCY:
        raise AppError(
            "TARGET_CONTINGENCY",
            "Baris tujuan tidak boleh Kontinjensi; pilih elemen biaya yang akan dipakai.",
            status_code=422,
        )
    if len(justification.strip()) < 10:
        raise AppError(
            "JUSTIFICATION_REQUIRED", "Tulis justifikasi (min. 10 karakter).", status_code=422
        )
    wbs = {w.code: w for w in await projects.wbs_of(session, project.id)}
    if wbs_code not in wbs:
        raise AppError("WBS_INVALID", f"WBS {wbs_code} tidak ada.", status_code=422)
    from_wbs_id = None
    if source == "transfer":
        if not from_wbs_code or not from_cost_element_code:
            raise AppError(
                "TRANSFER_SOURCE_REQUIRED", "Pilih baris sumber transfer.", status_code=422
            )
        if from_wbs_code not in wbs or from_cost_element_code == projects.CONTINGENCY:
            raise AppError(
                "TRANSFER_SOURCE_INVALID",
                "Baris sumber tidak valid (Kontinjensi dilepas lewat sumber kontinjensi).",
                status_code=422,
            )
        if (from_wbs_code, from_cost_element_code) == (wbs_code, cost_element_code):
            raise AppError("TRANSFER_SAME_LINE", "Baris sumber dan tujuan sama.", status_code=422)
        from_wbs_id = wbs[from_wbs_code].id
    elif source == "contingency_release" and from_wbs_code:
        if from_wbs_code not in wbs:
            raise AppError("WBS_INVALID", f"WBS {from_wbs_code} tidak ada.", status_code=422)
        from_wbs_id = wbs[from_wbs_code].id
    if revenue_change is not None and revenue_change <= 0:
        revenue_change = None
    total = project.budget_total
    increase_pct = (
        (amount / total * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if source == "budget_increase" and total > 0
        else Decimal(0)
    )
    bcr = BudgetChangeRequest(
        number=await numbering.next(session, "BCR"),
        project_id=project.id,
        wbs_id=wbs[wbs_code].id,
        cost_element_code=cost_element_code,
        amount=amount,
        source=source,
        from_wbs_id=from_wbs_id,
        from_cost_element_code=from_cost_element_code
        if source == "transfer"
        else (projects.CONTINGENCY if source == "contingency_release" else None),
        reason=reason,
        justification=justification.strip(),
        revenue_change=revenue_change,
        increase_pct=increase_pct,
        ref_doc_type=ref_doc_type,
        ref_doc_id=ref_doc_id,
        status="submitted",
        created_by=actor.id,
        is_demo=project.is_demo,
    )
    session.add(bcr)
    await session.flush()
    await _validate_source(session, bcr, lock=False)
    if bcr.source == "contingency_release" and bcr.from_wbs_id is None:
        row = await _contingency_line(session, project.id, None, lock=False)
        assert row is not None
        bcr.from_wbs_id = row.wbs_id
    request = await engine.submit(
        session,
        actor,
        doc_type="bcr",
        doc_id=bcr.id,
        doc_number=bcr.number,
        title=f"{SOURCE_LABELS[source]} {project.number} {wbs_code}/{cost_element_code}",
        amount=amount,
        context={
            "source": source,
            "increase_pct": str(increase_pct),
            "revenue_change": revenue_change is not None,
            "project": project.number,
            "reason": reason,
        },
        project_id=project.id,
    )
    bcr.request_id = request.id
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="project",
        entity_id=project.id,
        actor_id=actor.id,
        after={
            "bcr": bcr.number,
            "source": source,
            "line": f"{wbs_code}/{cost_element_code}",
            "amount": amount,
            "increase_pct": increase_pct,
            "revenue_change": revenue_change,
        },
    )
    return bcr


async def _snapshot_version(
    session: AsyncSession,
    project: Project,
    *,
    kind: str,
    request: ApprovalRequest,
    by: uuid.UUID | None,
    note: str,
    bcr_id: uuid.UUID,
) -> BudgetVersion:
    lines = await projects.budget_of(session, project.id)
    wbs = {w.id: w for w in await projects.wbs_of(session, project.id)}
    t = budget_service.totals(project.revenue, lines)
    number = (
        await session.execute(
            select(func.coalesce(func.max(BudgetVersion.version), -1)).where(
                BudgetVersion.project_id == project.id
            )
        )
    ).scalar_one() + 1
    version = BudgetVersion(
        project_id=project.id,
        version=number,
        kind=kind,
        revenue=t.revenue,
        total_cost=t.total_cost,
        margin_pct=t.margin_pct,
        request_id=request.id,
        approved_at=_now(),
        note=note[:1000],
        bcr_id=bcr_id,
        created_by=by,
        is_demo=project.is_demo,
    )
    session.add(version)
    await session.flush()
    for x in lines:
        session.add(
            BudgetVersionLine(
                version_id=version.id,
                wbs_code=wbs[x.wbs_id].code,
                wbs_name=wbs[x.wbs_id].name,
                cost_element_code=x.cost_element_code,
                amount=x.amount,
                locked_reserve=x.locked_reserve,
            )
        )
    await session.flush()
    return version


def _decider(request: ApprovalRequest) -> tuple[uuid.UUID | None, str | None]:
    acted = [s for s in request.steps if s.acted_by]
    if not acted:
        return None, None
    last = max(acted, key=lambda s: s.acted_at or _now())
    return last.acted_by, last.comment


async def _before_approve(
    session: AsyncSession, request: ApprovalRequest, step: Any, principal: Principal
) -> None:
    """The source may have been used since submission: re-check before the approver acts."""
    bcr = await session.get(BudgetChangeRequest, uuid.UUID(request.doc_id))
    assert bcr is not None
    await _validate_source(session, bcr, lock=True)


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    bcr = await session.get(BudgetChangeRequest, uuid.UUID(request.doc_id), with_for_update=True)
    assert bcr is not None
    project = await session.get(Project, bcr.project_id, with_for_update=True)
    assert project is not None
    who, comment = _decider(request)
    source = await _validate_source(session, bcr, lock=True)
    if source is not None:
        source.amount -= bcr.amount
    target = await _line_row(session, bcr.project_id, bcr.wbs_id, bcr.cost_element_code, True)
    if target is None:
        target = ProjectBudgetLine(
            project_id=bcr.project_id,
            version=0,
            wbs_id=bcr.wbs_id,
            cost_element_code=bcr.cost_element_code,
            amount=Decimal(0),
            source="bcr",
            locked_reserve=False,
        )
        session.add(target)
    target.amount += bcr.amount
    await session.flush()
    before = {"budget_total": project.budget_total, "revenue": project.revenue}
    project.budget_total = sum(
        (x.amount for x in await projects.budget_of(session, project.id)), Decimal(0)
    )
    if bcr.revenue_change:
        project.revenue += bcr.revenue_change
    wbs = await session.get(ProjectWbs, bcr.wbs_id)
    assert wbs is not None
    note = (
        f"{bcr.number}: {SOURCE_LABELS[bcr.source]} {_rp(bcr.amount)} ke "
        f"{wbs.code}/{bcr.cost_element_code}. {bcr.justification}"
    )
    version = await _snapshot_version(
        session, project, kind="bcr", request=request, by=who, note=note, bcr_id=bcr.id
    )
    bcr.status, bcr.decided_at, bcr.decision_comment = "approved", _now(), comment
    bcr.version = version.version
    await session.flush()
    await audit.record(
        session,
        action="bcr_approved",
        entity_type="project",
        entity_id=project.id,
        actor_id=who,
        before=before,
        after={
            "bcr": bcr.number,
            "version": version.version,
            "budget_total": project.budget_total,
            "revenue": project.revenue,
        },
    )
    ref = BcrRef(
        project.id, bcr.wbs_id, bcr.cost_element_code, bcr.ref_doc_type, bcr.ref_doc_id, bcr.id
    )
    for listener in _listeners:
        await listener(session, ref)


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    bcr = await session.get(BudgetChangeRequest, uuid.UUID(request.doc_id), with_for_update=True)
    assert bcr is not None
    _, comment = _decider(request)
    bcr.status = "cancelled" if request.status == "cancelled" else "rejected"
    bcr.decided_at, bcr.decision_comment = _now(), comment
    await session.flush()


engine.register_document(
    "bcr", on_approved=_on_approved, on_rejected=_on_rejected, before_approve=_before_approve
)


async def versions(session: AsyncSession, project_id: uuid.UUID) -> list[BudgetVersion]:
    rows = await session.execute(
        select(BudgetVersion)
        .where(BudgetVersion.project_id == project_id)
        .order_by(BudgetVersion.version)
    )
    return list(rows.scalars())


async def version_lines(session: AsyncSession, version_id: uuid.UUID) -> list[BudgetVersionLine]:
    rows = await session.execute(
        select(BudgetVersionLine).where(BudgetVersionLine.version_id == version_id)
    )
    return list(rows.scalars())
