"""LMS (09).

Auto-assignment (job `lms`, and on events):
  onboarding / matrix   mandatory courses of the employee's position without a valid completion
  certificate_expiry    an employee certificate expiring within 90 days whose renewal course is
                        known (course.certificate_name); reminders at 90/60/30 days
  sop_revision          a controlled document revision becomes effective -> every user holding
                        one of the document's affected roles reads and acknowledges it
Certificate renewal (HCBP, scan in the DMS) updates the employee certificate, which is what the
DOR mobilisation gate checks, and completes the open renewal assignment.
"""

import io
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User, UserRole
from app.auth.permissions import Scope
from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.dms import controlled
from app.dms.models import Attachment, ControlledDocument, DocumentRevision
from app.lms.models import Assignment, Course, CourseSession, Requirement, TrainingBudget
from app.master.models import Employee
from app.notifications import service as notifications
from app.operations import dor_service
from app.services import audit
from app.services.numbering import today_jakarta
from app.treasury.lookup import by_code
from app.workflow import engine

ZERO = Decimal(0)
EXPIRY_DAYS = (90, 60, 30)
ACK_DAYS = 14
ONBOARDING_DAYS = 30
KINDS = ("video", "pdf", "quiz", "scorm", "classroom", "practical")


def _add_months(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    y, m = k // 12, k % 12 + 1
    return date(y, m, min(d.day, 28))


async def _assign(
    session: AsyncSession,
    *,
    kind: str,
    reason: str,
    key: str,
    employee_code: str | None = None,
    user_id: uuid.UUID | None = None,
    course_code: str | None = None,
    revision_id: uuid.UUID | None = None,
    due: date | None = None,
    by: uuid.UUID | None = None,
) -> Assignment | None:
    """Idempotent: one assignment per dedupe key."""
    if (await session.execute(select(Assignment.id).where(Assignment.dedupe_key == key))).first():
        return None
    a = Assignment(
        kind=kind,
        reason=reason,
        employee_code=employee_code,
        user_id=user_id,
        course_code=course_code,
        revision_id=revision_id,
        due_date=due,
        status="assigned",
        dedupe_key=key,
        created_by=by,
    )
    session.add(a)
    await session.flush()
    return a


async def _user_of(session: AsyncSession, employee_code: str) -> uuid.UUID | None:
    return (
        await session.execute(select(User.id).where(User.employee_code == employee_code))
    ).scalar_one_or_none()


# ---------------------------------------------------------------- validity


def cert_of(emp: Employee, name: str) -> dict[str, Any] | None:
    for c in emp.certificates or []:
        if str(c.get("name", "")).strip().lower() == name.strip().lower():
            return c
    return None


async def valid_until(session: AsyncSession, emp: Employee, course: Course) -> date | None:
    """Until when the employee holds this competency (None = not held; date.max = no expiry)."""
    if course.certificate_name:
        c = cert_of(emp, course.certificate_name)
        if c and c.get("expiry_date"):
            return date.fromisoformat(str(c["expiry_date"]))
        if c:
            return date.max
    last = (
        await session.execute(
            select(func.max(Assignment.completed_at)).where(
                Assignment.employee_code == emp.code,
                Assignment.course_code == course.code,
                Assignment.status == "completed",
            )
        )
    ).scalar_one()
    if last is None:
        return None
    if not course.validity_months:
        return date.max
    return _add_months(last.date(), course.validity_months)


# ---------------------------------------------------------------- auto-assignment


async def assign_matrix(session: AsyncSession, today: date | None = None) -> int:
    today = today or today_jakarta()
    n = 0
    reqs = list(
        (
            await session.execute(
                select(Requirement, Course)
                .join(Course, Course.code == Requirement.course_code)
                .where(Requirement.mandatory.is_(True), Course.is_active.is_(True))
            )
        ).tuples()
    )
    by_pos: dict[str, list[Course]] = {}
    for r, c in reqs:
        by_pos.setdefault(r.position_code, []).append(c)
    emps = (
        await session.execute(
            select(Employee).where(
                Employee.is_active.is_(True), Employee.position_code.is_not(None)
            )
        )
    ).scalars()
    for e in emps:
        for c in by_pos.get(e.position_code or "", []):
            until = await valid_until(session, e, c)
            if until is not None and until >= today:
                continue
            new = e.join_date is not None and e.join_date >= today - timedelta(days=ONBOARDING_DAYS)
            reason = "onboarding" if new else "matrix"
            base = e.join_date if new and e.join_date else today
            a = await _assign(
                session,
                kind="course",
                reason=reason,
                key=f"matrix-{e.code}-{c.code}-{until or 'none'}",
                employee_code=e.code,
                user_id=await _user_of(session, e.code),
                course_code=c.code,
                due=base + timedelta(days=ONBOARDING_DAYS),
            )
            n += 1 if a else 0
    return n


async def assign_expiring(session: AsyncSession, today: date | None = None) -> int:
    today = today or today_jakarta()
    courses = {
        c.certificate_name.strip().lower(): c
        for c in (
            await session.execute(
                select(Course).where(
                    Course.certificate_name.is_not(None), Course.is_active.is_(True)
                )
            )
        ).scalars()
        if c.certificate_name
    }
    hcbp = await engine.holders_of_role(session, "hcbp_officer")
    n = 0
    for e in (
        await session.execute(select(Employee).where(Employee.is_active.is_(True)))
    ).scalars():
        for cert in e.certificates or []:
            if not cert.get("expiry_date"):
                continue
            exp = date.fromisoformat(str(cert["expiry_date"]))
            left = (exp - today).days
            if left > EXPIRY_DAYS[0]:
                continue
            course = courses.get(str(cert.get("name", "")).strip().lower())
            user = await _user_of(session, e.code)
            if course is not None:
                a = await _assign(
                    session,
                    kind="course",
                    reason="certificate_expiry",
                    key=f"expiry-{e.code}-{course.code}-{exp}",
                    employee_code=e.code,
                    user_id=user,
                    course_code=course.code,
                    due=exp,
                )
                n += 1 if a else 0
            stage = next((d for d in reversed(EXPIRY_DAYS) if left <= d), EXPIRY_DAYS[0])
            await notifications.notify(
                session,
                list({*hcbp, *([user] if user else [])}),
                kind="certificate_expiry",
                title=f"Sertifikat {cert.get('name')} {e.full_name} "
                + ("kedaluwarsa" if left < 0 else f"berakhir dalam {left} hari"),
                body=(
                    "Jadwalkan pelatihan perpanjangan; setelah kedaluwarsa tidak bisa dimobilisasi."
                ),
                link="/pelatihan?tab=compliance",
                dedupe_key=f"lms-cert-{e.code}-{cert.get('name')}-{exp}-{stage}",
            )
    return n


async def _on_revision_effective(
    session: AsyncSession, doc: ControlledDocument, rev: DocumentRevision
) -> None:
    """Read-and-acknowledge for the holders of the affected roles."""
    if not doc.affected_roles:
        return
    rows = (
        await session.execute(
            select(User.id, User.employee_code)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                Role.code.in_(doc.affected_roles),
                Role.is_active.is_(True),
                User.is_active.is_(True),
                UserRole.active_now(),
            )
            .distinct()
        )
    ).all()
    due = today_jakarta() + timedelta(days=ACK_DAYS)
    users = []
    for uid, emp in rows:
        a = await _assign(
            session,
            kind="acknowledge",
            reason="sop_revision",
            key=f"ack-{rev.id}-{uid}",
            employee_code=emp,
            user_id=uid,
            revision_id=rev.id,
            due=due,
        )
        if a:
            users.append(uid)
    # Older acknowledgements of this document are no longer needed.
    old = (
        await session.execute(
            select(Assignment)
            .join(DocumentRevision, DocumentRevision.id == Assignment.revision_id)
            .where(
                DocumentRevision.document_id == doc.id,
                Assignment.revision_id != rev.id,
                Assignment.status == "assigned",
            )
        )
    ).scalars()
    for a in old:
        a.status, a.note = "cancelled", "Diganti revisi baru"
    await notifications.notify(
        session,
        users,
        kind="sop_acknowledge",
        title=f"Baca & konfirmasi {doc.code} Rev.{rev.revision}",
        body=f"{doc.title[:150]} — paling lambat {due:%d/%m/%Y}.",
        link="/pelatihan",
    )


