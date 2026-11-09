"""QHSE API (05b)."""

import io
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import CurrentUser, Principal, require
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, NotFoundError
from app.project.models import Project
from app.qhse import service as svc
from app.qhse.models import (
    INCIDENT_CATEGORIES,
    PERMIT_TYPES,
    Capa,
    Incident,
    Inspection,
    Observation,
    Permit,
    RiskAssessment,
)
from app.services import audit, numbering
from app.services.audit import AuditAction

router = APIRouter(prefix="/qhse", tags=["qhse"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("qhse", "view"))]
Creator = Annotated[Principal, Depends(require("qhse", "create"))]
Editor = Annotated[Principal, Depends(require("qhse", "edit"))]
Approver = Annotated[Principal, Depends(require("qhse", "approve"))]
Exporter = Annotated[Principal, Depends(require("qhse", "export"))]


def _iso(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def _row(obj: Any, fields: tuple[str, ...], projects: dict[uuid.UUID, str]) -> dict[str, Any]:
    out = {f: _iso(getattr(obj, f)) for f in fields}
    out["id"] = str(obj.id)
    if hasattr(obj, "project_id"):
        out["project_number"] = projects.get(obj.project_id) if obj.project_id else None
    return out


async def _projects(session: AsyncSession) -> dict[uuid.UUID, str]:
    return dict((await session.execute(select(Project.id, Project.number))).tuples().all())


def _scoped(principal: Principal, model: Any, stmt: Any) -> Any:
    if principal.scope_for("qhse", "view") == Scope.ALL:
        return stmt
    ids = principal.project_ids or {uuid.uuid4()}
    return stmt.where(or_(model.created_by == principal.id, model.project_id.in_(ids)))


async def _project(
    session: AsyncSession, principal: Principal, pid: uuid.UUID | None
) -> Project | None:
    if pid is None:
        return None
    p = await session.get(Project, pid)
    if p is None:
        raise NotFoundError("NOT_FOUND", "Proyek tidak ditemukan.")
    if principal.scope_for("qhse", "create") != Scope.ALL and p.id not in principal.project_ids:
        raise NotFoundError(
            "NOT_FOUND", "Proyek tidak ditemukan atau Anda bukan anggota tim proyek."
        )
    return p


async def _get(session: AsyncSession, model: Any, rid: uuid.UUID, lock: bool = False) -> Any:
    obj = await session.get(model, rid, with_for_update=lock)
    if obj is None:
        raise NotFoundError("NOT_FOUND", "Data QHSE tidak ditemukan.")
    return obj


async def _qhse_access(
    session: AsyncSession, principal: Principal, eid: str, mode: access.Mode
) -> bool:
    return principal.can("qhse", "view" if mode == "read" else "create")


for _t in ("risk_assessment", "permit", "inspection", "observation", "incident"):
    access.register(_t, _qhse_access)


@router.get("/projects")
async def projects(principal: Viewer, session: Session) -> list[dict[str, str]]:
    stmt = (
        select(Project)
        .where(Project.status.in_(("locked", "awaiting_approval", "draft")))
        .order_by(Project.number)
    )
    if principal.scope_for("qhse", "view") != Scope.ALL:
        stmt = stmt.where(Project.id.in_(principal.project_ids or {uuid.uuid4()}))
    return [
        {"id": str(p.id), "number": p.number, "name": p.name}
        for p in (await session.execute(stmt)).scalars()
    ]


@router.get("/users")
async def users(_: Viewer, session: Session) -> list[dict[str, str]]:
    rows = await session.execute(
        select(User.id, User.full_name).where(User.is_active.is_(True)).order_by(User.full_name)
    )
    return [{"id": str(i), "full_name": n} for i, n in rows.tuples()]


# ---------------------------------------------------------------- HIRADC / JSA

RA_FIELDS = ("number", "kind", "title", "status", "hazards", "approved_at", "created_at")


class AssessmentBody(BaseModel):
    project_id: uuid.UUID
    kind: str = Field(pattern="^(hiradc|jsa)$")
    title: str = Field(min_length=3, max_length=200)
    hazards: list[dict[str, Any]] = Field(min_length=1, max_length=200)


@router.get("/risk-assessments")
async def list_ra(
    principal: Viewer, session: Session, project_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    stmt = _scoped(
        principal, RiskAssessment, select(RiskAssessment).order_by(RiskAssessment.created_at.desc())
    )
    if project_id:
        stmt = stmt.where(RiskAssessment.project_id == project_id)
    pj = await _projects(session)
    return [
        {
            **_row(r, RA_FIELDS, pj),
            "can_approve": r.status == "draft"
            and principal.can("qhse", "approve")
            and r.created_by != principal.id,
        }
        for r in (await session.execute(stmt)).scalars()
    ]


@router.post("/risk-assessments", status_code=201)
async def create_ra(body: AssessmentBody, actor: Creator, session: Session) -> dict[str, Any]:
    p = await _project(session, actor, body.project_id)
    assert p is not None
    ra = await svc.create_assessment(session, actor, p, body.kind, body.title, body.hazards)
    await session.commit()
    return _row(ra, RA_FIELDS, await _projects(session))


@router.post("/risk-assessments/{rid}/approve")
async def approve_ra(rid: uuid.UUID, actor: Approver, session: Session) -> dict[str, Any]:
    ra = await _get(session, RiskAssessment, rid, lock=True)
    await svc.approve_assessment(session, actor, ra)
    await session.commit()
    return _row(ra, RA_FIELDS, await _projects(session))


# ---------------------------------------------------------------- permits

PERMIT_FIELDS = (
    "number", "permit_type", "location", "work_description", "precautions", "valid_from",
    "valid_to", "status", "approved_at", "closed_at",
)  # fmt: skip


class PermitBody(BaseModel):
    project_id: uuid.UUID
    permit_type: str
    location: str = Field(min_length=2, max_length=200)
    work_description: str = Field(min_length=5, max_length=2000)
    precautions: list[str] = Field(default_factory=list, max_length=40)
    valid_from: datetime
    valid_to: datetime


@router.get("/permits")
async def list_permits(
    principal: Viewer, session: Session, status: str | None = None
) -> list[dict[str, Any]]:
    stmt = _scoped(principal, Permit, select(Permit).order_by(Permit.valid_from.desc()).limit(200))
    if status:
        stmt = stmt.where(Permit.status == status)
    pj = await _projects(session)
    return [
        {**_row(x, PERMIT_FIELDS, pj), "is_own": x.created_by == principal.id}
        for x in (await session.execute(stmt)).scalars()
    ]


@router.post("/permits", status_code=201)
async def create_permit(body: PermitBody, actor: Creator, session: Session) -> dict[str, Any]:
    if body.permit_type not in PERMIT_TYPES:
        raise AppError("TYPE_INVALID", "Jenis izin kerja tidak dikenal.", status_code=422)
    p = await _project(session, actor, body.project_id)
    assert p is not None
    pm = await svc.create_permit(
        session,
        actor,
        p,
        {
            "permit_type": body.permit_type,
            "location": body.location,
            "work_description": body.work_description,
            "precautions": [{"item": x, "done": False} for x in body.precautions if x.strip()],
            "valid_from": body.valid_from,
            "valid_to": body.valid_to,
        },
    )
    await session.commit()
    return _row(pm, PERMIT_FIELDS, await _projects(session))


@router.post("/permits/{pid}/{action}")
async def permit_action(
    pid: uuid.UUID, action: str, actor: CurrentUser, session: Session
) -> dict[str, Any]:
    if action not in ("approve", "close", "cancel"):
        raise NotFoundError("NOT_FOUND", "Aksi tidak dikenal.")
    needed = "approve" if action == "approve" else "edit"
    if not actor.can("qhse", needed) and not (action != "approve" and actor.can("qhse", "create")):
        raise AppError("PERMISSION_DENIED", "Anda tidak berizin.", status_code=403)
    pm = await _get(session, Permit, pid, lock=True)
    await svc.permit_action(session, actor, pm, action)
    await session.commit()
    return _row(pm, PERMIT_FIELDS, await _projects(session))


# ---------------------------------------------------------------- inspections & observations

INSP_FIELDS = ("number", "inspection_type", "inspection_date", "location", "checklist", "findings")
OBS_FIELDS = ("number", "obs_date", "category", "description", "action_taken")


class CapaIn(BaseModel):
    action: str = Field(min_length=5, max_length=2000)
    owner_id: uuid.UUID
    due_date: date


class InspectionBody(BaseModel):
    project_id: uuid.UUID | None = None
    inspection_type: str = Field(min_length=2, max_length=60)
    inspection_date: date
    location: str | None = Field(default=None, max_length=200)
    checklist: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    findings: str | None = Field(default=None, max_length=5000)
    capas: list[CapaIn] = Field(default_factory=list, max_length=20)


class ObservationBody(BaseModel):
    project_id: uuid.UUID | None = None
    obs_date: date
    category: str = Field(pattern="^(unsafe_act|unsafe_condition|good_practice)$")
    description: str = Field(min_length=5, max_length=3000)
    action_taken: str | None = Field(default=None, max_length=3000)
    capas: list[CapaIn] = Field(default_factory=list, max_length=20)


async def _capas(
    session: AsyncSession,
    actor: Principal,
    src: str,
    sid: uuid.UUID,
    pid: uuid.UUID | None,
    items: list[CapaIn],
) -> None:
    for c in items:
        await svc.create_capa(
            session,
            actor,
            source_type=src,
            source_id=sid,
            project_id=pid,
            action=c.action,
            owner_id=c.owner_id,
            due_date=c.due_date,
        )


@router.get("/inspections")
async def list_inspections(principal: Viewer, session: Session) -> list[dict[str, Any]]:
    pj = await _projects(session)
    stmt = _scoped(
        principal,
        Inspection,
        select(Inspection).order_by(Inspection.inspection_date.desc()).limit(200),
    )
    return [_row(x, INSP_FIELDS, pj) for x in (await session.execute(stmt)).scalars()]


@router.post("/inspections", status_code=201)
async def create_inspection(
    body: InspectionBody, actor: Creator, session: Session
) -> dict[str, Any]:
    p = await _project(session, actor, body.project_id)
    if body.inspection_date > numbering.today_jakarta():
        raise AppError(
            "DATE_IN_FUTURE", "Tanggal inspeksi tidak boleh di masa depan.", status_code=422
        )
    x = Inspection(
        number=await numbering.next(session, "INS"),
        project_id=p.id if p else None,
        inspection_type=body.inspection_type,
        inspection_date=body.inspection_date,
        location=body.location,
        checklist=body.checklist,
        findings=body.findings,
        created_by=actor.id,
    )
    session.add(x)
    await session.flush()
    await _capas(session, actor, "inspection", x.id, x.project_id, body.capas)
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="inspection",
        entity_id=x.id,
        actor_id=actor.id,
        after={"number": x.number},
    )
    await session.commit()
    return _row(x, INSP_FIELDS, await _projects(session))


@router.get("/observations")
async def list_observations(principal: Viewer, session: Session) -> list[dict[str, Any]]:
    pj = await _projects(session)
    stmt = _scoped(
        principal, Observation, select(Observation).order_by(Observation.obs_date.desc()).limit(200)
    )
    return [_row(x, OBS_FIELDS, pj) for x in (await session.execute(stmt)).scalars()]


@router.post("/observations", status_code=201)
async def create_observation(
    body: ObservationBody, actor: Creator, session: Session
) -> dict[str, Any]:
    p = await _project(session, actor, body.project_id)
    x = Observation(
        number=await numbering.next(session, "OBS"),
        project_id=p.id if p else None,
        obs_date=body.obs_date,
        category=body.category,
        description=body.description,
        action_taken=body.action_taken,
        created_by=actor.id,
    )
    session.add(x)
    await session.flush()
    await _capas(session, actor, "observation", x.id, x.project_id, body.capas)
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="observation",
        entity_id=x.id,
        actor_id=actor.id,
        after={"number": x.number},
    )
    await session.commit()
    return _row(x, OBS_FIELDS, await _projects(session))


