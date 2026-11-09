"""QHSE rules (prompt 05b).

- A project needs an approved HIRADC or JSA before its first DOR can be submitted.
- Approver of a HIRADC/JSA or permit is never its author (SoD).
- Incidents: reported -> investigating -> closed (root cause required for recordable cases).
- CAPA: open -> done (owner) -> verified (QHSE, not the person who did it); overdue reminders.
- Statistics: man-hours from approved DORs; LTI = lost time + fatality; recordable = medical
  treatment + restricted work + lost time + fatality; TRIR = recordable x 200.000 / man-hours;
  LTIFR = LTI x 1.000.000 / man-hours.
"""

import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError, ForbiddenError
from app.notifications import service as notifications
from app.operations import dor_service
from app.operations.models import HseDaily
from app.project.models import Project
from app.qhse.models import (
    LOST_TIME,
    RECORDABLE,
    Capa,
    Incident,
    Inspection,
    Observation,
    Permit,
    RiskAssessment,
)
from app.services import audit, numbering
from app.services.audit import AuditAction

ZERO = Decimal(0)


def _now() -> datetime:
    return datetime.now(UTC)


def _sod(actor: Principal, author: uuid.UUID | None, what: str) -> None:
    if author is not None and actor.id == author:
        raise ForbiddenError(
            "SOD_SELF_APPROVAL", f"Pembuat {what} tidak boleh menyetujuinya sendiri."
        )


# ---------------------------------------------------------------- HIRADC / JSA


async def approved_assessment(session: AsyncSession, project_id: uuid.UUID) -> bool:
    row = await session.execute(
        select(RiskAssessment.id).where(
            RiskAssessment.project_id == project_id, RiskAssessment.status == "approved"
        )
    )
    return row.first() is not None


async def _dor_gate(session: AsyncSession, project: Project) -> str | None:
    if await approved_assessment(session, project.id):
        return None
    return f"{project.number} belum punya HIRADC/JSA yang disetujui QHSE; DOR belum dapat diajukan."


dor_service.before_submit(_dor_gate)


def risk_score(likelihood: Any, severity: Any) -> int:
    try:
        lik, sev = int(likelihood), int(severity)
    except (TypeError, ValueError):
        return 0
    if not (1 <= lik <= 5 and 1 <= sev <= 5):
        return 0
    return lik * sev


def risk_level(score: int) -> str:
    return "high" if score >= 15 else "medium" if score >= 8 else "low" if score else "-"


def clean_hazards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if not str(r.get("hazard", "")).strip():
            continue
        score = risk_score(r.get("likelihood"), r.get("severity"))
        residual = risk_score(r.get("residual_likelihood"), r.get("residual_severity"))
        if score == 0:
            raise AppError(
                "RISK_INVALID",
                "Kemungkinan dan keparahan harus 1 sampai 5 untuk setiap bahaya.",
                status_code=422,
            )
        if score >= 8 and not str(r.get("controls", "")).strip():
            raise AppError(
                "CONTROLS_REQUIRED",
                f"Bahaya '{r['hazard']}' berisiko {risk_level(score)}: tulis pengendaliannya.",
                status_code=422,
            )
        out.append(
            {
                "activity": str(r.get("activity", "")).strip(),
                "hazard": str(r["hazard"]).strip(),
                "likelihood": int(r["likelihood"]),
                "severity": int(r["severity"]),
                "score": score,
                "level": risk_level(score),
                "controls": str(r.get("controls", "")).strip(),
                "residual_likelihood": r.get("residual_likelihood"),
                "residual_severity": r.get("residual_severity"),
                "residual_score": residual,
                "residual_level": risk_level(residual),
            }
        )
    if not out:
        raise AppError("HAZARDS_REQUIRED", "Isi minimal satu bahaya.", status_code=422)
    return out


async def create_assessment(
    session: AsyncSession,
    actor: Principal,
    project: Project,
    kind: str,
    title: str,
    hazards: list[dict[str, Any]],
) -> RiskAssessment:
    ra = RiskAssessment(
        number=await numbering.next(session, "HRA"),
        project_id=project.id,
        kind=kind,
        title=title.strip(),
        status="draft",
        hazards=clean_hazards(hazards),
        created_by=actor.id,
        is_demo=project.is_demo,
    )
    session.add(ra)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="risk_assessment",
        entity_id=ra.id,
        actor_id=actor.id,
        after={"number": ra.number, "kind": kind, "rows": len(ra.hazards)},
    )
    return ra