controlled.on_revision_effective(_on_revision_effective)


async def run_auto(session: AsyncSession) -> int:
    return await assign_matrix(session) + await assign_expiring(session)


# ---------------------------------------------------------------- completing


def _owner(p: Principal, a: Assignment) -> bool:
    return a.user_id == p.id or (
        a.employee_code is not None and a.employee_code == p.user.employee_code
    )


def _hcbp(p: Principal) -> bool:
    return p.scope_for("lms", "edit") == Scope.ALL


async def _complete(
    session: AsyncSession,
    a: Assignment,
    *,
    by: uuid.UUID | None,
    score: int | None = None,
    evidence: uuid.UUID | None = None,
) -> Assignment:
    if a.status != "assigned":
        raise ConflictError("ASSIGNMENT_DONE", "Penugasan ini sudah selesai atau dibatalkan.")
    course = await by_code(session, Course, a.course_code) if a.course_code else None
    a.status, a.completed_at, a.score = "completed", datetime.now(UTC), score
    a.cost = Decimal(course.cost) if course else ZERO
    a.evidence_attachment_id, a.verified_by = evidence, by
    await session.flush()
    await audit.record(
        session,
        action="training_completed",
        entity_type="training_assignment",
        entity_id=a.id,
        actor_id=by,
        after={
            "course": a.course_code,
            "revision": str(a.revision_id) if a.revision_id else None,
            "score": score,
        },
    )
    return a


