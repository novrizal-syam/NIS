"""Maintenance rules (GEK-MNT-001; prompt 05b).

Hour meter = operating hours of approved DORs (`asset_usage`).
Scheduler: for every active asset with an equipment type, each active PM task of that type has
a schedule; a calendar task is due `CALENDAR_DAYS[freq]` after it was last done, an hour task
`interval_hours` of operation after it was last done. Due -> one open work order per asset and
task (never duplicated). Daily tasks only run while the asset is allocated to a project.
`per_job` tasks feed the pre-mobilisation / post-job inspections created on allocation/release.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.inventory import stock_service as stock
from app.maintenance.models import (
    CALENDAR_DAYS,
    AssetAllocation,
    Downtime,
    PmSchedule,
    PmTask,
    WorkOrder,
    WorkOrderPart,
)
from app.master.models import Asset
from app.operations import dor_service
from app.operations.models import AssetUsage, Dor, DorEquipment
from app.project.models import Project
from app.services import audit, ledger, numbering
from app.services.audit import AuditAction

DOC = "work_order"
ZERO = Decimal(0)
MAINTENANCE_ACCOUNT = "5200"
OPEN = ("open", "in_progress")
DEFAULT_PRE = [
    "Sertifikat & kalibrasi berlaku",
    "Inspeksi visual: korosi, kebocoran, kerusakan",
    "Uji fungsi / tekanan sesuai prosedur",
    "Kelengkapan aksesori & suku cadang",
    "Pengikatan & label pengiriman",
]
DEFAULT_POST = [
    "Pembersihan & dekontaminasi",
    "Inspeksi visual setelah pekerjaan",
    "Catat jam operasi & temuan",
    "Kebutuhan perbaikan dilaporkan",
]


def _now() -> datetime:
    return datetime.now(UTC)


async def meter(session: AsyncSession, asset_code: str) -> Decimal:
    v = (
        await session.execute(
            select(func.coalesce(func.sum(AssetUsage.operating), 0)).where(
                AssetUsage.asset_code == asset_code
            )
        )
    ).scalar_one()
    return Decimal(v)


async def current_allocation(session: AsyncSession, asset_code: str) -> AssetAllocation | None:
    return (
        await session.execute(
            select(AssetAllocation).where(
                AssetAllocation.asset_code == asset_code, AssetAllocation.released_at.is_(None)
            )
        )
    ).scalar_one_or_none()


def _checklist(items: list[str]) -> list[dict[str, Any]]:
    return [{"item": i, "result": None, "note": None} for i in items]


async def _new_wo(
    session: AsyncSession,
    *,
    asset: str,
    kind: str,
    title: str,
    by: uuid.UUID | None,
    checklist: list[str],
    task: PmTask | None = None,
    project_id: uuid.UUID | None = None,
    dor_id: uuid.UUID | None = None,
    trigger: str | None = None,
    due_date: date | None = None,
    due_hours: Decimal | None = None,
) -> WorkOrder:
    wo = WorkOrder(
        number=await numbering.next(session, "WO"),
        asset_code=asset,
        kind=kind,
        status="open",
        title=title[:200],
        task_code=task.code if task else None,
        form_code=task.form_code if task else None,
        project_id=project_id,
        dor_id=dor_id,
        trigger=trigger,
        due_date=due_date,
        due_hours=due_hours,
        checklist=_checklist(checklist),
        created_by=by,
    )
    session.add(wo)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=wo.id,
        actor_id=by,
        after={"number": wo.number, "asset": asset, "kind": kind, "trigger": trigger},
    )
    return wo


# ---------------------------------------------------------------- scheduler


async def _open_wo_exists(session: AsyncSession, asset: str, task_code: str) -> bool:
    row = await session.execute(
        select(WorkOrder.id).where(
            WorkOrder.asset_code == asset,
            WorkOrder.task_code == task_code,
            WorkOrder.status.in_(OPEN),
        )
    )
    return row.first() is not None


async def _schedules(
    session: AsyncSession, asset: Asset, today: date
) -> list[tuple[PmSchedule, PmTask]]:
    if not asset.equipment_type_code:
        return []
    tasks = list(
        (
            await session.execute(
                select(PmTask).where(
                    PmTask.equipment_type_code == asset.equipment_type_code,
                    PmTask.is_active,
                    PmTask.frequency != "per_job",
                )
            )
        ).scalars()
    )
    have = {
        s.task_code: s
        for s in (
            await session.execute(select(PmSchedule).where(PmSchedule.asset_code == asset.code))
        ).scalars()
    }
    out = []
    for t in tasks:
        s = have.get(t.code)
        if s is None:
            # Unknown history: calendar tasks start counting today, hour tasks from 0 h.
            s = PmSchedule(asset_code=asset.code, task_code=t.code, last_done_date=today)
            s.last_done_hours = ZERO
            session.add(s)
        out.append((s, t))
    await session.flush()
    return out


async def check_asset(
    session: AsyncSession, asset: Asset, today: date, by: uuid.UUID | None = None
) -> list[WorkOrder]:
    created: list[WorkOrder] = []
    hours = await meter(session, asset.code)
    allocated = await current_allocation(session, asset.code)
    for s, t in await _schedules(session, asset, today):
        due = False
        trigger = ""
        if t.frequency == "hours" and t.interval_hours:
            s.next_due_hours = s.last_done_hours + t.interval_hours
            s.next_due_date = None
            due = hours >= s.next_due_hours
            trigger = f"Jam operasi {hours.normalize():f} ≥ {s.next_due_hours.normalize():f}"
        elif t.frequency in CALENDAR_DAYS:
            s.next_due_date = s.last_done_date + timedelta(days=CALENDAR_DAYS[t.frequency])
            s.next_due_hours = None
            due = today >= s.next_due_date and (t.frequency != "daily" or allocated is not None)
            trigger = f"Jadwal {t.frequency}, jatuh tempo {s.next_due_date.isoformat()}"
        if due and not await _open_wo_exists(session, asset.code, t.code):
            created.append(
                await _new_wo(
                    session,
                    asset=asset.code,
                    kind="preventive",
                    title=f"PM {t.title} — {asset.code}",
                    by=by,
                    checklist=list(t.checklist) or [t.title],
                    task=t,
                    project_id=allocated.project_id if allocated else None,
                    trigger=trigger,
                    due_date=s.next_due_date,
                    due_hours=s.next_due_hours,
                )
            )
    await session.flush()
    return created


async def run_pm(session: AsyncSession, today: date | None = None) -> int:
    """Scheduler job: create due PM work orders for every asset."""
    today = today or numbering.today_jakarta()
    n = 0
    assets = (
        await session.execute(
            select(Asset).where(Asset.is_active, Asset.equipment_type_code.is_not(None))
        )
    ).scalars()
    for a in list(assets):
        n += len(await check_asset(session, a, today))
    return n


# ---------------------------------------------------------------- DOR hook


async def after_dor(session: AsyncSession, dor: Dor, by: uuid.UUID | None) -> None:
    """Approved DOR: corrective WO + downtime for every breakdown, then hour-based PM."""
    rows = list(
        (await session.execute(select(DorEquipment).where(DorEquipment.dor_id == dor.id))).scalars()
    )
    for x in rows:
        if x.breakdown > 0:
            reason = (x.remark or "").strip() or "Breakdown tercatat di DOR"
            wo = await _new_wo(
                session,
                asset=x.asset_code,
                kind="corrective",
                title=f"Perbaikan {x.asset_code}: {reason}",
                by=by,
                checklist=["Identifikasi penyebab kerusakan", "Perbaikan", "Uji fungsi"],
                project_id=dor.project_id,
                dor_id=dor.id,
                trigger=f"Breakdown {x.breakdown.normalize():f} jam di {dor.number}",
                due_date=dor.report_date + timedelta(days=1),
            )
            session.add(
                Downtime(
                    asset_code=x.asset_code,
                    start_date=dor.report_date,
                    end_date=dor.report_date,
                    hours=x.breakdown,
                    reason=reason[:500],
                    wo_id=wo.id,
                    dor_id=dor.id,
                    created_by=by,
                )
            )
    for code in {x.asset_code for x in rows}:
        asset = (await session.execute(select(Asset).where(Asset.code == code))).scalar_one()
        await check_asset(session, asset, numbering.today_jakarta(), by)
    await session.flush()


dor_service.after_approval(after_dor)


# ---------------------------------------------------------------- allocation


async def allocate(
    session: AsyncSession,
    actor: Principal,
    asset: Asset,
    project: Project,
    start: date,
    note: str | None,
) -> tuple[AssetAllocation, WorkOrder]:
    block, _warn = dor_service.cert_status(asset.certificates, start)
    if block:
        raise AppError(
            "ASSET_CERT_EXPIRED",
            f"{asset.code} tidak dapat dialokasikan: {block}. Perpanjang sertifikat dulu.",
            status_code=422,
        )
    if not asset.is_active:
        raise AppError("ASSET_INACTIVE", f"{asset.code} tidak aktif.", status_code=422)
    if project.status != "locked":
        raise AppError("PROJECT_NOT_LOCKED", f"{project.number} belum terkunci.", status_code=422)
    cur = await current_allocation(session, asset.code)
    if cur is not None:
        other = await session.get(Project, cur.project_id)
        raise ConflictError(
            "ASSET_ALLOCATED",
            f"{asset.code} masih dialokasikan ke {other.number if other else 'proyek lain'}.",
        )
    alloc = AssetAllocation(
        asset_code=asset.code,
        project_id=project.id,
        start_date=start,
        note=note,
        created_by=actor.id,
    )
    session.add(alloc)
    await session.flush()
    wo = await _new_wo(
        session,
        asset=asset.code,
        kind="inspection_pre",
        title=f"Inspeksi pra-mobilisasi {asset.code} → {project.number}",
        by=actor.id,
        checklist=await _per_job_items(session, asset) or DEFAULT_PRE,
        project_id=project.id,
        trigger="Alokasi ke proyek",
        due_date=start,
    )
    await audit.record(
        session,
        action="allocate",
        entity_type="asset",
        entity_id=asset.id,
        actor_id=actor.id,
        after={"project": project.number, "start": start},
    )
    return alloc, wo


async def _per_job_items(session: AsyncSession, asset: Asset) -> list[str]:
    if not asset.equipment_type_code:
        return []
    items: list[str] = []
    for t in (
        await session.execute(
            select(PmTask).where(
                PmTask.equipment_type_code == asset.equipment_type_code,
                PmTask.frequency == "per_job",
                PmTask.is_active,
            )
        )
    ).scalars():
        items += list(t.checklist) or [t.title]
    return items


async def release(session: AsyncSession, actor: Principal, asset: Asset, on: date) -> WorkOrder:
    cur = await current_allocation(session, asset.code)
    if cur is None:
        raise ConflictError("NOT_ALLOCATED", f"{asset.code} tidak sedang dialokasikan.")
    if on < cur.start_date:
        raise AppError("DATE_INVALID", "Tanggal lepas sebelum tanggal alokasi.", status_code=422)
    cur.released_at = on
    project = await session.get(Project, cur.project_id)
    wo = await _new_wo(
        session,
        asset=asset.code,
        kind="inspection_post",
        title=f"Inspeksi pasca-pekerjaan {asset.code} ← {project.number if project else ''}",
        by=actor.id,
        checklist=DEFAULT_POST,
        project_id=cur.project_id,
        trigger="Selesai di proyek",
        due_date=on + timedelta(days=3),
    )
    await audit.record(
        session,
        action="release",
        entity_type="asset",
        entity_id=asset.id,
        actor_id=actor.id,
        after={"released_at": on},
    )
    return wo


# ---------------------------------------------------------------- work orders


async def create_corrective(
    session: AsyncSession, actor: Principal, asset: Asset, title: str, checklist: list[str]
) -> WorkOrder:
    alloc = await current_allocation(session, asset.code)
    return await _new_wo(
        session,
        asset=asset.code,
        kind="corrective",
        title=title,
        by=actor.id,
        checklist=checklist or ["Identifikasi penyebab", "Perbaikan", "Uji fungsi"],
        project_id=alloc.project_id if alloc else None,
        trigger="Dibuat manual",
        due_date=numbering.today_jakarta() + timedelta(days=2),
    )


@dataclass(frozen=True)
class WoUpdate:
    checklist: list[dict[str, Any]]
    labour_hours: Decimal
    result: str | None


def _require_open(wo: WorkOrder) -> None:
    if wo.status not in OPEN:
        raise ConflictError("WO_CLOSED", f"{wo.number} sudah selesai atau dibatalkan.")


async def update(session: AsyncSession, actor: Principal, wo: WorkOrder, u: WoUpdate) -> WorkOrder:
    _require_open(wo)
    items = [x["item"] for x in wo.checklist]
    if [x.get("item") for x in u.checklist] != items:
        raise AppError(
            "CHECKLIST_CHANGED",
            "Butir checklist tidak boleh diubah, hanya hasilnya.",
            status_code=422,
        )
    for x in u.checklist:
        if x.get("result") not in (None, "ok", "nok", "na"):
            raise AppError("RESULT_INVALID", "Hasil: OK, tidak OK, atau N/A.", status_code=422)
    wo.checklist = [
        {"item": x["item"], "result": x.get("result"), "note": (x.get("note") or None)}
        for x in u.checklist
    ]
    if u.labour_hours < 0:
        raise AppError("HOURS_INVALID", "Jam kerja tidak boleh negatif.", status_code=422)
    wo.labour_hours, wo.result = u.labour_hours, u.result
    if wo.status == "open":
        wo.status, wo.started_at = "in_progress", _now()
    await session.flush()
    return wo


async def issue_part(
    session: AsyncSession,
    actor: Principal,
    wo: WorkOrder,
    item_code: str,
    warehouse_code: str,
    qty: Decimal,
) -> WorkOrderPart:
    """Spare part from stock at moving-average cost: Dr 5200 / Cr 1310."""
    _require_open(wo)
    await stock.item(session, item_code)
    await stock.warehouse(session, warehouse_code)
    value = await stock.issue(
        session,
        item_code,
        warehouse_code,
        qty,
        stock.Doc(DOC, str(wo.id), wo.number, actor.id, wo.project_id),
    )
    part = WorkOrderPart(
        wo_id=wo.id, item_code=item_code, warehouse_code=warehouse_code, qty=qty, value=value
    )
    session.add(part)
    wo.parts_value += value
    if value > 0:
        await ledger.post_journal(
            session,
            entry_date=numbering.today_jakarta(),
            description=f"{wo.number} suku cadang {item_code} untuk {wo.asset_code}",
            lines=[
                ledger.JLine(MAINTENANCE_ACCOUNT, debit=value, asset=wo.asset_code, memo=wo.number),
                ledger.JLine(ledger.INVENTORY, credit=value, memo=wo.number),
            ],
            source_type=DOC,
            source_id=wo.id,
            source_number=wo.number,
            by=actor.id,
        )
    if wo.status == "open":
        wo.status, wo.started_at = "in_progress", _now()
    await session.flush()
    await audit.record(
        session,
        action="issue_part",
        entity_type=DOC,
        entity_id=wo.id,
        actor_id=actor.id,
        after={"item": item_code, "qty": qty, "value": value},
    )
    return part


async def complete(session: AsyncSession, actor: Principal, wo: WorkOrder, on: date) -> WorkOrder:
    """Sign off: every checklist item answered, a result written; PM resets its schedule."""
    _require_open(wo)
    if any(x.get("result") is None for x in wo.checklist):
        raise AppError(
            "CHECKLIST_INCOMPLETE",
            "Isi hasil semua butir checklist sebelum menyelesaikan WO.",
            status_code=422,
        )
    if not (wo.result or "").strip():
        raise AppError("RESULT_REQUIRED", "Tulis hasil pekerjaan.", status_code=422)
    wo.status, wo.completed_at, wo.completed_date = "done", _now(), on
    wo.signed_by, wo.signature_name = actor.id, actor.user.full_name
    if wo.task_code:
        s = (
            await session.execute(
                select(PmSchedule).where(
                    PmSchedule.asset_code == wo.asset_code, PmSchedule.task_code == wo.task_code
                )
            )
        ).scalar_one_or_none()
        task = (
            await session.execute(select(PmTask).where(PmTask.code == wo.task_code))
        ).scalar_one_or_none()
        if s is not None and task is not None:
            s.last_done_date, s.last_done_hours = on, await meter(session, wo.asset_code)
            if task.frequency == "hours" and task.interval_hours:
                s.next_due_hours = s.last_done_hours + task.interval_hours
            elif task.frequency in CALENDAR_DAYS:
                s.next_due_date = on + timedelta(days=CALENDAR_DAYS[task.frequency])
    await session.flush()
    await audit.record(
        session,
        action="complete",
        entity_type=DOC,
        entity_id=wo.id,
        actor_id=actor.id,
        after={"status": "done", "signed_by": wo.signature_name, "date": on},
    )
    return wo


async def cancel(session: AsyncSession, actor: Principal, wo: WorkOrder, reason: str) -> None:
    _require_open(wo)
    if len(reason.strip()) < 5:
        raise AppError("REASON_REQUIRED", "Tulis alasan pembatalan.", status_code=422)
    if wo.parts_value > 0:
        raise ConflictError("WO_HAS_PARTS", "WO sudah memakai suku cadang; selesaikan WO.")
    wo.status = "cancelled"
    wo.result = f"Dibatalkan: {reason.strip()}"
    await session.flush()


# ---------------------------------------------------------------- KPIs


async def kpis(session: AsyncSession, date_from: date, date_to: date) -> dict[str, Any]:
    """Utilisation = days on a project / days in period (target ≥ 85 %); downtime = downtime
    hours / period hours (< 3 %); PM compliance = PM WOs done by their due date / PM WOs due in
    the period; MTBF = operating hours / failures (corrective WOs); MTTR = downtime hours of
    corrective WOs / failures."""
    days = (date_to - date_from).days + 1
    assets = list(
        (await session.execute(select(Asset).where(Asset.is_active).order_by(Asset.code))).scalars()
    )
    usage = {
        code: (Decimal(d), Decimal(op))
        for code, d, op in (
            await session.execute(
                select(
                    AssetUsage.asset_code,
                    func.count(func.distinct(AssetUsage.usage_date)),
                    func.coalesce(func.sum(AssetUsage.operating), 0),
                )
                .where(AssetUsage.usage_date.between(date_from, date_to))
                .group_by(AssetUsage.asset_code)
            )
        ).tuples()
    }
    down = dict(
        (
            await session.execute(
                select(Downtime.asset_code, func.sum(Downtime.hours))
                .where(Downtime.start_date.between(date_from, date_to))
                .group_by(Downtime.asset_code)
            )
        )
        .tuples()
        .all()
    )
    failures = dict(
        (
            await session.execute(
                select(WorkOrder.asset_code, func.count())
                .where(
                    WorkOrder.kind == "corrective",
                    func.date(WorkOrder.created_at).between(date_from, date_to),
                    WorkOrder.status != "cancelled",
                )
                .group_by(WorkOrder.asset_code)
            )
        )
        .tuples()
        .all()
    )
    pm_due = list(
        (
            await session.execute(
                select(WorkOrder).where(
                    WorkOrder.kind == "preventive",
                    WorkOrder.status != "cancelled",
                    func.coalesce(WorkOrder.due_date, func.date(WorkOrder.created_at)).between(
                        date_from, date_to
                    ),
                )
            )
        ).scalars()
    )

    def pct(a: Decimal, b: Decimal) -> Decimal | None:
        return (a * 100 / b).quantize(Decimal("0.1")) if b > 0 else None

    rows = []
    tot_days = tot_op = tot_down = ZERO
    tot_fail = 0
    for a in assets:
        d, op = usage.get(a.code, (ZERO, ZERO))
        dh = Decimal(down.get(a.code) or 0)
        f = int(failures.get(a.code) or 0)
        tot_days, tot_op, tot_down, tot_fail = (
            tot_days + d,
            tot_op + op,
            tot_down + dh,
            tot_fail + f,
        )
        rows.append(
            {
                "asset_code": a.code,
                "name": a.name,
                "criticality": a.criticality,
                "days_used": d,
                "operating_hours": op,
                "downtime_hours": dh,
                "failures": f,
                "utilisation_pct": pct(d, Decimal(days)),
                "downtime_pct": pct(dh, Decimal(days * 24)),
                "mtbf_hours": (op / f).quantize(Decimal("0.1")) if f else None,
                "mttr_hours": (dh / f).quantize(Decimal("0.1")) if f else None,
            }
        )
    on_time = sum(
        1
        for w in pm_due
        if w.status == "done"
        and w.completed_date is not None
        and (w.due_date is None or w.completed_date <= w.due_date)
    )
    n = Decimal(len(assets) or 1)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "rows": rows,
        "totals": {
            "utilisation_pct": pct(tot_days, Decimal(days) * n),
            "downtime_pct": pct(tot_down, Decimal(days * 24) * n),
            "pm_due": len(pm_due),
            "pm_on_time": on_time,
            "pm_compliance_pct": pct(Decimal(on_time), Decimal(len(pm_due))),
            "mtbf_hours": (tot_op / tot_fail).quantize(Decimal("0.1")) if tot_fail else None,
            "mttr_hours": (tot_down / tot_fail).quantize(Decimal("0.1")) if tot_fail else None,
            "failures": tot_fail,
        },
        "targets": {"utilisation_pct": 85, "downtime_pct": 3},
    }
