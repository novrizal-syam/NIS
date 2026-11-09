"""DOR rules (PROCESS.md · Execution; prompt 05a).

Pricing (revenue, from the contract rate schedule):
  equipment  = operating/24 x rate + standby/24 x standby rate + breakdown/24 x breakdown rate
               (0 unless agreed) + rig-up/down/24 x rate
  personnel  = rate per person-day
  consumable = qty x cost x (1 + markup %)
Internal cost (management reporting, charged to the project budget):
  equipment  = asset internal day rate (EQUIP-OWN); personnel = price item unit cost (MANPOWER);
  consumable = moving-average stock cost of the site warehouse (CONSUMABLE).

Approval runs in the approval transaction: budget actuals per cost element, site stock issue,
journals (Dr 1220 / Cr 4100 revenue accrual, Dr 5300 / Cr 1310 consumables), asset hours, HSE
man-hours, payroll day records, contract usage (alert Head of Sales at >= 80 %). Internal
manpower/equipment costs reach the ledger through payroll and depreciation, not here.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.contract.models import Contract, ContractRate
from app.core.errors import AppError, ConflictError
from app.inventory import stock_service as stock
from app.master.models import Asset, Employee, Item, PriceItem
from app.notifications import service as notifications
from app.operations.models import (
    AssetUsage,
    Dor,
    DorConsumable,
    DorCrew,
    DorEquipment,
    HseDaily,
    PayrollDay,
)
from app.project.models import Project, ProjectWbs
from app.services import audit, ledger, numbering
from app.services import budget_control as bc
from app.services.audit import AuditAction
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest

DOC = "dor"
EDITABLE = ("draft", "returned")
ZERO = Decimal(0)
HOURS_PER_DAY = Decimal(24)
CERT_WARN_DAYS = 60
USAGE_ALERT_PCT = Decimal(80)
TEMPLATES_KEY = "dor.templates"
STATUS_LABELS = {
    "draft": "Draf",
    "submitted": "Menunggu persetujuan",
    "approved": "Disetujui",
    "returned": "Dikembalikan",
}
CE_EQUIPMENT, CE_MANPOWER, CE_CONSUMABLE = "EQUIP-OWN", "MANPOWER", "CONSUMABLE"

DEFAULT_TEMPLATES: dict[str, dict[str, Any]] = {
    "well_test": {
        "label": "Well testing",
        "fields": [
            {"key": "oil_rate", "label": "Laju minyak", "unit": "bbl/d"},
            {"key": "gas_rate", "label": "Laju gas", "unit": "MMSCFD"},
            {"key": "water_rate", "label": "Laju air", "unit": "bbl/d"},
            {"key": "whp", "label": "Tekanan kepala sumur (WHP)", "unit": "psi"},
            {"key": "separator_pressure", "label": "Tekanan separator", "unit": "psi"},
            {"key": "choke", "label": "Ukuran choke", "unit": "/64 in"},
            {"key": "bsw", "label": "BS&W", "unit": "%"},
        ],
    },
    "pumping": {
        "label": "Pumping",
        "fields": [
            {"key": "rate", "label": "Laju pompa", "unit": "bpm"},
            {"key": "pressure", "label": "Tekanan pompa", "unit": "psi"},
            {"key": "volume", "label": "Volume dipompa", "unit": "bbl"},
            {"key": "fluid", "label": "Fluida", "unit": "", "type": "text"},
        ],
    },
    "nitrogen": {
        "label": "Nitrogen",
        "fields": [
            {"key": "rate", "label": "Laju N2", "unit": "scfm"},
            {"key": "pressure", "label": "Tekanan", "unit": "psi"},
            {"key": "volume", "label": "Volume N2", "unit": "scf"},
        ],
    },
    "epf": {
        "label": "Early production facility",
        "fields": [
            {"key": "oil_rate", "label": "Laju minyak", "unit": "bbl/d"},
            {"key": "gas_rate", "label": "Laju gas", "unit": "MMSCFD"},
            {"key": "water_rate", "label": "Laju air", "unit": "bbl/d"},
            {"key": "export_pressure", "label": "Tekanan ekspor", "unit": "psi"},
        ],
    },
}


def rp(v: Decimal) -> Decimal:
    return v.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def _now() -> datetime:
    return datetime.now(UTC)


async def templates(session: AsyncSession) -> dict[str, dict[str, Any]]:
    value = await settings_store.get(session, TEMPLATES_KEY, None)
    return value if isinstance(value, dict) and value else DEFAULT_TEMPLATES


# ---------------------------------------------------------------- input


@dataclass(frozen=True)
class EquipmentIn:
    asset_code: str
    rate_id: uuid.UUID | None
    operating: Decimal
    standby: Decimal
    breakdown: Decimal
    rig: Decimal
    remark: str | None = None

    @property
    def total(self) -> Decimal:
        return self.operating + self.standby + self.breakdown + self.rig


@dataclass(frozen=True)
class CrewIn:
    employee_code: str
    rate_id: uuid.UUID | None
    hours: Decimal = Decimal(12)
    overtime_hours: Decimal = ZERO


@dataclass(frozen=True)
class ConsumableIn:
    item_code: str
    rate_id: uuid.UUID | None
    qty: Decimal


@dataclass(frozen=True)
class DorIn:
    report_date: date
    wbs_code: str = "EXEC"
    site_warehouse: str | None = None
    activities: str | None = None
    npt_hours: Decimal = ZERO
    npt_reason: str | None = None
    technical: dict[str, Any] = field(default_factory=dict)
    hse: dict[str, Any] = field(default_factory=dict)
    equipment: list[EquipmentIn] = field(default_factory=list)
    crew: list[CrewIn] = field(default_factory=list)
    consumables: list[ConsumableIn] = field(default_factory=list)


# ---------------------------------------------------------------- certificates


def cert_status(certs: list[dict[str, Any]], on: date) -> tuple[str | None, str | None]:
    """(blocking reason, warning) for mandatory certificates relative to `on`."""
    blocked: list[str] = []
    warn: list[str] = []
    for c in certs or []:
        if not c.get("mandatory", True) or not c.get("expiry_date"):
            continue
        exp = date.fromisoformat(str(c["expiry_date"]))
        if exp < on:
            blocked.append(f"{c.get('name')} kedaluwarsa {exp.isoformat()}")
        elif (exp - on).days <= CERT_WARN_DAYS:
            warn.append(f"{c.get('name')} berakhir {exp.isoformat()}")
    return ("; ".join(blocked) or None, "; ".join(warn) or None)


# ---------------------------------------------------------------- pricing


@dataclass
class Priced:
    equipment: list[tuple[Decimal, Decimal]]
    crew: list[tuple[Decimal, Decimal]]
    consumables: list[tuple[Decimal, Decimal]]

    def _sum(self, i: int) -> Decimal:
        return sum((x[i] for x in (*self.equipment, *self.crew, *self.consumables)), ZERO)

    @property
    def revenue(self) -> Decimal:
        return self._sum(0)

    @property
    def cost(self) -> Decimal:
        return self._sum(1)

    def cost_by_element(self) -> dict[str, Decimal]:
        return {
            CE_EQUIPMENT: sum((x[1] for x in self.equipment), ZERO),
            CE_MANPOWER: sum((x[1] for x in self.crew), ZERO),
            CE_CONSUMABLE: sum((x[1] for x in self.consumables), ZERO),
        }


async def _rates(session: AsyncSession, project: Project) -> dict[uuid.UUID, ContractRate]:
    if project.contract_id is None:
        return {}
    rows = await session.execute(
        select(ContractRate).where(ContractRate.contract_id == project.contract_id)
    )
    return {r.id: r for r in rows.scalars()}


def _rate(
    rates: dict[uuid.UUID, ContractRate], rate_id: uuid.UUID | None, kind: str
) -> ContractRate | None:
    if rate_id is None:
        return None
    r = rates.get(rate_id)
    if r is None or r.kind != kind:
        raise AppError(
            "RATE_INVALID",
            "Tarif tidak ada di kontrak proyek ini atau jenisnya salah.",
            status_code=422,
        )
    return r


def equipment_revenue(r: ContractRate | None, x: EquipmentIn) -> Decimal:
    if r is None:
        return ZERO
    return rp(
        (
            x.operating * r.rate
            + x.standby * (r.standby_rate or ZERO)
            + x.breakdown * (r.breakdown_rate or ZERO)
            + x.rig * r.rate
        )
        / HOURS_PER_DAY
    )


def consumable_revenue(r: ContractRate | None, qty: Decimal) -> Decimal:
    if r is None:
        return ZERO
    return rp(qty * (r.unit_cost or ZERO) * (1 + (r.markup_pct or ZERO) / 100))


async def price(session: AsyncSession, project: Project, data: DorIn, site: str | None) -> Priced:
    rates = await _rates(session, project)
    assets = {
        a.code: a
        for a in (
            await session.execute(
                select(Asset).where(Asset.code.in_([x.asset_code for x in data.equipment]))
            )
        ).scalars()
    }
    eq = []
    for x in data.equipment:
        r = _rate(rates, x.rate_id, "equipment")
        a = assets.get(x.asset_code)
        eq.append((equipment_revenue(r, x), a.internal_day_rate if a else ZERO))
    crew = []
    for c in data.crew:
        r = _rate(rates, c.rate_id, "personnel")
        cost = ZERO
        if r is not None and r.price_item_code:
            pi = (
                await session.execute(select(PriceItem).where(PriceItem.code == r.price_item_code))
            ).scalar_one_or_none()
            cost = pi.unit_cost if pi else ZERO
        crew.append((r.rate if r else ZERO, cost))
    cons = []
    for k in data.consumables:
        r = _rate(rates, k.rate_id, "consumable")
        avg = ZERO
        if site:
            bal = await stock.balance(session, k.item_code, site, lock=False)
            avg = stock.avg_cost(bal)
        cons.append((consumable_revenue(r, k.qty), rp(k.qty * avg)))
    return Priced(eq, crew, cons)


# ---------------------------------------------------------------- validation


async def validate(
    session: AsyncSession, project: Project, data: DorIn, *, exclude_dor: uuid.UUID | None
) -> tuple[list[str], list[str]]:
    """(errors that block submission, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    if data.report_date > numbering.today_jakarta():
        errors.append("Tanggal laporan tidak boleh di masa depan.")
    if not (data.activities or "").strip():
        errors.append("Isi ringkasan aktivitas.")
    if data.npt_hours < 0 or data.npt_hours > HOURS_PER_DAY:
        errors.append("NPT harus antara 0 dan 24 jam.")
    if data.npt_hours > 0 and not (data.npt_reason or "").strip():
        errors.append("Tulis penyebab NPT.")
    seen: set[str] = set()
    for x in data.equipment:
        if x.asset_code in seen:
            errors.append(f"Unit {x.asset_code} tercatat dua kali.")
        seen.add(x.asset_code)
        if min(x.operating, x.standby, x.breakdown, x.rig) < 0:
            errors.append(f"Jam unit {x.asset_code} tidak boleh negatif.")
        if x.total != HOURS_PER_DAY:
            errors.append(
                f"Unit {x.asset_code}: operasi + standby + breakdown + rig-up/down = "
                f"{x.total.normalize():f} jam; harus 24."
            )
    errors += await _selection_errors(session, data, warnings)
    # Consumables <= site stock.
    if data.consumables and not data.site_warehouse:
        errors.append("Pilih gudang site untuk pemakaian material.")
    need: dict[str, Decimal] = {}
    for k in data.consumables:
        if k.qty <= 0:
            errors.append(f"Jumlah {k.item_code} harus > 0.")
        need[k.item_code] = need.get(k.item_code, ZERO) + k.qty
    if data.site_warehouse:
        for code, qty in need.items():
            have = await stock.on_hand(session, code, data.site_warehouse)
            if qty > have:
                errors.append(
                    f"Pemakaian {code} {qty.normalize():f} melebihi stok site "
                    f"{data.site_warehouse} ({have.normalize():f})."
                )
    # A person is paid one site day per date (another project's DOR may hold it).
    codes = [c.employee_code for c in data.crew]
    if len(set(codes)) != len(codes):
        errors.append("Personel tercatat dua kali.")
    if codes:
        other = await session.execute(
            select(DorCrew.employee_code, Dor.number)
            .join(Dor, Dor.id == DorCrew.dor_id)
            .where(
                Dor.report_date == data.report_date,
                Dor.status.in_(("submitted", "approved")),
                DorCrew.employee_code.in_(codes),
                *([Dor.id != exclude_dor] if exclude_dor else []),
            )
        )
        for code, number in other.tuples():
            errors.append(f"{code} sudah tercatat di {number} pada tanggal yang sama.")
    return errors, warnings


async def _selection_errors(session: AsyncSession, data: DorIn, warnings: list[str]) -> list[str]:
    """Mobilisation gate: expired mandatory certificates cannot be selected."""
    errors: list[str] = []
    if data.equipment:
        rows = await session.execute(
            select(Asset).where(Asset.code.in_([x.asset_code for x in data.equipment]))
        )
        found = {a.code: a for a in rows.scalars()}
        for x in data.equipment:
            a = found.get(x.asset_code)
            if a is None or not a.is_active:
                errors.append(f"Unit {x.asset_code} tidak ditemukan atau tidak aktif.")
                continue
            block, warn = cert_status(a.certificates, data.report_date)
            if block:
                errors.append(f"Unit {a.code} tidak dapat dipilih: {block}.")
            if warn:
                warnings.append(f"Unit {a.code}: {warn}.")
    if data.crew:
        rows2 = await session.execute(
            select(Employee).where(Employee.code.in_([c.employee_code for c in data.crew]))
        )
        people = {e.code: e for e in rows2.scalars()}
        for c in data.crew:
            e = people.get(c.employee_code)
            if e is None or not e.is_active:
                errors.append(f"Personel {c.employee_code} tidak ditemukan atau tidak aktif.")
                continue
            block, warn = cert_status(e.certificates, data.report_date)
            if block:
                errors.append(f"{e.full_name} tidak dapat dipilih: {block}.")
            if warn:
                warnings.append(f"{e.full_name}: {warn}.")
    if data.consumables:
        codes = {k.item_code for k in data.consumables}
        known = set(
            (await session.execute(select(Item.code).where(Item.code.in_(codes)))).scalars()
        )
        errors += [f"Item {c} tidak ditemukan." for c in sorted(codes - known)]
    return errors


# ---------------------------------------------------------------- save (online or sync)


async def _wbs(session: AsyncSession, project: Project, code: str) -> ProjectWbs:
    w = (
        await session.execute(
            select(ProjectWbs).where(ProjectWbs.project_id == project.id, ProjectWbs.code == code)
        )
    ).scalar_one_or_none()
    if w is None:
        raise AppError("WBS_INVALID", f"WBS {code} tidak ada di proyek ini.", status_code=422)
    return w


async def save(
    session: AsyncSession,
    actor: Principal,
    project: Project,
    client_id: uuid.UUID,
    base_version: int | None,
    data: DorIn,
) -> Dor:
    """Create or update a draft. Idempotent by `client_id`; `base_version` must equal the
    stored version (otherwise someone else changed it: VERSION_CONFLICT)."""
    if project.status != "locked":
        raise AppError(
            "PROJECT_NOT_LOCKED",
            f"DOR hanya untuk proyek terkunci ({project.number}).",
            status_code=422,
        )
    dor = (
        await session.execute(select(Dor).where(Dor.client_id == client_id).with_for_update())
    ).scalar_one_or_none()
    wbs = await _wbs(session, project, data.wbs_code)
    if data.site_warehouse:
        await stock.warehouse(session, data.site_warehouse)
    warnings: list[str] = []
    sel_errors = await _selection_errors(session, data, warnings)
    if sel_errors:
        raise AppError("SELECTION_BLOCKED", " ".join(sel_errors), status_code=422)
    priced = await price(session, project, data, data.site_warehouse)
    if dor is None:
        clash = await session.execute(
            select(Dor.number).where(
                Dor.project_id == project.id, Dor.report_date == data.report_date
            )
        )
        if (n := clash.scalar_one_or_none()) is not None:
            raise ConflictError(
                "DOR_EXISTS", f"DOR {project.number} tanggal {data.report_date} sudah ada ({n})."
            )
        dor = Dor(
            number=await numbering.next(session, "DOR"),
            client_id=client_id,
            version=1,
            project_id=project.id,
            wbs_id=wbs.id,
            report_date=data.report_date,
            status="draft",
            created_by=actor.id,
            is_demo=project.is_demo,
        )
        session.add(dor)
        action: str = AuditAction.CREATE
    else:
        if dor.project_id != project.id:
            raise ConflictError("DOR_PROJECT", "DOR ini milik proyek lain.")
        if dor.status not in EDITABLE:
            raise ConflictError(
                "DOR_NOT_EDITABLE", f"{dor.number} sudah diajukan; tidak dapat diubah."
            )
        if base_version is not None and base_version != dor.version:
            raise ConflictError(
                "VERSION_CONFLICT",
                f"{dor.number} sudah diubah di perangkat lain (versi {dor.version}). "
                "Muat versi server lalu ulangi perubahan Anda.",
            )
        dor.version += 1
        action = AuditAction.UPDATE
    dor.wbs_id, dor.report_date = wbs.id, data.report_date
    dor.site_warehouse = data.site_warehouse
    dor.activities, dor.npt_hours, dor.npt_reason = data.activities, data.npt_hours, data.npt_reason
    dor.technical, dor.hse = data.technical, data.hse
    dor.revenue, dor.internal_cost = priced.revenue, priced.cost
    await session.flush()
    for model in (DorEquipment, DorCrew, DorConsumable):
        await session.execute(delete(model).where(model.dor_id == dor.id))
    for x, (rev, cost) in zip(data.equipment, priced.equipment, strict=True):
        session.add(
            DorEquipment(
                dor_id=dor.id,
                asset_code=x.asset_code,
                rate_id=x.rate_id,
                operating=x.operating,
                standby=x.standby,
                breakdown=x.breakdown,
                rig=x.rig,
                remark=x.remark,
                revenue=rev,
                internal_cost=cost,
            )
        )
    for c, (rev, cost) in zip(data.crew, priced.crew, strict=True):
        session.add(
            DorCrew(
                dor_id=dor.id,
                employee_code=c.employee_code,
                rate_id=c.rate_id,
                hours=c.hours,
                overtime_hours=c.overtime_hours,
                revenue=rev,
                internal_cost=cost,
            )
        )
    for k, (rev, cost) in zip(data.consumables, priced.consumables, strict=True):
        session.add(
            DorConsumable(
                dor_id=dor.id,
                item_code=k.item_code,
                rate_id=k.rate_id,
                qty=k.qty,
                revenue=rev,
                internal_cost=cost,
            )
        )
    await session.flush()
    await audit.record(
        session,
        action=action,
        entity_type=DOC,
        entity_id=dor.id,
        actor_id=actor.id,
        after={"number": dor.number, "version": dor.version, "revenue": dor.revenue},
    )
    return dor


async def load(session: AsyncSession, dor: Dor) -> DorIn:
    wbs = await session.get(ProjectWbs, dor.wbs_id)
    assert wbs is not None

    async def rows(model: Any) -> list[Any]:
        return list((await session.execute(select(model).where(model.dor_id == dor.id))).scalars())

    return DorIn(
        report_date=dor.report_date,
        wbs_code=wbs.code,
        site_warehouse=dor.site_warehouse,
        activities=dor.activities,
        npt_hours=dor.npt_hours,
        npt_reason=dor.npt_reason,
        technical=dor.technical,
        hse=dor.hse,
        equipment=[
            EquipmentIn(
                x.asset_code, x.rate_id, x.operating, x.standby, x.breakdown, x.rig, x.remark
            )
            for x in await rows(DorEquipment)
        ],
        crew=[
            CrewIn(c.employee_code, c.rate_id, c.hours, c.overtime_hours)
            for c in await rows(DorCrew)
        ],
        consumables=[
            ConsumableIn(k.item_code, k.rate_id, k.qty) for k in await rows(DorConsumable)
        ],
    )


# ---------------------------------------------------------------- submit / approve


def deadline(report_date: date) -> datetime:
    """Approval due before 08:00 WIB the next day."""
    return datetime.combine(report_date + timedelta(days=1), time(8, 0), numbering.JAKARTA)


async def submit(session: AsyncSession, actor: Principal, dor: Dor) -> ApprovalRequest:
    if dor.status not in EDITABLE:
        raise ConflictError("ILLEGAL_TRANSITION", f"{dor.number} tidak dapat diajukan.")
    project = await session.get(Project, dor.project_id)
    assert project is not None
    errors, _ = await validate(session, project, await load(session, dor), exclude_dor=dor.id)
    if errors:
        raise AppError("DOR_INVALID", " ".join(errors), status_code=422)
    request = await engine.submit(
        session,
        actor,
        doc_type=DOC,
        doc_id=dor.id,
        doc_number=dor.number,
        title=f"DOR {project.number} {dor.report_date.isoformat()}",
        amount=dor.revenue,
        context={"service_line": project.service_line, "project": project.number},
        project_id=project.id,
    )
    before = dor.status
    dor.status, dor.request_id, dor.return_reason = "submitted", request.id, None
    dor.submitted_at, dor.submitted_by = _now(), actor.id
    dor.late = dor.submitted_at > deadline(dor.report_date)
    await session.flush()
    await audit.record(
        session,
        action="submit",
        entity_type=DOC,
        entity_id=dor.id,
        actor_id=actor.id,
        before={"status": before},
        after={"status": "submitted", "late": dor.late},
    )
    return request


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    dor = await session.get(Dor, uuid.UUID(request.doc_id), with_for_update=True)
    if dor is None or dor.status != "submitted":
        return
    acted = [s.acted_by for s in request.steps if s.acted_by]
    await apply_approval(session, dor, acted[-1] if acted else None)


async def apply_approval(session: AsyncSession, dor: Dor, by: uuid.UUID | None) -> None:
    project = await session.get(Project, dor.project_id)
    assert project is not None
    doc = stock.Doc(DOC, str(dor.id), dor.number, by, project.id)
    dims: dict[str, Any] = {"project_id": project.id, "wbs_id": dor.wbs_id}

    # 1. Site stock issue at moving-average cost (replaces the estimate).
    cons = list(
        (
            await session.execute(select(DorConsumable).where(DorConsumable.dor_id == dor.id))
        ).scalars()
    )
    stock_value = ZERO
    for k in cons:
        assert dor.site_warehouse is not None
        k.internal_cost = await stock.issue(session, k.item_code, dor.site_warehouse, k.qty, doc)
        stock_value += k.internal_cost
    equipment = list(
        (await session.execute(select(DorEquipment).where(DorEquipment.dor_id == dor.id))).scalars()
    )
    crew = list((await session.execute(select(DorCrew).where(DorCrew.dor_id == dor.id))).scalars())
    by_element = {
        CE_EQUIPMENT: sum((x.internal_cost for x in equipment), ZERO),
        CE_MANPOWER: sum((c.internal_cost for c in crew), ZERO),
        CE_CONSUMABLE: stock_value,
    }
    dor.internal_cost = sum(by_element.values(), ZERO)

    # 2. Project actuals per cost element (hard stop above available, CLAUDE.md rule 8).
    for ce, amount in by_element.items():
        if amount > 0:
            await bc.actualize(
                session,
                bc.Line(project.id, dor.wbs_id, ce),
                amount,
                doc_type=DOC,
                doc_id=str(dor.id),
                by=by,
                note=dor.number,
            )

    # 3. Journals: revenue accrual and consumables.
    client = project.client_code
    today = numbering.today_jakarta()
    if dor.revenue > 0:
        entry = await ledger.post_journal(
            session,
            entry_date=dor.report_date if dor.report_date <= today else today,
            description=f"{dor.number} pendapatan {project.number}",
            lines=[
                ledger.JLine(
                    "1220", debit=dor.revenue, partner_type="client", partner_code=client, **dims
                ),
                ledger.JLine(
                    "4100", credit=dor.revenue, partner_type="client", partner_code=client, **dims
                ),
            ],
            source_type=DOC,
            source_id=dor.id,
            source_number=dor.number,
            by=by,
            is_demo=dor.is_demo,
        )
        dor.revenue_journal_id = entry.id
    if stock_value > 0:
        entry = await ledger.post_journal(
            session,
            entry_date=dor.report_date if dor.report_date <= today else today,
            description=f"{dor.number} pemakaian material {project.number}",
            lines=[
                ledger.JLine(
                    ledger.CONSUMABLES, debit=stock_value, cost_element=CE_CONSUMABLE, **dims
                ),
                ledger.JLine(ledger.INVENTORY, credit=stock_value),
            ],
            source_type=DOC,
            source_id=dor.id,
            source_number=dor.number,
            by=by,
            is_demo=dor.is_demo,
        )
        dor.stock_journal_id = entry.id

    # 4. Asset hours, HSE statistics, payroll days.
    for x in equipment:
        session.add(
            AssetUsage(
                asset_code=x.asset_code,
                usage_date=dor.report_date,
                project_id=project.id,
                dor_id=dor.id,
                operating=x.operating,
                standby=x.standby,
                breakdown=x.breakdown,
                rig=x.rig,
            )
        )
    hse = dor.hse or {}

    def _int(k: str) -> int:
        try:
            return max(int(hse.get(k) or 0), 0)
        except (TypeError, ValueError):
            return 0

    manhours = sum((c.hours + c.overtime_hours for c in crew), ZERO)
    session.add(
        HseDaily(
            project_id=project.id,
            report_date=dor.report_date,
            dor_id=dor.id,
            manhours=manhours,
            incidents=_int("incidents"),
            near_misses=_int("near_misses"),
            unsafe_acts=_int("unsafe_acts"),
            toolbox_talks=_int("toolbox_talks"),
        )
    )
    for c in crew:
        session.add(
            PayrollDay(
                employee_code=c.employee_code,
                work_date=dor.report_date,
                project_id=project.id,
                dor_id=dor.id,
                hours=c.hours,
                overtime_hours=c.overtime_hours,
            )
        )

    # 5. Contract usage and the 80 % alert.
    if project.contract_id and dor.revenue > 0:
        contract = await session.get(Contract, project.contract_id, with_for_update=True)
        assert contract is not None
        before_pct = _pct(contract.used_value, contract.value)
        contract.used_value += dor.revenue
        after_pct = _pct(contract.used_value, contract.value)
        if before_pct < USAGE_ALERT_PCT <= after_pct:
            users = await engine.holders_of_role(session, "head_of_sales")
            await notifications.notify(
                session,
                users,
                kind="contract_usage",
                title=f"Pemakaian kontrak {contract.number} mencapai {after_pct}%",
                body=f"{project.number}: terpakai {contract.used_value} dari {contract.value}.",
                link=f"/kontrak/{contract.id}",
                dedupe_key=f"contract-usage-80-{contract.id}",
            )

    dor.status, dor.approved_at = "approved", _now()
    dor.late = dor.late or dor.approved_at > deadline(dor.report_date)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.APPROVE,
        entity_type=DOC,
        entity_id=dor.id,
        actor_id=by,
        after={
            "revenue": dor.revenue,
            "internal_cost": dor.internal_cost,
            "stock_issue": stock_value,
            "late": dor.late,
        },
    )


def _pct(used: Decimal, value: Decimal) -> Decimal:
    return (used * 100 / value).quantize(Decimal("0.1")) if value > 0 else ZERO


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    dor = await session.get(Dor, uuid.UUID(request.doc_id), with_for_update=True)
    if dor is None or dor.status != "submitted":
        return
    acted = [s for s in request.steps if s.acted_by]
    dor.status, dor.request_id = "returned", None
    dor.return_reason = (acted[-1].comment if acted else None) or None
    await session.flush()


engine.register_document(DOC, on_approved=_on_approved, on_rejected=_on_rejected)


async def count_by_status(
    session: AsyncSession, project_ids: list[uuid.UUID] | None
) -> dict[str, int]:
    stmt = select(Dor.status, func.count()).group_by(Dor.status)
    if project_ids is not None:
        stmt = stmt.where(Dor.project_id.in_(project_ids))
    return dict((await session.execute(stmt)).tuples().all())
