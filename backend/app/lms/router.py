"""LMS API (09)."""

import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Scope
from app.auth.principal import CurrentUser, Principal, require
from app.core import access
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.dms import service as dms
from app.dms.models import ControlledDocument, DocumentRevision
from app.lms import service as svc
from app.lms.models import Assignment, Course, CourseSession, Position, Requirement, TrainingBudget
from app.master.models import Employee
from app.services import audit
from app.services.numbering import today_jakarta
from app.services.storage import Storage, get_storage
from app.treasury.lookup import by_code

router = APIRouter(prefix="/lms", tags=["lms"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("lms", "view"))]


async def _manager(principal: CurrentUser) -> Principal:
    if principal.scope_for("lms", "edit") != Scope.ALL:
        raise ForbiddenError(
            "PERMISSION_DENIED", "Hanya pengelola pelatihan (HCBP/QHSE) yang dapat mengubah."
        )
    return principal


Manager = Annotated[Principal, Depends(_manager)]


async def _course_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    return p.can("lms", "view") if mode == "read" else p.scope_for("lms", "edit") == Scope.ALL


access.register("course", _course_access)


# ---------------------------------------------------------------- catalogue and matrix


class PositionIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=5000)


class Question(BaseModel):
    q: str = Field(min_length=2, max_length=500)
    options: list[str] = Field(min_length=2, max_length=8)
    answer: int = Field(ge=0, le=7)


class CourseIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    title: str = Field(min_length=2, max_length=200)
    kind: Literal["video", "pdf", "quiz", "scorm", "classroom", "practical"]
    description: str | None = Field(default=None, max_length=5000)
    duration_hours: Decimal = Field(
        default=Decimal(1), ge=0, le=1000, max_digits=6, decimal_places=1
    )
    validity_months: int | None = Field(default=None, ge=1, le=120)
    certificate_name: str | None = Field(default=None, max_length=120)
    cost: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=0)
    pass_score: int = Field(default=70, ge=0, le=100)
    questions: list[Question] = Field(default_factory=list, max_length=100)
    is_active: bool = True


def _course_out(c: Course, hide_answers: bool = False) -> dict[str, Any]:
    return {
        "code": c.code,
        "title": c.title,
        "kind": c.kind,
        "description": c.description,
        "duration_hours": format(c.duration_hours, "f"),
        "validity_months": c.validity_months,
        "certificate_name": c.certificate_name,
        "cost": format(c.cost, "f"),
        "pass_score": c.pass_score,
        "questions": [
            {k: v for k, v in q.items() if k != "answer" or not hide_answers} for q in c.questions
        ],
        "is_active": c.is_active,
    }


@router.get("/positions")
async def positions(_: Viewer, session: Session) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Position).order_by(Position.code))).scalars()
    reqs = list((await session.execute(select(Requirement))).scalars())
    return [
        {
            "code": p.code,
            "name": p.name,
            "description": p.description,
            "requirements": [
                {"course_code": r.course_code, "mandatory": r.mandatory}
                for r in reqs
                if r.position_code == p.code
            ],
        }
        for p in rows
    ]


@router.put("/positions/{code}")
async def save_position(
    code: str, body: PositionIn, actor: Manager, session: Session
) -> dict[str, Any]:
    p = await by_code(session, Position, code)
    if p is None:
        p = Position(
            code=body.code, name=body.name, description=body.description, created_by=actor.id
        )
        session.add(p)
    else:
        p.name, p.description = body.name, body.description
    await session.commit()
    return {"code": p.code}


class RequirementsIn(BaseModel):
    requirements: list[dict[str, Any]] = Field(max_length=100)