async def self_complete(session: AsyncSession, actor: Principal, a: Assignment) -> Assignment:
    """Video / PDF courses and SCORM completion reported by the learner."""
    if not _owner(actor, a):
        raise ForbiddenError("NOT_ASSIGNEE", "Penugasan ini bukan milik Anda.")
    course = await by_code(session, Course, a.course_code) if a.course_code else None
    if course is None or course.kind not in ("video", "pdf", "scorm"):
        raise AppError(
            "COMPLETION_METHOD",
            "Kursus ini diselesaikan lewat kuis, kelas atau praktik yang diawasi.",
            status_code=422,
        )
    return await _complete(session, a, by=actor.id)


async def acknowledge(session: AsyncSession, actor: Principal, a: Assignment) -> Assignment:
    if a.kind != "acknowledge" or not _owner(actor, a):
        raise ForbiddenError("NOT_ASSIGNEE", "Penugasan ini bukan milik Anda.")
    return await _complete(session, a, by=actor.id)


async def quiz(
    session: AsyncSession, actor: Principal, a: Assignment, answers: list[int]
) -> tuple[Assignment, int, bool]:
    if not _owner(actor, a):
        raise ForbiddenError("NOT_ASSIGNEE", "Penugasan ini bukan milik Anda.")
    course = await by_code(session, Course, a.course_code) if a.course_code else None
    if course is None or course.kind != "quiz" or not course.questions:
        raise AppError("NOT_A_QUIZ", "Kursus ini tidak memiliki kuis.", status_code=422)
    if a.status != "assigned":
        raise ConflictError("ASSIGNMENT_DONE", "Penugasan ini sudah selesai.")
    right = sum(
        1
        for q, ans in zip(course.questions, answers, strict=False)
        if int(q.get("answer", -1)) == int(ans)
    )
    score = round(right * 100 / len(course.questions))
    passed = score >= course.pass_score
    if passed:
        await _complete(session, a, by=actor.id, score=score)
    else:
        a.score = score
        await session.flush()
    return a, score, passed


async def record_attendance(
    session: AsyncSession, actor: Principal, s: CourseSession, rows: list[dict[str, Any]]
) -> CourseSession:
    """Classroom attendance / supervised practical results; passing completes the open
    assignment (and renews the certificate when the course carries one and a scan is given)."""
    course = await by_code(session, Course, s.course_code)
    assert course is not None
    if course.kind == "practical" and s.supervisor_id != actor.id and not _hcbp(actor):
        raise ForbiddenError("NOT_SUPERVISOR", "Hasil praktik dicatat oleh pengawas sesi.")
    out = []
    for r in rows:
        out.append({k: r.get(k) for k in ("employee_code", "attended", "passed", "score")})
        if not (r.get("attended") and r.get("passed")):
            continue
        open_a = (
            await session.execute(
                select(Assignment).where(
                    Assignment.employee_code == r["employee_code"],
                    Assignment.course_code == course.code,
                    Assignment.status == "assigned",
                )
            )
        ).scalars()
        done_any = False
        for a in open_a:
            await _complete(session, a, by=actor.id, score=r.get("score"))
            done_any = True
        if not done_any:
            a2 = await _assign(
                session,
                kind="course",
                reason="manual",
                key=f"session-{s.id}-{r['employee_code']}",
                employee_code=r["employee_code"],
                course_code=course.code,
                by=actor.id,
            )
            if a2:
                await _complete(session, a2, by=actor.id, score=r.get("score"))
    s.attendance, s.status = out, "done"
    await session.flush()
    return s


