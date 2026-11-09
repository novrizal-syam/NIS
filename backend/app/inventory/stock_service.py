"""Stock per item per warehouse at moving-average cost.

Receipt: qty += q, value += cost. Issue: value out = q x (value / qty), rounded to the rupiah;
issuing the last unit takes the whole remaining value, so no rupiah is ever stranded and the
stock value always equals what was posted to 1310. Every change locks the balance row
(SELECT ... FOR UPDATE) and writes an append-only stock move.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.inventory.models import (
    StockBalance,
    StockCount,
    StockCountLine,
    StockMove,
    StockTransfer,
    StockTransferLine,
)
from app.master.models import Item, Warehouse
from app.services import audit, ledger, numbering
from app.services.audit import AuditAction
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest

COUNT_DOC = "stock_opname"
TRANSFER_DOC = "stock_transfer"
VARIANCE_KEY = "inventory.variance_account"
DEFAULT_VARIANCE_ACCOUNT = "6100"
ZERO = Decimal(0)


def rp(v: Decimal) -> Decimal:
    return v.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def avg_cost(bal: StockBalance) -> Decimal:
    return (bal.value / bal.qty).quantize(Decimal("0.01")) if bal.qty > 0 else ZERO


async def warehouse(session: AsyncSession, code: str) -> Warehouse:
    wh = (
        await session.execute(select(Warehouse).where(Warehouse.code == code))
    ).scalar_one_or_none()
    if wh is None or not wh.is_active:
        raise AppError(
            "WAREHOUSE_INVALID", f"Gudang {code} tidak ditemukan atau tidak aktif.", status_code=422
        )
    return wh


async def item(session: AsyncSession, code: str) -> Item:
    it = (await session.execute(select(Item).where(Item.code == code))).scalar_one_or_none()
    if it is None or not it.is_active:
        raise AppError(
            "ITEM_INVALID", f"Item {code} tidak ditemukan atau tidak aktif.", status_code=422
        )
    return it


async def balance(
    session: AsyncSession, item_code: str, wh_code: str, *, lock: bool = True
) -> StockBalance:
    await session.execute(
        insert(StockBalance)
        .values(item_code=item_code, warehouse_code=wh_code, qty=0, value=0)
        .on_conflict_do_nothing(constraint="uq_stock_item_warehouse")
    )
    stmt = select(StockBalance).where(
        StockBalance.item_code == item_code, StockBalance.warehouse_code == wh_code
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt.execution_options(populate_existing=True))).scalar_one()


@dataclass(frozen=True)
class Doc:
    type: str
    id: str
    number: str | None
    by: uuid.UUID | None
    project_id: uuid.UUID | None = None


def _move(bal: StockBalance, kind: str, qty: Decimal, value: Decimal, doc: Doc) -> StockMove:
    return StockMove(
        item_code=bal.item_code,
        warehouse_code=bal.warehouse_code,
        kind=kind,
        qty=qty,
        value=value,
        qty_after=bal.qty,
        value_after=bal.value,
        doc_type=doc.type,
        doc_id=doc.id,
        doc_number=doc.number,
        project_id=doc.project_id,
        by=doc.by,
    )


async def receive(
    session: AsyncSession,
    item_code: str,
    wh_code: str,
    qty: Decimal,
    value: Decimal,
    doc: Doc,
    *,
    kind: str = "receipt",
) -> StockBalance:
    if qty <= 0 or value < 0:
        raise AppError("QTY_INVALID", "Kuantitas masuk harus > 0.", status_code=422)
    bal = await balance(session, item_code, wh_code)
    bal.qty += qty
    bal.value += rp(value)
    session.add(_move(bal, kind, qty, rp(value), doc))
    await session.flush()
    return bal


async def issue(
    session: AsyncSession,
    item_code: str,
    wh_code: str,
    qty: Decimal,
    doc: Doc,
    *,
    kind: str = "issue",
) -> Decimal:
    """Take `qty` out at moving-average cost; returns the value taken."""
    bal = await balance(session, item_code, wh_code)
    if qty <= 0:
        raise AppError("QTY_INVALID", "Kuantitas keluar harus > 0.", status_code=422)
    if qty > bal.qty:
        raise ConflictError(
            "STOCK_INSUFFICIENT",
            f"Stok {item_code} di {wh_code} hanya {bal.qty.normalize():f}; "
            f"tidak cukup untuk {qty.normalize():f}.",
        )
    value = bal.value if qty == bal.qty else rp(qty * bal.value / bal.qty)
    bal.qty -= qty
    bal.value -= value
    session.add(_move(bal, kind, -qty, -value, doc))
    await session.flush()
    return value


async def on_hand(session: AsyncSession, item_code: str, wh_code: str) -> Decimal:
    row = (
        await session.execute(
            select(StockBalance.qty).where(
                StockBalance.item_code == item_code, StockBalance.warehouse_code == wh_code
            )
        )
    ).scalar_one_or_none()
    return row if row is not None else ZERO


# ---------------------------------------------------------------- transfers


@dataclass(frozen=True)
class QtyLine:
    item_code: str
    qty: Decimal


async def transfer(
    session: AsyncSession,
    actor: Principal,
    *,
    from_wh: str,
    to_wh: str,
    lines: list[QtyLine],
    note: str | None,
) -> StockTransfer:
    """Move stock between warehouses (typically Base Cilegon -> project site) at average cost.
    Inventory stays on 1310, so no journal is needed."""
    if from_wh == to_wh:
        raise AppError("SAME_WAREHOUSE", "Gudang asal dan tujuan harus berbeda.", status_code=422)
    await warehouse(session, from_wh)
    await warehouse(session, to_wh)
    if not lines:
        raise AppError("LINES_REQUIRED", "Isi minimal satu baris.", status_code=422)
    tr = StockTransfer(
        number=await numbering.next(session, "TRF"),
        from_warehouse=from_wh,
        to_warehouse=to_wh,
        note=note,
        created_by=actor.id,
    )
    session.add(tr)
    await session.flush()
    doc = Doc(TRANSFER_DOC, str(tr.id), tr.number, actor.id)
    total = ZERO
    # Lock in a stable order so two transfers cannot deadlock.
    for x in sorted(lines, key=lambda x: x.item_code):
        await item(session, x.item_code)
        value = await issue(session, x.item_code, from_wh, x.qty, doc, kind="transfer_out")
        await receive(session, x.item_code, to_wh, x.qty, value, doc, kind="transfer_in")
        session.add(
            StockTransferLine(transfer_id=tr.id, item_code=x.item_code, qty=x.qty, value=value)
        )
        total += value
    tr.value = total
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=TRANSFER_DOC,
        entity_id=tr.id,
        actor_id=actor.id,
        after={"number": tr.number, "from": from_wh, "to": to_wh, "value": total},
    )
    return tr


# ---------------------------------------------------------------- stock opname


@dataclass(frozen=True)
class CountLine:
    item_code: str
    counted_qty: Decimal
    reason: str | None = None


async def count_lines(session: AsyncSession, count_id: uuid.UUID) -> list[StockCountLine]:
    rows = await session.execute(
        select(StockCountLine)
        .where(StockCountLine.count_id == count_id)
        .order_by(StockCountLine.item_code)
    )
    return list(rows.scalars())


async def create_count(
    session: AsyncSession,
    actor: Principal,
    *,
    wh_code: str,
    count_date: date,
    lines: list[CountLine],
    note: str | None,
) -> StockCount:
    """Record counted quantities; the system quantity and average cost are snapshotted now."""
    await warehouse(session, wh_code)
    if not lines:
        raise AppError("LINES_REQUIRED", "Isi minimal satu baris hitung.", status_code=422)
    if len({x.item_code for x in lines}) != len(lines):
        raise AppError("DUPLICATE_ITEM", "Setiap item hanya boleh satu baris.", status_code=422)
    sc = StockCount(
        number=await numbering.next(session, "SOP"),
        warehouse_code=wh_code,
        count_date=count_date,
        status="draft",
        note=note,
        created_by=actor.id,
    )
    session.add(sc)
    await session.flush()
    total = ZERO
    for x in lines:
        it = await item(session, x.item_code)
        if x.counted_qty < 0:
            raise AppError("QTY_INVALID", "Jumlah hitung tidak boleh negatif.", status_code=422)
        bal = await balance(session, x.item_code, wh_code, lock=False)
        delta = x.counted_qty - bal.qty
        unit = avg_cost(bal) if bal.qty > 0 else Decimal(it.last_price or 0)
        if delta == 0:
            variance = ZERO
        elif x.counted_qty == 0:
            variance = -bal.value
        else:
            variance = rp(delta * unit)
        if delta != 0 and not (x.reason or "").strip():
            raise AppError(
                "REASON_REQUIRED",
                f"Tulis alasan selisih untuk {x.item_code}.",
                status_code=422,
            )
        session.add(
            StockCountLine(
                count_id=sc.id,
                item_code=x.item_code,
                system_qty=bal.qty,
                counted_qty=x.counted_qty,
                unit_cost=rp(unit),
                variance_value=variance,
                reason=(x.reason or "").strip() or None,
            )
        )
        total += variance
    sc.variance_value = total
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=COUNT_DOC,
        entity_id=sc.id,
        actor_id=actor.id,
        after={"number": sc.number, "warehouse": wh_code, "variance": total},
    )
    return sc


async def submit_count(session: AsyncSession, actor: Principal, sc: StockCount) -> None:
    """No variance: closed at once. Any variance: Lead Controller approves first."""
    if sc.status not in ("draft", "rejected"):
        raise ConflictError("ILLEGAL_TRANSITION", f"{sc.number} tidak dapat diajukan lagi.")
    lines = await count_lines(session, sc.id)
    before = sc.status
    if all(x.counted_qty == x.system_qty for x in lines):
        sc.status = "approved"
    else:
        gross = sum((abs(x.variance_value) for x in lines), ZERO)
        request = await engine.submit(
            session,
            actor,
            doc_type=COUNT_DOC,
            doc_id=sc.id,
            doc_number=sc.number,
            title=f"Selisih stock opname {sc.warehouse_code}",
            amount=gross,
            context={"warehouse": sc.warehouse_code, "net_variance": str(sc.variance_value)},
        )
        sc.status, sc.request_id, sc.reject_reason = "awaiting_approval", request.id, None
    await session.flush()
    await audit.record(
        session,
        action="submit",
        entity_type=COUNT_DOC,
        entity_id=sc.id,
        actor_id=actor.id,
        before={"status": before},
        after={"status": sc.status},
    )


async def _apply_count(session: AsyncSession, sc: StockCount, by: uuid.UUID | None) -> None:
    """Adjust stock by the approved variance and post it (shortage Dr variance / Cr 1310;
    surplus Dr 1310 / Cr variance)."""
    doc = Doc(COUNT_DOC, str(sc.id), sc.number, by)
    loss = gain = ZERO
    for x in await count_lines(session, sc.id):
        delta = x.counted_qty - x.system_qty
        if delta < 0:
            bal = await balance(session, x.item_code, sc.warehouse_code)
            take = min(-delta, bal.qty)  # stock may have moved since the count
            if take > 0:
                loss += await issue(
                    session, x.item_code, sc.warehouse_code, take, doc, kind="adjustment"
                )
        elif delta > 0:
            value = rp(delta * x.unit_cost)
            await receive(
                session, x.item_code, sc.warehouse_code, delta, value, doc, kind="adjustment"
            )
            gain += value
    account = str(await settings_store.get(session, VARIANCE_KEY, DEFAULT_VARIANCE_ACCOUNT))
    lines: list[ledger.JLine] = []
    memo = f"Stock opname {sc.number}"
    if loss > 0:
        lines += [
            ledger.JLine(account, debit=loss, memo=memo),
            ledger.JLine(ledger.INVENTORY, credit=loss, memo=memo),
        ]
    if gain > 0:
        lines += [
            ledger.JLine(ledger.INVENTORY, debit=gain, memo=memo),
            ledger.JLine(account, credit=gain, memo=memo),
        ]
    if lines:
        entry = await ledger.post_journal(
            session,
            entry_date=numbering.today_jakarta(),
            description=f"Selisih stock opname {sc.number} ({sc.warehouse_code})",
            lines=lines,
            source_type=COUNT_DOC,
            source_id=sc.id,
            source_number=sc.number,
            by=by,
            is_demo=sc.is_demo,
        )
        sc.journal_id = entry.id
    sc.variance_value = gain - loss
    await session.flush()


async def _on_count_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    sc = await session.get(StockCount, uuid.UUID(request.doc_id), with_for_update=True)
    if sc is None or sc.status != "awaiting_approval":
        return
    sc.status = "approved"
    await _apply_count(session, sc, None)
    await audit.record(
        session,
        action=AuditAction.APPROVE,
        entity_type=COUNT_DOC,
        entity_id=sc.id,
        actor_id=None,
        after={"status": "approved", "variance": sc.variance_value},
    )


async def _on_count_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    sc = await session.get(StockCount, uuid.UUID(request.doc_id), with_for_update=True)
    if sc is None or sc.status != "awaiting_approval":
        return
    acted = [s for s in request.steps if s.acted_by]
    comment = acted[-1].comment if acted else None
    sc.status, sc.request_id = ("rejected" if request.status == "rejected" else "draft"), None
    sc.reject_reason = (comment or "")[:1000] or None
    await session.flush()


engine.register_document(COUNT_DOC, on_approved=_on_count_approved, on_rejected=_on_count_rejected)


# ---------------------------------------------------------------- reports


async def reorder_suggestions(session: AsyncSession) -> list[dict[str, Any]]:
    """Items at or below their reorder point across all warehouses; suggest refilling to twice
    the reorder point at the last purchase price."""
    sums = await session.execute(
        select(StockBalance.item_code, func.sum(StockBalance.qty)).group_by(StockBalance.item_code)
    )
    on_hand: dict[str, Decimal] = {code: Decimal(q) for code, q in sums.tuples()}
    out: list[dict[str, Any]] = []
    items = await session.execute(
        select(Item).where(Item.is_active, Item.reorder_point > 0).order_by(Item.code)
    )
    for it in items.scalars():
        have = Decimal(on_hand.get(it.code) or 0)
        if have <= it.reorder_point:
            qty = it.reorder_point * 2 - have
            out.append(
                {
                    "item_code": it.code,
                    "name": it.name,
                    "uom": it.uom,
                    "on_hand": have,
                    "reorder_point": it.reorder_point,
                    "suggested_qty": qty,
                    "last_price": it.last_price,
                    "est_value": rp(qty * (it.last_price or 0)),
                }
            )
    return out


async def valuation(session: AsyncSession) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(StockBalance, Item.name, Item.uom)
            .join(Item, Item.code == StockBalance.item_code)
            .where((StockBalance.qty != 0) | (StockBalance.value != 0))
            .order_by(StockBalance.warehouse_code, StockBalance.item_code)
        )
    ).all()
    total = sum((b.value for b, _, _ in rows), ZERO)
    gl = await ledger.balance(session, ledger.INVENTORY)
    return {
        "rows": [
            {
                "warehouse_code": b.warehouse_code,
                "item_code": b.item_code,
                "name": name,
                "uom": uom,
                "qty": b.qty,
                "avg_cost": avg_cost(b),
                "value": b.value,
            }
            for b, name, uom in rows
        ],
        "total": total,
        "ledger_1310": gl,
        "difference": total - gl,
        "reconciled": total == gl,
    }