# ---------------------------------------------------------------- incidents

INC_FIELDS = (
    "number", "occurred_on", "category", "location", "description", "lost_days", "status",
    "root_cause", "investigation", "closed_at",
)  # fmt: skip


class IncidentBody(BaseModel):
    project_id: uuid.UUID | None = None
    occurred_on: date
    category: str
    location: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=5, max_length=5000)
    lost_days: int = Field(default=0, ge=0, le=10_000)


class InvestigationBody(BaseModel):
    root_cause: str | None = Field(default=None, max_length=5000)
    investigation: str | None = Field(default=None, max_length=10_000)
    lost_days: int | None = Field(default=None, ge=0, le=10_000)
    close: bool = False
    capas: list[CapaIn] = Field(default_factory=list, max_length=20)


@router.get("/incidents")
async def list_incidents(principal: Viewer, session: Session) -> list[dict[str, Any]]:
    pj = await _projects(session)
    stmt = _scoped(
        principal, Incident, select(Incident).order_by(Incident.occurred_on.desc()).limit(200)
    )
    return [_row(x, INC_FIELDS, pj) for x in (await session.execute(stmt)).scalars()]


@router.post("/incidents", status_code=201)
async def create_incident(body: IncidentBody, actor: Creator, session: Session) -> dict[str, Any]:
    if body.category not in INCIDENT_CATEGORIES:
        raise AppError("CATEGORY_INVALID", "Kategori insiden tidak dikenal.", status_code=422)
    if body.occurred_on > numbering.today_jakarta():
        raise AppError(
            "DATE_IN_FUTURE", "Tanggal insiden tidak boleh di masa depan.", status_code=422
        )
    p = await _project(session, actor, body.project_id)
    x = Incident(
        number=await numbering.next(session, "INC"),
        project_id=p.id if p else None,
        occurred_on=body.occurred_on,
        category=body.category,
        location=body.location,
        description=body.description,
        lost_days=body.lost_days,
        created_by=actor.id,
    )
    session.add(x)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="incident",
        entity_id=x.id,
        actor_id=actor.id,
        after={"number": x.number, "category": x.category},
    )
    from app.notifications import service as notifications
    from app.workflow import engine

    qhse = await engine.holders_of_role(session, "qhse_coordinator")
    await notifications.notify(
        session,
        qhse,
        kind="incident",
        title=f"Insiden {x.number}: {x.category}",
        body=x.description[:200],
        link="/qhse?tab=incidents",
    )
    await session.commit()
    return _row(x, INC_FIELDS, await _projects(session))