async def approve_assessment(session: AsyncSession, actor: Principal, ra: RiskAssessment) -> None:
    if ra.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{ra.number} bukan draf.")
    _sod(actor, ra.created_by, "HIRADC/JSA")
    ra.status, ra.approved_by, ra.approved_at = "approved", actor.id, _now()
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.APPROVE,
        entity_type="risk_assessment",
        entity_id=ra.id,
        actor_id=actor.id,
        after={"status": "approved"},
    )


# ---------------------------------------------------------------- permits


async def create_permit(
    session: AsyncSession, actor: Principal, project: Project, data: dict[str, Any]
) -> Permit:
    if data["valid_to"] <= data["valid_from"]:
        raise AppError("PERIOD_INVALID", "Akhir izin harus setelah awal izin.", status_code=422)
    if (data["valid_to"] - data["valid_from"]).total_seconds() > 24 * 3600:
        raise AppError("PERIOD_TOO_LONG", "Izin kerja berlaku maksimal 24 jam.", status_code=422)
    p = Permit(
        number=await numbering.next(session, "PTW"),
        project_id=project.id,
        created_by=actor.id,
        is_demo=project.is_demo,
        **data,
    )
    session.add(p)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="permit",
        entity_id=p.id,
        actor_id=actor.id,
        after={"number": p.number, "type": p.permit_type},
    )
    return p


async def permit_action(session: AsyncSession, actor: Principal, p: Permit, action: str) -> None:
    allowed = {
        "approve": ("requested",),
        "close": ("approved",),
        "cancel": ("requested", "approved"),
    }
    if p.status not in allowed[action]:
        raise ConflictError("ILLEGAL_TRANSITION", f"{p.number} tidak dapat di-{action}.")
    before = p.status
    if action == "approve":
        _sod(actor, p.created_by, "izin kerja")
        p.status, p.approved_by, p.approved_at = "approved", actor.id, _now()
    elif action == "close":
        p.status, p.closed_at = "closed", _now()
    else:
        p.status = "cancelled"
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type="permit",
        entity_id=p.id,
        actor_id=actor.id,
        before={"status": before},
        after={"status": p.status},
    )


# ---------------------------------------------------------------- incidents & CAPA


async def create_capa(
    session: AsyncSession,
    actor: Principal,
    *,
    source_type: str,
    source_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    action: str,
    owner_id: uuid.UUID,
    due_date: date,
) -> Capa:
    if due_date < numbering.today_jakarta():
        raise AppError("DUE_IN_PAST", "Tenggat CAPA tidak boleh di masa lalu.", status_code=422)
    c = Capa(
        number=await numbering.next(session, "CAPA"),
        source_type=source_type,
        source_id=source_id,
        project_id=project_id,
        action=action.strip(),
        owner_id=owner_id,
        due_date=due_date,
        created_by=actor.id,
    )
    session.add(c)
    await session.flush()
    await notifications.notify(
        session,
        [owner_id],
        kind="capa_assigned",
        title=f"CAPA {c.number} untuk Anda",
        body=f"{c.action[:200]} (tenggat {due_date:%d/%m/%Y})",
        link="/qhse?tab=capa",
    )
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="capa",
        entity_id=c.id,
        actor_id=actor.id,
        after={"number": c.number, "source": source_type, "due": due_date},
    )
    return c


async def complete_capa(session: AsyncSession, actor: Principal, c: Capa, note: str) -> None:
    if c.status != "open":
        raise ConflictError("NOT_OPEN", f"{c.number} sudah diselesaikan.")
    if actor.id != c.owner_id and not actor.can("qhse", "edit"):
        raise ForbiddenError(
            "NOT_OWNER", "Hanya pemilik CAPA atau QHSE yang dapat menyelesaikannya."
        )
    if len(note.strip()) < 5:
        raise AppError("NOTE_REQUIRED", "Tulis bukti penyelesaian.", status_code=422)
    c.status, c.completion_note, c.done_by, c.done_at = "done", note.strip(), actor.id, _now()
    await session.flush()