async def renew_certificate(
    session: AsyncSession,
    actor: Principal,
    *,
    employee_code: str,
    name: str,
    number: str | None,
    issued_on: date | None,
    expiry_date: date,
    attachment_id: uuid.UUID,
) -> Employee:
    """New certificate with its scan in the DMS: replaces the employee's entry of that name,
    which lifts the DOR mobilisation gate, and completes the open renewal assignment."""
    emp = await by_code(session, Employee, employee_code)
    if emp is None:
        raise NotFoundError("EMPLOYEE_NOT_FOUND", "Karyawan tidak ditemukan.")
    att = await session.get(Attachment, attachment_id)
    if att is None or att.entity_type != "employees" or att.entity_id != str(emp.id):
        raise AppError(
            "SCAN_REQUIRED",
            "Unggah scan sertifikat pada data karyawan ini terlebih dahulu.",
            status_code=422,
        )
    if expiry_date <= today_jakarta():
        raise AppError(
            "EXPIRY_INVALID", "Masa berlaku sertifikat baru harus di masa depan.", status_code=422
        )
    old = cert_of(emp, name)
    entry = {
        "name": old["name"] if old else name.strip(),
        "number": number,
        "issued_on": issued_on.isoformat() if issued_on else None,
        "expiry_date": expiry_date.isoformat(),
        "mandatory": bool(old.get("mandatory", True)) if old else True,
        "attachment_id": str(att.id),
    }
    certs = [c for c in (emp.certificates or []) if c is not old]
    emp.certificates = [*certs, entry]
    await session.flush()
    await audit.record(
        session,
        action="certificate_renewed",
        entity_type="employees",
        entity_id=emp.id,
        actor_id=actor.id,
        before={"certificate": old},
        after={"certificate": entry},
    )
    courses = [
        c.code
        for c in (
            await session.execute(
                select(Course).where(func.lower(Course.certificate_name) == name.strip().lower())
            )
        ).scalars()
    ]
    if courses:
        for a in (
            await session.execute(
                select(Assignment).where(
                    Assignment.employee_code == emp.code,
                    Assignment.course_code.in_(courses),
                    Assignment.status == "assigned",
                )
            )
        ).scalars():
            await _complete(session, a, by=actor.id, evidence=att.id)
    return emp


# ---------------------------------------------------------------- reports


async def compliance(
    session: AsyncSession, today: date | None = None, department: str | None = None
) -> list[dict[str, Any]]:
    """Per employee: matrix courses and mandatory certificates with their status."""
    today = today or today_jakarta()
    reqs = list(
        (
            await session.execute(
                select(Requirement, Course).join(Course, Course.code == Requirement.course_code)
            )
        ).tuples()
    )
    stmt = select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.code)
    if department:
        stmt = stmt.where(Employee.department_code == department)
    out = []
    for e in (await session.execute(stmt)).scalars():
        items = []
        for r, c in reqs:
            if r.position_code != e.position_code:
                continue
            until = await valid_until(session, e, c)
            status = (
                "missing" if until is None
                else "expired" if until < today
                else "expiring" if until != date.max and until <= today + timedelta(days=90)
                else "valid"
            )  # fmt: skip
            items.append(
                {
                    "kind": "course",
                    "code": c.code,
                    "name": c.title,
                    "mandatory": r.mandatory,
                    "valid_until": None if until in (None, date.max) else until.isoformat(),
                    "status": status,
                }
            )
        block, _ = dor_service.cert_status(e.certificates or [], today)
        for cert in e.certificates or []:
            if not cert.get("mandatory", True):
                continue
            exp = date.fromisoformat(str(cert["expiry_date"])) if cert.get("expiry_date") else None
            status = (
                "valid" if exp is None
                else "expired" if exp < today
                else "expiring" if exp <= today + timedelta(days=90)
                else "valid"
            )  # fmt: skip
            items.append(
                {
                    "kind": "certificate",
                    "code": cert.get("number"),
                    "name": cert.get("name"),
                    "mandatory": True,
                    "valid_until": exp.isoformat() if exp else None,
                    "status": status,
                    "scan": cert.get("attachment_id"),
                }
            )
        mandatory = [i for i in items if i["mandatory"]]
        ok = [i for i in mandatory if i["status"] in ("valid", "expiring")]
        out.append(
            {
                "employee_code": e.code,
                "name": e.full_name,
                "position_code": e.position_code,
                "department": e.department_code,
                "is_field": e.is_field,
                "mobilisation_blocked": block,
                "compliance_pct": round(len(ok) * 100 / len(mandatory)) if mandatory else 100,
                "items": items,
            }
        )
    return out


