import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import CurrentUser, Principal, require, scope_filter
from app.contract.models import Contract
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.master.models import CostElement
from app.project import budget_service as budget
from app.project import service
from app.project.models import PROJECT_STATUSES, BudgetVersionLine, Project
from app.services import audit, budget_control
from app.services.audit import AuditAction
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta

router = APIRouter(prefix="/projects", tags=["project"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("project", "view"))]
Exporter = Annotated[Principal, Depends(require("project", "export"))]

STATUS_LABELS = {
    "draft": "Draf",
    "controller_review": "Review controller",
    "awaiting_approval": "Menunggu persetujuan",
    "locked": "Terkunci",
    "closed": "Ditutup",
}


def may(principal: Principal, action: str, p: Project) -> bool:
    scope = principal.scope_for("project", action)
    if scope is None:
        return False
    if scope == Scope.ALL:
        return True
    if scope == Scope.PROJECT and p.id in principal.project_ids:
        return True
    return principal.id in (p.owner_id, p.manager_id)


async def _check(
    session: AsyncSession, principal: Principal, entity_id: str, mode: access.Mode
) -> bool:
    try:
        p = await session.get(Project, uuid.UUID(entity_id))
    except ValueError:
        return False
    if p is None:
        return False
    # Documents: anyone who may view the project may read; editors (phase 03) may write.
    return may(principal, "view" if mode == "read" else "edit", p)


access.register("project", _check)


def _query(principal: Principal, action: str, q: str | None, status: str | None) -> Select[Any]:
    stmt = select(Project).where(
        scope_filter(
            principal,
            "project",
            action,
            owner_col=Project.owner_id,
            project_col=Project.id,
        )
        | (Project.manager_id == principal.id)
    )
    if status:
        stmt = stmt.where(Project.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Project.number.ilike(like),
                Project.name.ilike(like),
                Project.company_name.ilike(like),
            )
        )
    return stmt


async def _rows(session: AsyncSession, items: list[Project]) -> list[dict[str, Any]]:
    contracts = {}
    ids = [p.contract_id for p in items if p.contract_id]
    if ids:
        contracts = dict(
            (
                await session.execute(
                    select(Contract.id, Contract.number).where(Contract.id.in_(ids))
                )
            )
            .tuples()
            .all()
        )
    return [
        {
            "id": str(p.id),
            "number": p.number,
            "name": p.name,
            "company_name": p.company_name,
            "status": p.status,
            "revenue": format(p.revenue, "f"),
            "budget_total": format(p.budget_total, "f"),
            "planned_margin": format(p.revenue - p.budget_total, "f"),
            "contract_id": str(p.contract_id) if p.contract_id else None,
            "contract_number": contracts.get(p.contract_id) if p.contract_id else None,
            "start_date": p.start_date.isoformat() if p.start_date else None,
            "end_date": p.end_date.isoformat() if p.end_date else None,
            "created_at": p.created_at.isoformat(),
            "is_demo": p.is_demo,
        }
        for p in items
    ]