@router.post("/incidents/{iid}/investigation")
async def investigate(
    iid: uuid.UUID, body: InvestigationBody, actor: Editor, session: Session
) -> dict[str, Any]:
    inc = await _get(session, Incident, iid, lock=True)
    data: dict[str, Any] = {}
    if body.root_cause is not None:
        data["root_cause"] = body.root_cause.strip() or None
    if body.investigation is not None:
        data["investigation"] = body.investigation.strip() or None
    if body.lost_days is not None:
        data["lost_days"] = body.lost_days
    await _capas(session, actor, "incident", inc.id, inc.project_id, body.capas)
    await svc.update_incident(session, actor, inc, data, body.close)
    await session.commit()
    return _row(inc, INC_FIELDS, await _projects(session))


# ---------------------------------------------------------------- CAPA

CAPA_FIELDS = (
    "number", "source_type", "action", "due_date", "status", "completion_note", "done_at",
    "verified_at", "owner_id",
)  # fmt: skip


class CapaBody(CapaIn):
    source_type: str = Field(
        default="other", pattern="^(incident|inspection|observation|audit|other)$"
    )
    project_id: uuid.UUID | None = None


class NoteBody(BaseModel):
    note: str = Field(min_length=5, max_length=3000)


@router.get("/capas")
async def list_capas(
    principal: CurrentUser, session: Session, mine: bool = False
) -> list[dict[str, Any]]:
    stmt = select(Capa).order_by(Capa.due_date)
    if mine or not principal.can("qhse", "view"):
        stmt = stmt.where(Capa.owner_id == principal.id)
    names = dict((await session.execute(select(User.id, User.full_name))).tuples().all())
    pj = await _projects(session)
    today = numbering.today_jakarta()
    return [
        {
            **_row(c, CAPA_FIELDS, pj),
            "owner_name": names.get(c.owner_id),
            "overdue": c.status == "open" and c.due_date < today,
            "can_complete": c.status == "open"
            and (c.owner_id == principal.id or principal.can("qhse", "edit")),
            "can_verify": c.status == "done"
            and principal.can("qhse", "approve")
            and c.done_by != principal.id,
        }
        for c in (await session.execute(stmt)).scalars()
    ]