@router.put("/positions/{code}/requirements")
async def set_requirements(
    code: str, body: RequirementsIn, actor: Manager, session: Session
) -> dict[str, Any]:
    if await by_code(session, Position, code) is None:
        raise NotFoundError("NOT_FOUND", "Jabatan tidak ditemukan.")
    before = [
        (r.course_code, r.mandatory)
        for r in (
            await session.execute(select(Requirement).where(Requirement.position_code == code))
        ).scalars()
    ]
    for old in (
        await session.execute(select(Requirement).where(Requirement.position_code == code))
    ).scalars():
        await session.delete(old)
    await session.flush()
    for item in body.requirements:
        if await by_code(session, Course, item["course_code"]) is None:
            raise NotFoundError("COURSE_NOT_FOUND", f"Kursus {item['course_code']} tidak ada.")
        session.add(
            Requirement(
                position_code=code,
                course_code=item["course_code"],
                mandatory=bool(item.get("mandatory", True)),
            )
        )
    await audit.record(
        session,
        action="update",
        entity_type="competency_matrix",
        entity_id=code,
        actor_id=actor.id,
        before={"requirements": before},
        after={"requirements": body.requirements},
    )
    await session.commit()
    return {"position": code, "requirements": len(body.requirements)}


@router.get("/courses")
async def courses(p: Viewer, session: Session) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Course).order_by(Course.code))).scalars()
    hide = p.scope_for("lms", "edit") != Scope.ALL
    return [_course_out(c, hide) for c in rows]


@router.put("/courses/{code}")
async def save_course(
    code: str, body: CourseIn, actor: Manager, session: Session
) -> dict[str, Any]:
    c = await by_code(session, Course, code)
    data = body.model_dump()
    data["questions"] = [q.model_dump() for q in body.questions]
    if c is None:
        c = Course(created_by=actor.id, **data)
        session.add(c)
    else:
        for k, v in data.items():
            if k != "code":
                setattr(c, k, v)
    await session.commit()
    return _course_out(c)


# ---------------------------------------------------------------- assignments


def _a_out(
    a: Assignment, course: Course | None, doc: tuple[str, int, str, str] | None
) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "kind": a.kind,
        "reason": a.reason,
        "employee_code": a.employee_code,
        "course": _course_out(course, hide_answers=True) if course else None,
        "document": (
            {
                "code": doc[0],
                "revision": doc[1],
                "title": doc[2],
                "document_id": doc[3],
                "revision_id": str(a.revision_id),
            }
            if doc
            else None
        ),
        "due_date": a.due_date.isoformat() if a.due_date else None,
        "overdue": a.status == "assigned"
        and a.due_date is not None
        and a.due_date < today_jakarta(),
        "status": a.status,
        "score": a.score,
        "completed_at": a.completed_at.isoformat() if a.completed_at else None,
    }


async def _render(session: AsyncSession, rows: list[Assignment]) -> list[dict[str, Any]]:
    courses_ = {c.code: c for c in (await session.execute(select(Course))).scalars()}
    rev_ids = [a.revision_id for a in rows if a.revision_id]
    docs: dict[uuid.UUID, tuple[str, int, str, str]] = {}
    if rev_ids:
        for rid, code, rev, title, did in (
            await session.execute(
                select(
                    DocumentRevision.id,
                    ControlledDocument.code,
                    DocumentRevision.revision,
                    ControlledDocument.title,
                    ControlledDocument.id,
                )
                .join(ControlledDocument, ControlledDocument.id == DocumentRevision.document_id)
                .where(DocumentRevision.id.in_(rev_ids))
            )
        ).tuples():
            docs[rid] = (code, rev, title, str(did))
    return [
        _a_out(
            a, courses_.get(a.course_code or ""), docs.get(a.revision_id) if a.revision_id else None
        )
        for a in rows
    ]


@router.get("/my")
async def my_assignments(
    p: CurrentUser, session: Session, status: str | None = "assigned"
) -> list[dict[str, Any]]:
    mine = [Assignment.user_id == p.id]
    if p.user.employee_code:
        mine.append(Assignment.employee_code == p.user.employee_code)
    stmt = select(Assignment).where(or_(*mine))
    if status:
        stmt = stmt.where(Assignment.status == status)
    rows = list((await session.execute(stmt.order_by(Assignment.due_date))).scalars())
    return await _render(session, rows)


