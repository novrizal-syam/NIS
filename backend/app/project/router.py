import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Scope
from app.auth.principal import Principal, require, scope_filter
from app.contract.models import Contract
from app.core import access
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.core.pagination import PageParams, page_params
from app.master.models import CostElement
from app.project import service
from app.project.models import PROJECT_STATUSES, Project
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


@router.get("/{pid}")
async def get_project(pid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    p = await session.get(Project, pid)
    if p is None or not may(principal, "view", p):
        raise NotFoundError("NOT_FOUND", "Proyek tidak ditemukan atau Anda tidak berizin.")
    names = dict((await session.execute(select(CostElement.code, CostElement.name))).tuples().all())
    lines = await service.budget_of(session, p.id)
    revenue = p.revenue
    return {
        **(await _rows(session, [p]))[0],
        "contingency_pct": format(p.contingency_pct, "f"),
        "budget": [
            {
                "cost_element_code": x.cost_element_code,
                "cost_element_name": names.get(x.cost_element_code, x.cost_element_code),
                "amount": format(x.amount, "f"),
                "source": x.source,
                "share_of_revenue": str((x.amount / revenue * 100).quantize(Decimal("0.1")))
                if revenue > 0
                else None,
            }
            for x in lines
        ],
    }
