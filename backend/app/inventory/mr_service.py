"""Material request by a Field Engineer (PROCESS.md; ACCOUNTING.md · Material issue).

For each line: take what the project site warehouse has, then what Base has; the issued part is
charged to the project at once (budget actual + Dr 5300 / Cr 1310 with project dimensions).
What neither warehouse can cover becomes one PR at each item's last price, created and submitted
in the engineer's name so the 04a rules apply (budget check -> blocked, or DOA approval).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError
from app.inventory import stock_service as stock
from app.inventory.models import MaterialRequest, MaterialRequestLine
from app.master.models import Warehouse
from app.procurement import pr_service
from app.services import audit, ledger, numbering
from app.services import budget_control as bc
from app.services.audit import AuditAction

DOC = "material_request"
ZERO = Decimal(0)
STATUS_LABELS = {
    "issued": "Dikeluarkan dari stok",
    "partial": "Sebagian dikeluarkan, sisanya PR",
    "pr_created": "Seluruhnya jadi PR",
}


@dataclass(frozen=True)
class LineIn:
    item_code: str
    qty: Decimal


async def lines_of(session: AsyncSession, mr_id: uuid.UUID) -> list[MaterialRequestLine]:
    rows = await session.execute(
        select(MaterialRequestLine)
        .where(MaterialRequestLine.mr_id == mr_id)
        .order_by(MaterialRequestLine.seq)
    )
    return list(rows.scalars())


async def _base_warehouse(session: AsyncSession) -> Warehouse:
    wh = (
        await session.execute(
            select(Warehouse)
            .where(Warehouse.kind == "base", Warehouse.is_active)
            .order_by(Warehouse.code)
            .limit(1)
        )
    ).scalar_one_or_none()
    if wh is None:
        raise AppError("NO_BASE_WAREHOUSE", "Gudang base belum didefinisikan.", status_code=422)
    return wh


async def create(
    session: AsyncSession,
    actor: Principal,
    *,
    project_id: uuid.UUID,
    wbs_code: str,
    cost_element_code: str,
    site_warehouse: str,
    need_date: date,
    purpose: str | None,
    lines: list[LineIn],
) -> MaterialRequest:
    # Same header rules as a PR: locked project, WBS of the project, no Contingency.
    project, wbs = await pr_service._validate_header(
        session, project_id, wbs_code, cost_element_code
    )
    site = await stock.warehouse(session, site_warehouse)
    if site.kind != "site":
        raise AppError(
            "NOT_SITE_WAREHOUSE", f"{site.code} bukan gudang site proyek.", status_code=422
        )
    base = await _base_warehouse(session)
    if not lines:
        raise AppError("LINES_REQUIRED", "Isi minimal satu baris.", status_code=422)
    if len({x.item_code for x in lines}) != len(lines):
        raise AppError("DUPLICATE_ITEM", "Setiap item hanya boleh satu baris.", status_code=422)
    items = {}
    for x in lines:
        if x.qty <= 0:
            raise AppError("QTY_INVALID", "Kuantitas harus lebih dari 0.", status_code=422)
        items[x.item_code] = await stock.item(session, x.item_code)

    mr = MaterialRequest(
        number=await numbering.next(session, "MR"),
        project_id=project.id,
        wbs_id=wbs.id,
        cost_element_code=cost_element_code,
        site_warehouse=site.code,
        base_warehouse=base.code,
        requester_id=actor.id,
        need_date=need_date,
        purpose=purpose,
        status="issued",
        created_by=actor.id,
        is_demo=project.is_demo,
    )
    session.add(mr)
    await session.flush()
    doc = stock.Doc(DOC, str(mr.id), mr.number, actor.id, project.id)
    issued = ZERO
    shortfalls: list[pr_service.LineIn] = []
    for seq, x in enumerate(lines, start=1):
        need = x.qty
        site_qty = min(need, await _available(session, x.item_code, site.code))
        base_qty = min(need - site_qty, await _available(session, x.item_code, base.code))
        value = ZERO
        if site_qty > 0:
            value += await stock.issue(session, x.item_code, site.code, site_qty, doc)
        if base_qty > 0:
            value += await stock.issue(session, x.item_code, base.code, base_qty, doc)
        short = need - site_qty - base_qty
        session.add(
            MaterialRequestLine(
                mr_id=mr.id,
                seq=seq,
                item_code=x.item_code,
                qty=need,
                from_site=site_qty,
                from_base=base_qty,
                shortfall=short,
                value=value,
            )
        )
        issued += value
        if short > 0:
            it = items[x.item_code]
            shortfalls.append(
                pr_service.LineIn(
                    item_code=it.code,
                    description=it.name,
                    qty=short,
                    uom=it.uom,
                    est_price=Decimal(it.last_price or 0),
                )
            )
    mr.issued_value = issued
    await session.flush()

    if issued > 0:
        line = bc.Line(project.id, wbs.id, cost_element_code)
        await bc.actualize(
            session, line, issued, doc_type=DOC, doc_id=str(mr.id), by=actor.id, note=mr.number
        )
        entry = await ledger.post_event(
            session,
            "material_issue",
            {"issued": issued},
            entry_date=numbering.today_jakarta(),
            description=f"{mr.number} pengeluaran material {project.number}",
            source_type=DOC,
            source_id=mr.id,
            source_number=mr.number,
            by=actor.id,
            dims=ledger.Dims(project_id=project.id, wbs_id=wbs.id, cost_element=cost_element_code),
            memo=mr.number,
            is_demo=mr.is_demo,
        )
        mr.journal_id = entry.id

    if shortfalls:
        if any(x.est_price <= 0 for x in shortfalls):
            raise AppError(
                "NO_LAST_PRICE",
                "Item kekurangan belum punya harga terakhir; minta Procurement melengkapi "
                "harga di Data Master.",
                status_code=422,
            )
        pr = await pr_service.create(
            session,
            actor,
            project_id=project.id,
            wbs_code=wbs.code,
            cost_element_code=cost_element_code,
            need_date=need_date,
            delivery_location=f"{site.name} ({site.code})",
            purpose=f"Kekurangan stok {mr.number}" + (f": {purpose}" if purpose else ""),
            lines=shortfalls,
        )
        await pr_service.submit(session, actor, pr)
        mr.pr_id = pr.id
        mr.status = "partial" if issued > 0 or _any_issued(lines, shortfalls) else "pr_created"
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=mr.id,
        actor_id=actor.id,
        after={"number": mr.number, "status": mr.status, "issued_value": issued},
    )
    return mr


def _any_issued(lines: list[LineIn], shortfalls: list[pr_service.LineIn]) -> bool:
    """Something was issued even if at zero cost (e.g. free stock)."""
    short = {x.item_code: x.qty for x in shortfalls}
    return any(short.get(x.item_code, ZERO) < x.qty for x in lines)


async def _available(session: AsyncSession, item_code: str, wh_code: str) -> Decimal:
    return (await stock.balance(session, item_code, wh_code)).qty
