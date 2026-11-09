"""Importer for GEK_PM_Plan_Peralatan.xlsx (sheets "Task Library" and "Equipment Register").

Columns are found by header name (Indonesian or English, case-insensitive), so column order
does not matter. Every row is validated first; when any row is wrong nothing is written and
the errors are returned with sheet and row number. Rows are upserted by code.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError
from app.maintenance.models import PmTask
from app.master.models import Asset, EquipmentType
from app.services import audit

TASK_SHEET = "task library"
ASSET_SHEET = "equipment register"

TASK_COLS = {
    "code": ("kode tugas", "task code", "kode", "code", "task id"),
    "type": ("jenis peralatan", "equipment type", "tipe peralatan", "jenis"),
    "title": ("tugas", "task", "deskripsi tugas", "task description", "uraian"),
    "frequency": ("frekuensi", "frequency"),
    "interval": ("interval jam", "interval hours", "interval (jam)", "jam"),
    "form": ("formulir", "form", "form code", "kode formulir"),
    "checklist": ("checklist", "daftar periksa", "langkah", "steps"),
    "est": ("estimasi jam", "est hours", "estimated hours", "durasi (jam)"),
}
ASSET_COLS = {
    "code": ("kode aset", "asset code", "kode", "code", "tag"),
    "name": ("nama", "name", "nama peralatan", "equipment name", "deskripsi"),
    "type": ("jenis peralatan", "equipment type", "jenis", "tipe"),
    "criticality": ("kritikalitas", "criticality"),
    "serial": ("no. seri", "no seri", "serial no", "serial number"),
    "location": ("lokasi", "location"),
    "rate": ("tarif internal", "internal rate", "tarif internal / hari", "internal day rate"),
    "cert": ("sertifikat", "certificate"),
    "expiry": ("berlaku s.d.", "berlaku sampai", "expiry", "expiry date", "masa berlaku"),
}
FREQ = {
    "harian": "daily", "daily": "daily",
    "mingguan": "weekly", "weekly": "weekly",
    "bulanan": "monthly", "monthly": "monthly",
    "tahunan": "annual", "annual": "annual", "yearly": "annual",
    "per job": "per_job", "per pekerjaan": "per_job", "per_job": "per_job", "per-job": "per_job",
    "jam operasi": "hours", "operating hours": "hours", "hours": "hours", "jam": "hours",
}  # fmt: skip


@dataclass
class ImportResult:
    tasks_created: int = 0
    tasks_updated: int = 0
    assets_created: int = 0
    assets_updated: int = 0
    errors: list[str] = field(default_factory=list)


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


def _columns(header: tuple[Any, ...], spec: dict[str, tuple[str, ...]]) -> dict[str, int]:
    names = [_norm(h) for h in header]
    out: dict[str, int] = {}
    for key, aliases in spec.items():
        for a in aliases:
            if a in names:
                out[key] = names.index(a)
                break
    return out


def _rows(wb: Any, sheet: str, spec: dict[str, tuple[str, ...]], required: tuple[str, ...]):  # type: ignore[no-untyped-def]
    ws = next((wb[n] for n in wb.sheetnames if _norm(n) == sheet), None)
    if ws is None:
        return None, [f"Sheet '{sheet.title()}' tidak ditemukan."]
    it = ws.iter_rows(values_only=True)
    header = next(it, None)
    if header is None:
        return [], []
    cols = _columns(header, spec)
    missing = [k for k in required if k not in cols]
    if missing:
        return None, [f"Sheet '{ws.title}': kolom wajib tidak ada: {', '.join(missing)}."]
    rows = []
    for i, r in enumerate(it, start=2):
        if not any(c not in (None, "") for c in r):
            continue
        rows.append((i, {k: (r[c] if c < len(r) else None) for k, c in cols.items()}))
    return rows, []


def _frequency(raw: Any) -> tuple[str | None, int | None]:
    """'Bulanan' -> monthly; '250 jam' / '250 hours' -> hours, 250."""
    text = _norm(raw)
    m = re.match(r"^(\d+)\s*(jam|hours?|hrs?)$", text)
    if m:
        return "hours", int(m.group(1))
    return FREQ.get(text), None


def _decimal(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return (
            Decimal(str(v).replace(".", "").replace(",", "."))
            if isinstance(v, str)
            else Decimal(str(v))
        )
    except InvalidOperation:
        return None


async def run(session: AsyncSession, actor: Principal, data: bytes) -> ImportResult:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise AppError(
            "XLSX_INVALID", "Berkas bukan Excel (.xlsx) yang valid.", status_code=422
        ) from exc
    res = ImportResult()
    types = {t.code: t for t in (await session.execute(select(EquipmentType))).scalars()}
    by_name = {_norm(t.name): t.code for t in types.values()}

    def type_code(raw: Any) -> str | None:
        v = str(raw or "").strip()
        return v if v in types else by_name.get(_norm(v))

    tasks, errs = _rows(wb, TASK_SHEET, TASK_COLS, ("code", "type", "title", "frequency"))
    res.errors += errs
    assets, errs = _rows(wb, ASSET_SHEET, ASSET_COLS, ("code", "name", "type"))
    if assets is None and tasks is not None:
        assets, errs = [], []  # the equipment register is optional
    res.errors += errs
    parsed_tasks = []
    for row, r in tasks or []:
        code = str(r["code"] or "").strip()
        t = type_code(r["type"])
        freq, hours = _frequency(r["frequency"])
        if hours is None and r.get("interval") not in (None, ""):
            try:
                hours = int(Decimal(str(r["interval"])))
            except InvalidOperation:
                hours = None
        where = f"Task Library baris {row}"
        if not code:
            res.errors.append(f"{where}: kode tugas kosong.")
        if t is None:
            res.errors.append(f"{where}: jenis peralatan '{r['type']}' tidak dikenal.")
        if freq is None:
            res.errors.append(f"{where}: frekuensi '{r['frequency']}' tidak dikenal.")
        if freq == "hours" and not hours:
            res.errors.append(f"{where}: frekuensi jam operasi perlu interval jam.")
        items = [x.strip() for x in re.split(r"[;\n]", str(r.get("checklist") or "")) if x.strip()]
        parsed_tasks.append(
            (
                code,
                t,
                str(r["title"] or "").strip(),
                freq,
                hours,
                r.get("form"),
                items,
                _decimal(r.get("est")),
            )
        )
    parsed_assets = []
    for row, r in assets or []:
        where = f"Equipment Register baris {row}"
        code = str(r["code"] or "").strip()
        t = type_code(r["type"])
        crit = str(r.get("criticality") or "C").strip().upper()[:1]
        if not code or not str(r["name"] or "").strip():
            res.errors.append(f"{where}: kode dan nama wajib.")
        if t is None:
            res.errors.append(f"{where}: jenis peralatan '{r['type']}' tidak dikenal.")
        if crit not in ("A", "B", "C"):
            res.errors.append(f"{where}: kritikalitas harus A, B, atau C.")
        expiry = r.get("expiry")
        if isinstance(expiry, datetime):
            expiry = expiry.date()
        elif expiry not in (None, "") and not isinstance(expiry, date):
            try:
                expiry = date.fromisoformat(str(expiry).strip())
            except ValueError:
                res.errors.append(f"{where}: tanggal berlaku '{expiry}' tidak valid (YYYY-MM-DD).")
                expiry = None
        parsed_assets.append((code, str(r["name"] or "").strip(), t, crit, r, expiry))
    if res.errors:
        return res

    existing = {t.code: t for t in (await session.execute(select(PmTask))).scalars()}
    for code, t, title, freq, hours, form, items, est in parsed_tasks:
        task = existing.get(code)
        if task is None:
            task = PmTask(code=code, created_by=actor.id)
            session.add(task)
            res.tasks_created += 1
        else:
            res.tasks_updated += 1
        task.equipment_type_code = t  # type: ignore[assignment]
        task.title = title[:200]
        task.frequency = freq  # type: ignore[assignment]
        task.interval_hours = hours if freq == "hours" else None
        task.form_code = (str(form).strip() or None) if form else None
        task.checklist = items
        task.est_hours = est
        task.is_active = True
    have = {a.code: a for a in (await session.execute(select(Asset))).scalars()}
    for code, name, t, crit, r, expiry in parsed_assets:
        a = have.get(code)
        if a is None:
            a = Asset(code=code, asset_class=types[t].name if t else "-", created_by=actor.id)
            session.add(a)
            res.assets_created += 1
        else:
            res.assets_updated += 1
        a.name, a.equipment_type_code, a.criticality = name, t, crit
        if r.get("serial"):
            a.serial_no = str(r["serial"]).strip()
        if r.get("location"):
            a.location = str(r["location"]).strip()
        if (rate := _decimal(r.get("rate"))) is not None:
            a.internal_day_rate = rate
        if r.get("cert"):
            certs = [c for c in (a.certificates or []) if c.get("name") != str(r["cert"]).strip()]
            certs.append(
                {
                    "name": str(r["cert"]).strip(),
                    "number": None,
                    "expiry_date": expiry.isoformat() if isinstance(expiry, date) else None,
                    "mandatory": True,
                }
            )
            a.certificates = certs
    await session.flush()
    await audit.record(
        session,
        action="import",
        entity_type="pm_plan",
        entity_id="GEK_PM_Plan",
        actor_id=actor.id,
        after={k: v for k, v in res.__dict__.items() if k != "errors"},
    )
    return res