async def verify_capa(session: AsyncSession, actor: Principal, c: Capa) -> None:
    if c.status != "done":
        raise ConflictError("NOT_DONE", f"{c.number} belum diselesaikan.")
    if actor.id == c.done_by:
        raise ForbiddenError(
            "SOD_SELF_APPROVAL", "Verifikasi CAPA oleh orang lain dari pelaksananya."
        )
    c.status, c.verified_by, c.verified_at = "verified", actor.id, _now()
    await session.flush()


async def update_incident(
    session: AsyncSession, actor: Principal, inc: Incident, data: dict[str, Any], close: bool
) -> None:
    if inc.status == "closed":
        raise ConflictError("CLOSED", f"{inc.number} sudah ditutup.")
    for k, v in data.items():
        setattr(inc, k, v)
    if inc.status == "reported" and (inc.investigation or inc.root_cause):
        inc.status = "investigating"
    if close:
        if inc.category in RECORDABLE and not (inc.root_cause or "").strip():
            raise AppError(
                "ROOT_CAUSE_REQUIRED",
                "Insiden tercatat perlu akar masalah sebelum ditutup.",
                status_code=422,
            )
        open_capa = await session.execute(
            select(Capa.number).where(Capa.source_id == inc.id, Capa.status == "open")
        )
        if (n := open_capa.scalars().first()) is not None:
            raise ConflictError("CAPA_OPEN", f"Selesaikan {n} sebelum menutup insiden.")
        inc.status, inc.closed_at = "closed", _now()
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="incident",
        entity_id=inc.id,
        actor_id=actor.id,
        after={"status": inc.status},
    )


async def capa_overdue_alerts(session: AsyncSession, today: date | None = None) -> int:
    today = today or numbering.today_jakarta()
    sent = 0
    for c in (
        await session.execute(select(Capa).where(Capa.status == "open", Capa.due_date < today))
    ).scalars():
        sent += await notifications.notify(
            session,
            [c.owner_id],
            kind="capa_overdue",
            title=f"CAPA {c.number} lewat tenggat",
            body=c.action[:200],
            link="/qhse?tab=capa",
            dedupe_key=f"capa-overdue:{c.id}:{today}",
        )
    return sent


# ---------------------------------------------------------------- statistics & CSMS


async def statistics(
    session: AsyncSession, date_from: date, date_to: date, project_id: uuid.UUID | None = None
) -> dict[str, Any]:
    def scoped(stmt: Any, col: Any) -> Any:
        return stmt.where(col == project_id) if project_id else stmt

    manhours = Decimal(
        (
            await session.execute(
                scoped(
                    select(func.coalesce(func.sum(HseDaily.manhours), 0)).where(
                        HseDaily.report_date.between(date_from, date_to)
                    ),
                    HseDaily.project_id,
                )
            )
        ).scalar_one()
    )
    by_cat = dict(
        (
            await session.execute(
                scoped(
                    select(Incident.category, func.count())
                    .where(Incident.occurred_on.between(date_from, date_to))
                    .group_by(Incident.category),
                    Incident.project_id,
                )
            )
        )
        .tuples()
        .all()
    )
    lti = sum(int(by_cat.get(c, 0)) for c in LOST_TIME)
    recordable = sum(int(by_cat.get(c, 0)) for c in RECORDABLE)
    obs = (
        await session.execute(
            scoped(
                select(func.count())
                .select_from(Observation)
                .where(Observation.obs_date.between(date_from, date_to)),
                Observation.project_id,
            )
        )
    ).scalar_one()
    insp = (
        await session.execute(
            scoped(
                select(func.count())
                .select_from(Inspection)
                .where(Inspection.inspection_date.between(date_from, date_to)),
                Inspection.project_id,
            )
        )
    ).scalar_one()
    today = numbering.today_jakarta()
    capa_open = (
        await session.execute(
            scoped(
                select(func.count()).select_from(Capa).where(Capa.status == "open"), Capa.project_id
            )
        )
    ).scalar_one()
    capa_overdue = (
        await session.execute(
            scoped(
                select(func.count())
                .select_from(Capa)
                .where(Capa.status == "open", Capa.due_date < today),
                Capa.project_id,
            )
        )
    ).scalar_one()

    def rate(n: int, base: int) -> Decimal | None:
        return (Decimal(n) * base / manhours).quantize(Decimal("0.01")) if manhours > 0 else None

    return {
        "date_from": date_from,
        "date_to": date_to,
        "manhours": manhours,
        "incidents": {k: int(v) for k, v in by_cat.items()},
        "lti": lti,
        "recordable": recordable,
        "trir": rate(recordable, 200_000),
        "ltifr": rate(lti, 1_000_000),
        "near_misses": int(by_cat.get("near_miss", 0)),
        "observations": int(obs),
        "inspections": int(insp),
        "capa_open": int(capa_open),
        "capa_overdue": int(capa_overdue),
    }