@router.post("/capas", status_code=201)
async def create_capa(body: CapaBody, actor: Creator, session: Session) -> dict[str, Any]:
    c = await svc.create_capa(
        session,
        actor,
        source_type=body.source_type,
        source_id=None,
        project_id=body.project_id,
        action=body.action,
        owner_id=body.owner_id,
        due_date=body.due_date,
    )
    await session.commit()
    return _row(c, CAPA_FIELDS, await _projects(session))


@router.post("/capas/{cid}/complete")
async def complete_capa(
    cid: uuid.UUID, body: NoteBody, actor: CurrentUser, session: Session
) -> dict[str, Any]:
    c = await _get(session, Capa, cid, lock=True)
    await svc.complete_capa(session, actor, c, body.note)
    await session.commit()
    return _row(c, CAPA_FIELDS, await _projects(session))


@router.post("/capas/{cid}/verify")
async def verify_capa(cid: uuid.UUID, actor: Approver, session: Session) -> dict[str, Any]:
    c = await _get(session, Capa, cid, lock=True)
    await svc.verify_capa(session, actor, c)
    await session.commit()
    return _row(c, CAPA_FIELDS, await _projects(session))


# ---------------------------------------------------------------- statistics & CSMS


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    to = date_to or numbering.today_jakarta()
    return (date_from or to.replace(month=1, day=1)), to


@router.get("/statistics")
async def statistics(
    _: Viewer,
    session: Session,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    frm, to = _period(date_from, date_to)
    st = await svc.statistics(session, frm, to, project_id)
    return {k: _iso(v) for k, v in st.items()}


@router.get("/csms-export")
async def csms_export(
    _: Exporter, session: Session, date_from: date | None = None, date_to: date | None = None
) -> StreamingResponse:
    frm, to = _period(date_from, date_to)
    data = await svc.csms_workbook(session, frm, to)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="csms-{frm:%Y%m%d}-{to:%Y%m%d}.xlsx"'
        },
    )
