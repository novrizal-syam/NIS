"""Monthly depreciation run (07d).

Commercial (PSAK 216, straight line): (cost - salvage) / useful life per month, never below
salvage; posted Dr 6200 (office) or Dr 5200 with the project the equipment is allocated to at
month end (equipment types = project equipment), Cr 1590, asset dimension on every line.
Fiscal (PMK 72/2023, straight line by group): cost x group rate / 12, kept beside the commercial
figure for the fiscal correction report; not posted.
"""

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import ConflictError
from app.maintenance.models import AssetAllocation
from app.master.models import Asset
from app.services import audit, ledger
from app.tax.models import DepreciationRun

ZERO = Decimal(0)
# Annual straight-line rate per fiscal group (PMK 72/2023 jo. UU PPh art. 11).
FISCAL_RATES = {
    "kelompok_1": Decimal("25"),
    "kelompok_2": Decimal("12.5"),
    "kelompok_3": Decimal("6.25"),
    "kelompok_4": Decimal("5"),
    "bangunan_permanen": Decimal("5"),
    "bangunan_tidak_permanen": Decimal("10"),
}


def _rp(v: Decimal) -> Decimal:
    return v.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def commercial(asset: Asset) -> Decimal:
    if not asset.useful_life_months or asset.acquisition_cost <= 0:
        return ZERO
    base = Decimal(asset.acquisition_cost) - Decimal(asset.salvage_value)
    left = base - Decimal(asset.accumulated_depreciation)
    if left <= 0:
        return ZERO
    return min(_rp(base / asset.useful_life_months), left)


def fiscal(asset: Asset) -> Decimal:
    rate = FISCAL_RATES.get(asset.tax_group or "")
    if rate is None or asset.acquisition_cost <= 0:
        return ZERO
    left = Decimal(asset.acquisition_cost) - Decimal(asset.accumulated_tax_depreciation)
    if left <= 0:
        return ZERO
    return min(_rp(Decimal(asset.acquisition_cost) * rate / 100 / 12), left)


async def run(session: AsyncSession, actor: Principal, year: int, month: int) -> DepreciationRun:
    if (
        await session.execute(
            select(DepreciationRun.id).where(
                DepreciationRun.year == year, DepreciationRun.month == month
            )
        )
    ).first():
        raise ConflictError("DEPRECIATION_DONE", f"Penyusutan {month:02d}/{year} sudah dijalankan.")
    end = date(year, month, calendar.monthrange(year, month)[1])
    assets = list(
        (
            await session.execute(
                select(Asset)
                .where(
                    Asset.is_active.is_(True),
                    Asset.depreciation_start.is_not(None),
                    Asset.depreciation_start <= end,
                )
                .order_by(Asset.code)
                .with_for_update()
            )
        ).scalars()
    )
    allocated = dict(
        (
            await session.execute(
                select(AssetAllocation.asset_code, AssetAllocation.project_id).where(
                    AssetAllocation.start_date <= end,
                    (AssetAllocation.released_at.is_(None)) | (AssetAllocation.released_at > end),
                )
            )
        )
        .tuples()
        .all()
    )
    lines: list[dict[str, Any]] = []
    parts: list[ledger.Part] = []
    total = fiscal_total = ZERO
    for a in assets:
        c, f = commercial(a), fiscal(a)
        if c == 0 and f == 0:
            continue
        project = allocated.get(a.code)
        role = "project" if a.equipment_type_code else "office"
        if c > 0:
            parts.append(
                ledger.Part(role, c, ledger.Dims(asset=a.code, project_id=project), a.code)
            )
            parts.append(ledger.Part("accumulated", c, ledger.Dims(asset=a.code), a.code))
        a.accumulated_depreciation = Decimal(a.accumulated_depreciation) + c
        a.accumulated_tax_depreciation = Decimal(a.accumulated_tax_depreciation) + f
        total += c
        fiscal_total += f
        lines.append(
            {
                "asset": a.code,
                "name": a.name,
                "commercial": format(c, "f"),
                "fiscal": format(f, "f"),
                "account": "5200" if role == "project" else "6200",
                "project_id": str(project) if project and role == "project" else None,
                "book_value": format(
                    Decimal(a.acquisition_cost) - Decimal(a.accumulated_depreciation), "f"
                ),
            }
        )
    dr = DepreciationRun(
        year=year,
        month=month,
        total=total,
        fiscal_total=fiscal_total,
        lines=lines,
        created_by=actor.id,
    )
    if total > 0:
        entry = await ledger.post_parts(
            session,
            "depreciation",
            parts,
            entry_date=end,
            description=f"Penyusutan {month:02d}/{year} ({len(lines)} aset)",
            source_type="depreciation",
            source_id=f"{year}-{month:02d}",
            source_number=f"DEP-{year}-{month:02d}",
            by=actor.id,
        )
        dr.journal_id = entry.id
    session.add(dr)
    await session.flush()
    await audit.record(
        session,
        action="post",
        entity_type="depreciation_run",
        entity_id=dr.id,
        actor_id=actor.id,
        after={"period": f"{year}-{month:02d}", "total": total, "fiscal": fiscal_total},
    )
    return dr


async def fiscal_report(session: AsyncSession, year: int) -> dict[str, Any]:
    """Commercial vs fiscal depreciation per asset for the year (fiscal correction)."""
    runs = list(
        (
            await session.execute(
                select(DepreciationRun)
                .where(DepreciationRun.year == year)
                .order_by(DepreciationRun.month)
            )
        ).scalars()
    )
    per: dict[str, dict[str, Any]] = {}
    for r in runs:
        for x in r.lines:
            row = per.setdefault(
                x["asset"],
                {"asset": x["asset"], "name": x.get("name"), "commercial": ZERO, "fiscal": ZERO},
            )
            row["commercial"] += Decimal(x["commercial"])
            row["fiscal"] += Decimal(x["fiscal"])
    rows = []
    for row in per.values():
        diff = row["commercial"] - row["fiscal"]
        rows.append(
            {
                **row,
                "commercial": format(row["commercial"], "f"),
                "fiscal": format(row["fiscal"], "f"),
                # Positive: commercial above fiscal -> positive fiscal correction.
                "correction": format(diff, "f"),
            }
        )
    tc = sum((Decimal(r["commercial"]) for r in rows), ZERO)
    tf = sum((Decimal(r["fiscal"]) for r in rows), ZERO)
    return {
        "year": year,
        "months": [r.month for r in runs],
        "rows": rows,
        "summary": {
            "commercial": format(tc, "f"),
            "fiscal": format(tf, "f"),
            "correction": format(tc - tf, "f"),
        },
    }