@router.get("/assignments")
async def all_assignments(
    _: Manager, session: Session, employee_code: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(Assignment).order_by(Assignment.created_at.desc()).limit(500)
    if employee_code:
        stmt = stmt.where(Assignment.employee_code == employee_code)
    if status:
        stmt = stmt.where(Assignment.status == status)
    return await _render(session, list((await session.execute(stmt)).scalars()))


class AssignIn(BaseModel):
    employee_codes: list[str] = Field(min_length=1, max_length=500)
    course_code: str
    due_date: date | None = None


@router.post("/assignments")
async def assign(body: AssignIn, actor: Manager, session: Session) -> dict[str, Any]:
    if await by_code(session, Course, body.course_code) is None:
        raise NotFoundError("COURSE_NOT_FOUND", "Kursus tidak ditemukan.")
    n = 0
    for code in body.employee_codes:
        a = await svc._assign(
            session,
            kind="course",
            reason="manual",
            key=f"manual-{code}-{body.course_code}-{uuid.uuid4().hex[:8]}",
            employee_code=code,
            user_id=await svc._user_of(session, code),
            course_code=body.course_code,
            due=body.due_date,
            by=actor.id,
        )
        n += 1 if a else 0
    await session.commit()
    return {"assigned": n}


async def _assignment(session: AsyncSession, aid: uuid.UUID) -> Assignment:
    a = await session.get(Assignment, aid, with_for_update=True)
    if a is None:
        raise NotFoundError("NOT_FOUND", "Penugasan tidak ditemukan.")
    return a


@router.post("/assignments/{aid}/complete")
async def complete(aid: uuid.UUID, p: CurrentUser, session: Session) -> dict[str, Any]:
    a = await svc.self_complete(session, p, await _assignment(session, aid))
    await session.commit()
    return (await _render(session, [a]))[0]


@router.post("/assignments/{aid}/acknowledge")
async def acknowledge(aid: uuid.UUID, p: CurrentUser, session: Session) -> dict[str, Any]:
    a = await svc.acknowledge(session, p, await _assignment(session, aid))
    await session.commit()
    return (await _render(session, [a]))[0]


class QuizIn(BaseModel):
    answers: list[int] = Field(max_length=100)


@router.post("/assignments/{aid}/quiz")
async def quiz(aid: uuid.UUID, body: QuizIn, p: CurrentUser, session: Session) -> dict[str, Any]:
    a, score, passed = await svc.quiz(session, p, await _assignment(session, aid), body.answers)
    await session.commit()
    return {**(await _render(session, [a]))[0], "score": score, "passed": passed}


@router.post("/run")
async def run(_: Manager, session: Session) -> dict[str, Any]:
    n = await svc.run_auto(session)
    await session.commit()
    return {"assigned": n}


# ---------------------------------------------------------------- sessions


class SessionIn(BaseModel):
    course_code: str
    starts_on: date
    location: str | None = Field(default=None, max_length=200)
    trainer: str | None = Field(default=None, max_length=120)
    supervisor_id: uuid.UUID | None = None
    capacity: int | None = Field(default=None, ge=1, le=500)


class AttendanceRow(BaseModel):
    employee_code: str
    attended: bool
    passed: bool = False
    score: int | None = Field(default=None, ge=0, le=100)


class AttendanceIn(BaseModel):
    rows: list[AttendanceRow] = Field(max_length=500)


def _s_out(s: CourseSession) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "course_code": s.course_code,
        "starts_on": s.starts_on.isoformat(),
        "location": s.location,
        "trainer": s.trainer,
        "supervisor_id": str(s.supervisor_id) if s.supervisor_id else None,
        "capacity": s.capacity,
        "status": s.status,
        "attendance": s.attendance,
    }


@router.get("/sessions")
async def sessions(_: Viewer, session: Session) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(CourseSession).order_by(CourseSession.starts_on.desc()).limit(200)
        )
    ).scalars()
    return [_s_out(s) for s in rows]


@router.post("/sessions")
async def create_session(body: SessionIn, actor: Manager, session: Session) -> dict[str, Any]:
    c = await by_code(session, Course, body.course_code)
    if c is None or c.kind not in ("classroom", "practical"):
        raise NotFoundError("COURSE_NOT_FOUND", "Pilih kursus kelas atau praktik.")
    s = CourseSession(**body.model_dump(), created_by=actor.id)
    session.add(s)
    await session.commit()
    return _s_out(s)