async def csms_workbook(session: AsyncSession, date_from: date, date_to: date) -> bytes:
    """CSMS evidence pack: statistics, HIRADC/JSA, permits, inspections, incidents, CAPA."""
    stats = await statistics(session, date_from, date_to)
    projects: dict[uuid.UUID | None, str] = dict(
        (await session.execute(select(Project.id, Project.number))).tuples().all()
    )
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Statistik"
    ws.append(["Periode", f"{date_from:%d/%m/%Y} s.d. {date_to:%d/%m/%Y}"])
    for label, key in (
        ("Jam kerja (man-hours)", "manhours"),
        ("LTI", "lti"),
        ("Recordable", "recordable"),
        ("TRIR (per 200.000 jam)", "trir"),
        ("LTIFR (per 1.000.000 jam)", "ltifr"),
        ("Near miss", "near_misses"),
        ("Observasi", "observations"),
        ("Inspeksi", "inspections"),
        ("CAPA terbuka", "capa_open"),
        ("CAPA lewat tenggat", "capa_overdue"),
    ):
        v = stats[key]
        ws.append([label, float(v) if isinstance(v, Decimal) else v])

    def sheet(title: str, headers: list[str], rows: list[list[Any]]) -> None:
        s = wb.create_sheet(title)
        s.append(headers)
        for r in rows:
            s.append(r)

    ras = (await session.execute(select(RiskAssessment).order_by(RiskAssessment.number))).scalars()
    sheet(
        "HIRADC-JSA",
        ["Nomor", "Proyek", "Jenis", "Judul", "Status", "Jumlah bahaya", "Risiko tinggi"],
        [
            [
                r.number,
                projects.get(r.project_id),
                r.kind.upper(),
                r.title,
                r.status,
                len(r.hazards),
                sum(1 for h in r.hazards if h.get("level") == "high"),
            ]
            for r in ras
        ],
    )
    permits = (
        await session.execute(
            select(Permit)
            .where(func.date(Permit.valid_from).between(date_from, date_to))
            .order_by(Permit.number)
        )
    ).scalars()
    sheet(
        "Izin kerja",
        ["Nomor", "Proyek", "Jenis", "Lokasi", "Mulai", "Selesai", "Status"],
        [
            [
                p.number,
                projects.get(p.project_id),
                p.permit_type,
                p.location,
                p.valid_from.replace(tzinfo=None),
                p.valid_to.replace(tzinfo=None),
                p.status,
            ]
            for p in permits
        ],
    )
    insps = (
        await session.execute(
            select(Inspection)
            .where(Inspection.inspection_date.between(date_from, date_to))
            .order_by(Inspection.number)
        )
    ).scalars()
    sheet(
        "Inspeksi",
        ["Nomor", "Proyek", "Jenis", "Tanggal", "Temuan"],
        [
            [i.number, projects.get(i.project_id), i.inspection_type, i.inspection_date, i.findings]
            for i in insps
        ],
    )
    incs = (
        await session.execute(
            select(Incident)
            .where(Incident.occurred_on.between(date_from, date_to))
            .order_by(Incident.number)
        )
    ).scalars()
    sheet(
        "Insiden",
        ["Nomor", "Proyek", "Tanggal", "Kategori", "Hari hilang", "Akar masalah", "Status"],
        [
            [
                i.number,
                projects.get(i.project_id),
                i.occurred_on,
                i.category,
                i.lost_days,
                i.root_cause,
                i.status,
            ]
            for i in incs
        ],
    )
    capas = (await session.execute(select(Capa).order_by(Capa.number))).scalars()
    sheet(
        "CAPA",
        ["Nomor", "Sumber", "Tindakan", "Tenggat", "Status"],
        [[c.number, c.source_type, c.action, c.due_date, c.status] for c in capas],
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