@router.get("")
async def list_projects(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    q: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    base = _query(principal, "view", q, None).subquery()
    counts = dict.fromkeys(PROJECT_STATUSES, 0)
    counts.update(
        dict(
            (await session.execute(select(base.c.status, func.count()).group_by(base.c.status)))
            .tuples()
            .all()
        )
    )
    stmt = _query(principal, "view", q, status)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    items = (
        await session.execute(
            stmt.order_by(Project.created_at.desc()).offset(paging.offset).limit(paging.page_size)
        )
    ).scalars()
    return {
        "items": await _rows(session, list(items)),
        "total": total,
        "counts": counts,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/export")
async def export(
    principal: Exporter, session: Session, q: str | None = None, status: str | None = None
) -> StreamingResponse:
    stmt = _query(principal, "export", q, status).order_by(Project.number)
    rows = await _rows(session, list((await session.execute(stmt)).scalars()))
    columns = [
        Column("Nomor", "number", width=14),
        Column("Nama", "name", width=36),
        Column("Klien", "company_name", width=30),
        Column("Status", "status_label", width=18),
        Column("Kontrak", "contract_number", width=14),
        Column("Pendapatan", "revenue", "idr"),
        Column("Anggaran", "budget_total", "idr"),
        Column("Margin rencana", "planned_margin", "idr"),
    ]
    return xlsx_response(
        f"proyek-{today_jakarta():%Y%m%d}.xlsx",
        "Proyek",
        columns,
        ({**r, "status_label": STATUS_LABELS.get(r["status"], r["status"])} for r in rows),
    )


def may_budget(principal: Principal, action: str, p: Project) -> bool:
    """Budget rights (module `budget`): all, or the project's planner/assignment."""
    scope = principal.scope_for("budget", action)
    if scope is None:
        return False
    if scope == Scope.ALL:
        return True
    if p.id in principal.project_ids:
        return True
    return principal.id == p.manager_id


async def _get(
    session: AsyncSession, principal: Principal, pid: uuid.UUID, lock: bool = False
) -> Project:
    p = await session.get(Project, pid, with_for_update=lock)
    if p is None or not (may(principal, "view", p) or may_budget(principal, "view", p)):
        raise NotFoundError("NOT_FOUND", "Proyek tidak ditemukan atau Anda tidak berizin.")
    return p


async def _detail(session: AsyncSession, principal: Principal, p: Project) -> dict[str, Any]:
    names = dict((await session.execute(select(CostElement.code, CostElement.name))).tuples().all())
    lines = await service.budget_of(session, p.id)
    wbs = await service.wbs_of(session, p.id)
    codes = {w.id: w.code for w in wbs}
    t = budget.totals(p.revenue, lines)
    threshold = await budget.min_margin_pct(session)
    base = await budget.baseline(session, p.id)
    manager = (
        (
            await session.execute(select(User.full_name).where(User.id == p.manager_id))
        ).scalar_one_or_none()
        if p.manager_id
        else None
    )
    per_element: dict[str, Decimal] = {}
    for x in lines:
        per_element[x.cost_element_code] = (
            per_element.get(x.cost_element_code, Decimal(0)) + x.amount
        )
    revenue = p.revenue
    return {
        **(await _rows(session, [p]))[0],
        "contingency_pct": format(p.contingency_pct, "f"),
        "status_label": STATUS_LABELS.get(p.status, p.status),
        "total_cost": format(t.total_cost, "f"),
        "margin_pct": str(t.margin_pct),
        "min_margin_pct": str(threshold),
        "margin_warning": t.margin_pct < threshold,
        "manager_id": str(p.manager_id) if p.manager_id else None,
        "manager_name": manager,
        "budget_request_id": str(p.budget_request_id) if p.budget_request_id else None,
        "budget_comment": p.budget_comment,
        "locked_at": p.locked_at.isoformat() if p.locked_at else None,
        "baseline": {
            "version": base.version,
            "total_cost": format(base.total_cost, "f"),
            "margin_pct": str(base.margin_pct),
            "approved_at": base.approved_at.isoformat(),
        }
        if base
        else None,
        "can_edit_budget": p.status == "draft" and may_budget(principal, "edit", p),
        "can_submit_budget": p.status == "draft" and may_budget(principal, "submit", p),
        "can_assign": may(principal, "edit", p) and p.status not in ("closed",),
        "wbs": [{"id": str(w.id), "code": w.code, "name": w.name} for w in wbs],
        "cells": [
            {
                "wbs_code": codes[x.wbs_id],
                "cost_element_code": x.cost_element_code,
                "amount": format(x.amount, "f"),
                "locked_reserve": x.locked_reserve,
                "source": x.source,
            }
            for x in lines
        ],
        "cost_elements": [{"code": c, "name": n} for c, n in sorted(names.items())],
        "budget": [
            {
                "cost_element_code": code,
                "cost_element_name": names.get(code, code),
                "amount": format(amount, "f"),
                "source": "contingency" if code == service.CONTINGENCY else "quotation",
                "share_of_revenue": str((amount / revenue * 100).quantize(Decimal("0.1")))
                if revenue > 0
                else None,
            }
            for code, amount in sorted(per_element.items())
        ],
    }


@router.get("/planners")
async def planners(_: Viewer, session: Session) -> list[dict[str, str]]:
    """Active users whose roles may edit budgets (candidates for project planner)."""
    from app.auth.models import Role, RolePermission, UserRole

    rows = await session.execute(
        select(User.id, User.full_name)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .where(
            User.is_active.is_(True),
            UserRole.active_now(),
            RolePermission.module == "budget",
            RolePermission.action == "edit",
            Role.code != "super_admin",
        )
        .distinct()
        .order_by(User.full_name)
    )
    return [{"id": str(i), "full_name": n} for i, n in rows.tuples()]


@router.get("/{pid}")
async def get_project(pid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _detail(session, principal, await _get(session, principal, pid))


def _need_budget(principal: Principal, action: str, p: Project) -> None:
    if not may_budget(principal, action, p):
        raise ForbiddenError(
            "PERMISSION_DENIED", "Anda tidak berizin mengubah anggaran proyek ini."
        )


class CellBody(BaseModel):
    wbs_code: str = Field(min_length=1, max_length=20)
    cost_element_code: str = Field(min_length=1, max_length=20)
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=0)


class BudgetBody(BaseModel):
    cells: list[CellBody] = Field(max_length=500)


@router.put("/{pid}/budget")
async def save_budget(
    pid: uuid.UUID, body: BudgetBody, principal: CurrentUser, session: Session
) -> dict[str, Any]:
    p = await _get(session, principal, pid, lock=True)
    _need_budget(principal, "edit", p)
    await budget.save_budget(
        session,
        principal,
        p,
        [
            budget.CellIn(c.wbs_code.strip().upper(), c.cost_element_code, c.amount)
            for c in body.cells
        ],
    )
    await session.commit()
    return await _detail(session, principal, p)


class WbsBody(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=2, max_length=120)


@router.post("/{pid}/wbs", status_code=201)
async def add_wbs(
    pid: uuid.UUID, body: WbsBody, principal: CurrentUser, session: Session
) -> dict[str, Any]:
    p = await _get(session, principal, pid, lock=True)
    _need_budget(principal, "edit", p)
    await budget.add_wbs(session, principal, p, body.code, body.name)
    await session.commit()
    return await _detail(session, principal, p)


@router.delete("/{pid}/wbs/{wid}")
async def delete_wbs(
    pid: uuid.UUID, wid: uuid.UUID, principal: CurrentUser, session: Session
) -> dict[str, Any]:
    p = await _get(session, principal, pid, lock=True)
    _need_budget(principal, "edit", p)
    await budget.delete_wbs(session, principal, p, wid)
    await session.commit()
    return await _detail(session, principal, p)


@router.post("/{pid}/submit-budget")
async def submit_budget(pid: uuid.UUID, principal: CurrentUser, session: Session) -> dict[str, Any]:
    p = await _get(session, principal, pid, lock=True)
    _need_budget(principal, "submit", p)
    request = await budget.submit(session, principal, p)
    await session.commit()
    return {
        **(await _detail(session, principal, p)),
        "approvers": [s.approver_role for s in sorted(request.steps, key=lambda s: s.seq)],
    }


class ManagerBody(BaseModel):
    manager_id: uuid.UUID | None


@router.put("/{pid}/manager")
async def set_manager(
    pid: uuid.UUID, body: ManagerBody, principal: CurrentUser, session: Session
) -> dict[str, Any]:
    """Head of Operation assigns the planner (project-scoped users work on assigned projects)."""
    p = await _get(session, principal, pid, lock=True)
    if not may(principal, "edit", p):
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin menugaskan proyek ini.")
    if body.manager_id is not None:
        user = await session.get(User, body.manager_id)
        if user is None or not user.is_active:
            raise AppError(
                "USER_INVALID", "Pengguna tidak ditemukan atau tidak aktif.", status_code=422
            )
    before = p.manager_id
    p.manager_id = body.manager_id
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="project",
        entity_id=p.id,
        actor_id=principal.id,
        before={"manager_id": before},
        after={"manager_id": p.manager_id},
    )
    await session.commit()
    return await _detail(session, principal, p)


@router.get("/{pid}/budget-status")
async def budget_status(pid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    """Budget, pre-commitment, commitment, actual and available per line."""
    p = await _get(session, principal, pid)
    names = dict((await session.execute(select(CostElement.code, CostElement.name))).tuples().all())
    rows = []
    total = dict.fromkeys(("budget", "pre_commit", "commit", "actual", "available"), Decimal(0))
    for line, wbs_code, b in await budget_control.project_status(session, p.id):
        for k in total:
            total[k] += getattr(b, k)
        rows.append(
            {
                "wbs_code": wbs_code,
                "cost_element_code": line.cost_element_code,
                "cost_element_name": names.get(line.cost_element_code, line.cost_element_code),
                "locked_reserve": line.cost_element_code == service.CONTINGENCY,
                "budget": format(b.budget, "f"),
                "pre_commit": format(b.pre_commit, "f"),
                "commit": format(b.commit, "f"),
                "actual": format(b.actual, "f"),
                "available": format(b.available, "f"),
                "used_pct": str(b.used_pct),
                "state": "exhausted"
                if b.available <= 0 and b.budget > 0
                else "warning"
                if b.used_pct >= budget_control.WARN_PCT
                else "ok",
            }
        )
    return {
        "status": p.status,
        "lines": rows,
        "totals": {k: format(v, "f") for k, v in total.items()},
    }


@router.get("/{pid}/baseline")
async def get_baseline(pid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    p = await _get(session, principal, pid)
    base = await budget.baseline(session, p.id)
    if base is None:
        raise NotFoundError("NO_BASELINE", "Proyek belum punya baseline (belum terkunci).")
    lines = (
        await session.execute(
            select(BudgetVersionLine).where(BudgetVersionLine.version_id == base.id)
        )
    ).scalars()
    return {
        "version": base.version,
        "kind": base.kind,
        "revenue": format(base.revenue, "f"),
        "total_cost": format(base.total_cost, "f"),
        "margin_pct": str(base.margin_pct),
        "approved_at": base.approved_at.isoformat(),
        "lines": [
            {
                "wbs_code": x.wbs_code,
                "wbs_name": x.wbs_name,
                "cost_element_code": x.cost_element_code,
                "amount": format(x.amount, "f"),
                "locked_reserve": x.locked_reserve,
            }
            for x in lines
        ],
    }