@router.post("/sessions/{sid}/attendance")
async def attendance(
    sid: uuid.UUID, body: AttendanceIn, p: CurrentUser, session: Session
) -> dict[str, Any]:
    s = await session.get(CourseSession, sid, with_for_update=True)
    if s is None:
        raise NotFoundError("NOT_FOUND", "Sesi tidak ditemukan.")
    if p.scope_for("lms", "edit") != Scope.ALL and s.supervisor_id != p.id:
        raise ForbiddenError("PERMISSION_DENIED", "Anda bukan pengelola atau pengawas sesi ini.")
    await svc.record_attendance(session, p, s, [r.model_dump() for r in body.rows])
    await session.commit()
    return _s_out(s)


# ---------------------------------------------------------------- certificates


class RenewIn(BaseModel):
    employee_code: str
    name: str = Field(min_length=2, max_length=120)
    number: str | None = Field(default=None, max_length=60)
    issued_on: date | None = None
    expiry_date: date
    attachment_id: uuid.UUID


@router.post("/certificates/renew")
async def renew(body: RenewIn, actor: Manager, session: Session) -> dict[str, Any]:
    emp = await svc.renew_certificate(session, actor, **body.model_dump())
    await session.commit()
    return {"employee_code": emp.code, "certificates": emp.certificates}


# ---------------------------------------------------------------- reports


@router.get("/compliance")
async def compliance(
    _: Manager, session: Session, department: str | None = None
) -> list[dict[str, Any]]:
    return await svc.compliance(session, department=department)


@router.get("/budget/{year}")
async def get_budget(year: int, _: Manager, session: Session) -> list[dict[str, Any]]:
    return await svc.budget(session, year)


class BudgetIn(BaseModel):
    department_code: str = Field(min_length=1, max_length=10)
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=0)


@router.put("/budget/{year}")
async def put_budget(
    year: int, body: BudgetIn, actor: Manager, session: Session
) -> list[dict[str, Any]]:
    b = (
        await session.execute(
            select(TrainingBudget).where(
                TrainingBudget.year == year, TrainingBudget.department_code == body.department_code
            )
        )
    ).scalar_one_or_none()
    if b is None:
        session.add(
            TrainingBudget(
                year=year,
                department_code=body.department_code,
                amount=body.amount,
                created_by=actor.id,
            )
        )
    else:
        b.amount = body.amount
    await session.commit()
    return await svc.budget(session, year)


@router.get("/evidence-pack")
async def evidence(
    actor: Manager, session: Session, department: str | None = None, since: date | None = None
) -> StreamingResponse:
    data = await svc.evidence_pack(session, department=department, since=since)
    await audit.record(
        session,
        action="export",
        entity_type="lms_evidence_pack",
        entity_id=department or "all",
        actor_id=actor.id,
    )
    await session.commit()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="csms-iso-evidence.xlsx"'},
    )


@router.post("/certificates/renew-upload")
async def renew_upload(
    actor: Manager,
    session: Session,
    storage: Annotated[Storage, Depends(get_storage)],
    employee_code: Annotated[str, Form(max_length=20)],
    name: Annotated[str, Form(min_length=2, max_length=120)],
    expiry_date: Annotated[date, Form()],
    file: Annotated[UploadFile, File()],
    number: Annotated[str | None, Form(max_length=60)] = None,
    issued_on: Annotated[date | None, Form()] = None,
) -> dict[str, Any]:
    """Upload the certificate scan to the employee's DMS files and renew in one step."""
    emp = await by_code(session, Employee, employee_code)
    if emp is None:
        raise NotFoundError("EMPLOYEE_NOT_FOUND", "Karyawan tidak ditemukan.")
    att = await dms.upload(
        session,
        storage,
        actor,
        entity_type="employees",
        entity_id=str(emp.id),
        filename=file.filename or "sertifikat.pdf",
        data=await file.read(dms.MAX_BYTES + 1),
        note=f"Sertifikat {name}",
    )
    emp = await svc.renew_certificate(
        session,
        actor,
        employee_code=employee_code,
        name=name,
        number=number,
        issued_on=issued_on,
        expiry_date=expiry_date,
        attachment_id=att.id,
    )
    await session.commit()
    return {"employee_code": emp.code, "certificates": emp.certificates}