async def budget(session: AsyncSession, year: int) -> list[dict[str, Any]]:
    budgets = {
        b.department_code: Decimal(b.amount)
        for b in (
            await session.execute(select(TrainingBudget).where(TrainingBudget.year == year))
        ).scalars()
    }
    spent = dict(
        (
            await session.execute(
                select(Employee.department_code, func.coalesce(func.sum(Assignment.cost), 0))
                .join(Employee, Employee.code == Assignment.employee_code)
                .where(
                    Assignment.status == "completed",
                    func.extract("year", Assignment.completed_at) == year,
                )
                .group_by(Employee.department_code)
            )
        )
        .tuples()
        .all()
    )
    out = []
    for dept in sorted(set(budgets) | {d for d in spent if d}):
        b, s = budgets.get(dept, ZERO), Decimal(spent.get(dept, 0))
        out.append(
            {
                "department": dept,
                "budget": format(b, "f"),
                "spent": format(s, "f"),
                "remaining": format(b - s, "f"),
                "used_pct": round(float(s * 100 / b), 1) if b else None,
            }
        )
    return out


async def evidence_pack(
    session: AsyncSession, *, department: str | None = None, since: date | None = None
) -> bytes:
    """CSMS / ISO evidence workbook: compliance, training records, certificates,
    acknowledgements of controlled documents."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Kepatuhan"
    ws.append(["NIP", "Nama", "Jabatan", "Departemen", "Kepatuhan %", "Mobilisasi diblokir"])
    rows = await compliance(session, department=department)
    for r in rows:
        ws.append(
            [
                r["employee_code"],
                r["name"],
                r["position_code"],
                r["department"],
                r["compliance_pct"],
                r["mobilisation_blocked"] or "",
            ]
        )
    codes = [r["employee_code"] for r in rows]
    tr = wb.create_sheet("Riwayat pelatihan")
    tr.append(["NIP", "Kursus", "Judul", "Selesai", "Nilai", "Alasan"])
    stmt = (
        select(Assignment, Course.title)
        .outerjoin(Course, Course.code == Assignment.course_code)
        .where(
            Assignment.status == "completed",
            Assignment.kind == "course",
            Assignment.employee_code.in_(codes),
        )
        .order_by(Assignment.completed_at)
    )
    if since:
        stmt = stmt.where(
            Assignment.completed_at >= datetime(since.year, since.month, since.day, tzinfo=UTC)
        )
    for a, title in (await session.execute(stmt)).tuples():
        tr.append(
            [
                a.employee_code,
                a.course_code,
                title,
                a.completed_at.date().isoformat() if a.completed_at else "",
                a.score,
                a.reason,
            ]
        )
    ce = wb.create_sheet("Sertifikat")
    ce.append(["NIP", "Sertifikat", "Nomor", "Berlaku s.d.", "Wajib", "Scan DMS"])
    for r in rows:
        for i in r["items"]:
            if i["kind"] == "certificate":
                ce.append(
                    [
                        r["employee_code"],
                        i["name"],
                        i["code"],
                        i["valid_until"],
                        "ya",
                        i.get("scan") or "",
                    ]
                )
    ak = wb.create_sheet("Konfirmasi SOP")
    ak.append(["Pengguna", "Dokumen", "Revisi", "Status", "Selesai"])
    acks = (
        await session.execute(
            select(Assignment, ControlledDocument.code, DocumentRevision.revision, User.full_name)
            .join(DocumentRevision, DocumentRevision.id == Assignment.revision_id)
            .join(ControlledDocument, ControlledDocument.id == DocumentRevision.document_id)
            .outerjoin(User, User.id == Assignment.user_id)
            .where(Assignment.kind == "acknowledge")
        )
    ).tuples()
    for a, code, rev, name in acks:
        ak.append(
            [name, code, rev, a.status, a.completed_at.date().isoformat() if a.completed_at else ""]
        )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
