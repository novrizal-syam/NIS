"""Budget edit, Controller review, approval and baseline lock (PROCESS.md · Project & budget;
DOA.md · project_budget). Status machine:

    draft -> controller_review (submitted; step 1 Lead Controller)
          -> awaiting_approval (step 2: <= Rp 2 M Head of Operation, > Rp 2 M Director)
          -> locked (baseline v0 in budget_versions)
    reject / withdraw at any step -> draft
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.master.models import CostElement
from app.project import service as projects
from app.project.models import (
    BudgetVersion,
    BudgetVersionLine,
    Project,
    ProjectBudgetLine,
    ProjectWbs,
)
from app.services import audit
from app.services.audit import AuditAction
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest, ApprovalStep

MIN_MARGIN = "project.min_margin_pct"
DEFAULT_MIN_MARGIN = 20
TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"controller_review"}),
    "controller_review": frozenset({"awaiting_approval", "draft"}),
    "awaiting_approval": frozenset({"locked", "draft"}),
    "locked": frozenset({"closed"}),
    "closed": frozenset(),
}
STATUS_LABELS = {
    "draft": "Draf",
    "controller_review": "Review controller",
    "awaiting_approval": "Menunggu persetujuan",
    "locked": "Terkunci",
    "closed": "Ditutup",
}


def _now() -> datetime:
    return datetime.now(UTC)


async def min_margin_pct(session: AsyncSession) -> Decimal:
    return Decimal(str(await settings_store.get(session, MIN_MARGIN, DEFAULT_MIN_MARGIN)))


@dataclass(frozen=True)
class Totals:
    revenue: Decimal
    total_cost: Decimal
    margin: Decimal
    margin_pct: Decimal


def totals(revenue: Decimal, lines: list[ProjectBudgetLine]) -> Totals:
    cost = sum((x.amount for x in lines), Decimal(0))
    margin = revenue - cost
    pct = (
        (margin / revenue * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if revenue > 0
        else Decimal("0.00")
    )
    return Totals(revenue, cost, margin, pct)


async def _transition(
    session: AsyncSession, project: Project, to: str, actor_id: uuid.UUID | None, note: str | None
) -> None:
    if to not in TRANSITIONS.get(project.status, frozenset()):
        raise ConflictError(
            "ILLEGAL_TRANSITION",
            f"Status proyek tidak dapat berubah dari {STATUS_LABELS[project.status]} "
            f"ke {STATUS_LABELS.get(to, to)}.",
        )
    before = project.status
    project.status = to
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type="project",
        entity_id=project.id,
        actor_id=actor_id,
        before={"status": before},
        after={"status": to},
        note=note,
    )


def ensure_editable(project: Project) -> None:
    if project.status != "draft":
        raise ConflictError(
            "BUDGET_LOCKED",
            f"Anggaran {project.number} hanya dapat diubah saat Draf "
            f"(sekarang {STATUS_LABELS[project.status]}). Setelah terkunci gunakan BCR.",
        )


# ---------------------------------------------------------------- WBS


async def add_wbs(
    session: AsyncSession, actor: Principal, project: Project, code: str, name: str
) -> ProjectWbs:
    ensure_editable(project)
    code = code.strip().upper()
    existing = await projects.wbs_of(session, project.id)
    if any(w.code == code for w in existing):
        raise ConflictError("WBS_EXISTS", f"WBS {code} sudah ada.")
    wbs = ProjectWbs(
        project_id=project.id,
        code=code,
        name=name.strip(),
        seq=max((w.seq for w in existing), default=0) + 1,
    )
    session.add(wbs)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="project",
        entity_id=project.id,
        actor_id=actor.id,
        after={"wbs": code, "name": wbs.name},
    )
    return wbs


async def delete_wbs(
    session: AsyncSession, actor: Principal, project: Project, wbs_id: uuid.UUID
) -> None:
    ensure_editable(project)
    wbs = await session.get(ProjectWbs, wbs_id)
    if wbs is None or wbs.project_id != project.id:
        raise AppError("NOT_FOUND", "WBS tidak ditemukan.", status_code=404)
    if wbs.code == projects.DEFAULT_WBS[0]:
        raise ConflictError("WBS_DEFAULT", "WBS Execution tidak dapat dihapus.")
    used = (
        await session.execute(
            select(ProjectBudgetLine.id).where(
                ProjectBudgetLine.wbs_id == wbs.id, ProjectBudgetLine.amount > 0
            )
        )
    ).first()
    if used:
        raise ConflictError("WBS_HAS_BUDGET", f"WBS {wbs.code} masih punya anggaran.")
    await session.execute(delete(ProjectBudgetLine).where(ProjectBudgetLine.wbs_id == wbs.id))
    await session.delete(wbs)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.DELETE,
        entity_type="project",
        entity_id=project.id,
        actor_id=actor.id,
        before={"wbs": wbs.code},
    )


# ---------------------------------------------------------------- editor


@dataclass(frozen=True)
class CellIn:
    wbs_code: str
    cost_element_code: str
    amount: Decimal


def _snapshot(lines: list[ProjectBudgetLine], wbs: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {f"{wbs[x.wbs_id]}/{x.cost_element_code}": x.amount for x in lines}


async def save_budget(
    session: AsyncSession, actor: Principal, project: Project, cells: list[CellIn]
) -> list[ProjectBudgetLine]:
    """Replace the draft budget (cost element x WBS). Zero cells are dropped."""
    ensure_editable(project)
    wbs = {w.code: w for w in await projects.wbs_of(session, project.id)}
    elements = set((await session.execute(select(CostElement.code))).scalars())
    seen: set[tuple[str, str]] = set()
    for c in cells:
        if c.wbs_code not in wbs:
            raise AppError("WBS_INVALID", f"WBS {c.wbs_code} tidak ada.", status_code=422)
        if c.cost_element_code not in elements:
            raise AppError(
                "COST_ELEMENT_INVALID",
                f"Elemen biaya {c.cost_element_code} tidak valid.",
                status_code=422,
            )
        if c.amount < 0 or c.amount != c.amount.to_integral_value():
            raise AppError(
                "AMOUNT_INVALID",
                "Nilai anggaran harus rupiah bulat, tidak negatif.",
                status_code=422,
            )
        key = (c.wbs_code, c.cost_element_code)
        if key in seen:
            raise AppError(
                "DUPLICATE_CELL",
                f"Baris {c.wbs_code} / {c.cost_element_code} muncul dua kali.",
                status_code=422,
            )
        seen.add(key)
    by_id = {w.id: w.code for w in wbs.values()}
    old = await projects.budget_of(session, project.id)
    before = _snapshot(old, by_id)
    sources = {(by_id[x.wbs_id], x.cost_element_code): x.source for x in old}
    await session.execute(
        delete(ProjectBudgetLine).where(ProjectBudgetLine.project_id == project.id)
    )
    new = []
    for c in cells:
        if c.amount == 0:
            continue
        reserve = c.cost_element_code == projects.CONTINGENCY
        line = ProjectBudgetLine(
            project_id=project.id,
            version=0,
            wbs_id=wbs[c.wbs_code].id,
            cost_element_code=c.cost_element_code,
            amount=c.amount,
            source="contingency"
            if reserve
            else sources.get((c.wbs_code, c.cost_element_code), "manual"),
            locked_reserve=reserve,
        )
        session.add(line)
        new.append(line)
    await session.flush()
    project.budget_total = sum((x.amount for x in new), Decimal(0))
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="project",
        entity_id=project.id,
        actor_id=actor.id,
        before={"budget": before},
        after={"budget": _snapshot(new, by_id), "total": project.budget_total},
    )
    return new


# ---------------------------------------------------------------- DOA


async def submit(session: AsyncSession, actor: Principal, project: Project) -> ApprovalRequest:
    ensure_editable(project)
    lines = await projects.budget_of(session, project.id)
    t = totals(project.revenue, lines)
    if t.total_cost <= 0:
        raise AppError("BUDGET_EMPTY", "Anggaran masih kosong.", status_code=422)
    request = await engine.submit(
        session,
        actor,
        doc_type="project_budget",
        doc_id=project.id,
        doc_number=project.number,
        title=f"Anggaran {project.name} ({project.company_name}) · margin {t.margin_pct}%",
        amount=t.total_cost,
        context={
            "total_cost": str(t.total_cost),
            "revenue": str(t.revenue),
            "margin_pct": str(t.margin_pct),
        },
        project_id=project.id,
    )
    project.budget_request_id, project.budget_comment = request.id, None
    await _transition(session, project, "controller_review", actor.id, None)
    return request


async def _check_margin(
    session: AsyncSession, request: ApprovalRequest, step: ApprovalStep, _: Principal
) -> None:
    """Step 1 (Lead Controller) cannot approve a budget below the margin threshold."""
    if step.approver_role != "lead_controller":
        return
    project = await session.get(Project, uuid.UUID(request.doc_id))
    assert project is not None
    t = totals(project.revenue, await projects.budget_of(session, project.id))
    threshold = await min_margin_pct(session)
    if t.margin_pct < threshold:
        raise AppError(
            "MARGIN_BELOW_THRESHOLD",
            f"Margin rencana {t.margin_pct}% di bawah batas {threshold}%. "
            "Tolak dengan catatan agar anggaran diperbaiki.",
            status_code=422,
        )


def _decider(request: ApprovalRequest) -> tuple[uuid.UUID | None, str | None]:
    acted = [s for s in request.steps if s.acted_by]
    if not acted:
        return None, None
    last = max(acted, key=lambda s: s.acted_at or _now())
    return last.acted_by, last.comment


async def _on_step(session: AsyncSession, request: ApprovalRequest) -> None:
    project = await session.get(Project, uuid.UUID(request.doc_id), with_for_update=True)
    assert project is not None
    who, _ = _decider(request)
    await _transition(session, project, "awaiting_approval", who, "Review controller disetujui")


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    project = await session.get(Project, uuid.UUID(request.doc_id), with_for_update=True)
    assert project is not None
    who, _ = _decider(request)
    await _transition(session, project, "locked", who, "Anggaran disetujui; baseline v0")
    project.locked_at = _now()
    lines = await projects.budget_of(session, project.id)
    wbs = {w.id: w for w in await projects.wbs_of(session, project.id)}
    t = totals(project.revenue, lines)
    version = BudgetVersion(
        project_id=project.id,
        version=0,
        kind="baseline",
        revenue=t.revenue,
        total_cost=t.total_cost,
        margin_pct=t.margin_pct,
        request_id=request.id,
        approved_at=project.locked_at,
        created_by=who,
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
    await audit.record(
        session,
        action="budget_baseline",
        entity_type="project",
        entity_id=project.id,
        actor_id=who,
        after={"version": 0, "total_cost": t.total_cost, "margin_pct": t.margin_pct},
    )


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    project = await session.get(Project, uuid.UUID(request.doc_id), with_for_update=True)
    assert project is not None
    who, comment = _decider(request)
    project.budget_comment = comment if request.status == "rejected" else None
    project.budget_request_id = None
    note = "Ditarik pengaju" if request.status == "cancelled" else f"Ditolak: {comment}"
    await _transition(session, project, "draft", who or request.requester_id, note)


engine.register_document(
    "project_budget",
    on_approved=_on_approved,
    on_rejected=_on_rejected,
    on_step_activated=_on_step,
    before_approve=_check_margin,
)


async def baseline(session: AsyncSession, project_id: uuid.UUID) -> BudgetVersion | None:
    return (
        await session.execute(
            select(BudgetVersion).where(
                BudgetVersion.project_id == project_id, BudgetVersion.version == 0
            )
        )
    ).scalar_one_or_none()
