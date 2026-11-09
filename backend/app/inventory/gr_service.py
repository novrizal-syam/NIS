"""Goods / service receipt against an issued PO (PROCESS.md · GR; ACCOUNTING.md).

draft --post (needs a photo or BAST attachment)--> posted
draft --cancel--> cancelled

Who: goods (PO has item-coded lines) by the Warehouse Head (inventory create); services by the
project owner (project manager). Partial receipts are allowed; quantities never exceed what the
PO still has open. When everything is received the PO is closed and any commitment it still
holds (rounding) is released.

Posting, in one transaction:
- direct to project (services, or goods not put into a warehouse): budget commit -> actual
  (consuming the PO commitment); Dr expense of the cost element / Cr 2120 GR/IR.
- stock items received into a warehouse: Dr 1310 / Cr 2120 and moving-average update. The PO
  commitment for these lines is released, not actualised: the project is charged when the
  material is issued (MR / DOR, actual + 5300/1310), so the cost is never counted twice.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError, ForbiddenError
from app.dms.models import Attachment
from app.inventory import stock_service as stock
from app.inventory.models import GoodsReceipt, GoodsReceiptLine
from app.procurement import po_service
from app.procurement.models import PurchaseOrder, PurchaseOrderLine
from app.project.models import Project
from app.services import audit, ledger, numbering
from app.services import budget_control as bc
from app.services.audit import AuditAction

DOC = "goods_receipt"
ZERO = Decimal(0)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class LineIn:
    seq: int
    qty: Decimal


async def lines_of(session: AsyncSession, gr_id: uuid.UUID) -> list[GoodsReceiptLine]:
    rows = await session.execute(
        select(GoodsReceiptLine)
        .where(GoodsReceiptLine.gr_id == gr_id)
        .order_by(GoodsReceiptLine.po_line_seq)
    )
    return list(rows.scalars())


async def received_by_seq(session: AsyncSession, po_id: uuid.UUID) -> dict[int, Decimal]:
    """Quantity already received (posted GRs) per PO line seq."""
    rows = await session.execute(
        select(GoodsReceiptLine.po_line_seq, func.sum(GoodsReceiptLine.qty))
        .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.gr_id)
        .where(GoodsReceipt.po_id == po_id, GoodsReceipt.status == "posted")
        .group_by(GoodsReceiptLine.po_line_seq)
    )
    return {seq: Decimal(q) for seq, q in rows.all()}


def kind_of(po_lines: list[PurchaseOrderLine]) -> str:
    return "goods" if any(x.item_code for x in po_lines) else "service"


async def may_receive(session: AsyncSession, actor: Principal, po: PurchaseOrder) -> bool:
    kind = kind_of(await po_service.lines_of(session, po.id))
    if kind == "goods":
        return actor.can("inventory", "create")
    project = await session.get(Project, po.project_id)
    return project is not None and project.manager_id == actor.id


async def _require_receiver(session: AsyncSession, actor: Principal, po: PurchaseOrder) -> None:
    if not await may_receive(session, actor, po):
        kind = kind_of(await po_service.lines_of(session, po.id))
        who = "Kepala Gudang" if kind == "goods" else "pemilik proyek (manajer proyek)"
        raise ForbiddenError("GR_NOT_ALLOWED", f"Penerimaan PO ini dilakukan oleh {who}.")


async def create(
    session: AsyncSession,
    actor: Principal,
    po: PurchaseOrder,
    *,
    received_date: date,
    warehouse_code: str | None,
    delivery_note: str | None,
    note: str | None,
    lines: list[LineIn],
) -> GoodsReceipt:
    if po.status != "issued":
        raise ConflictError(
            "PO_NOT_OPEN", f"{po.number} tidak dalam status terbit; tidak dapat diterima."
        )
    await _require_receiver(session, actor, po)
    if received_date > numbering.today_jakarta():
        raise AppError(
            "DATE_IN_FUTURE", "Tanggal terima tidak boleh di masa depan.", status_code=422
        )
    po_lines = {x.seq: x for x in await po_service.lines_of(session, po.id)}
    kind = kind_of(list(po_lines.values()))
    if warehouse_code:
        if kind != "goods":
            raise AppError(
                "WAREHOUSE_NOT_FOR_SERVICE", "Penerimaan jasa tidak masuk gudang.", status_code=422
            )
        await stock.warehouse(session, warehouse_code)
    picked = [x for x in lines if x.qty > 0]
    if not picked:
        raise AppError(
            "LINES_REQUIRED", "Isi kuantitas diterima minimal satu baris.", status_code=422
        )
    if len({x.seq for x in picked}) != len(picked):
        raise AppError("DUPLICATE_LINE", "Setiap baris PO hanya sekali per GR.", status_code=422)
    done = await received_by_seq(session, po.id)
    gr = GoodsReceipt(
        number=await numbering.next(session, "GR"),
        po_id=po.id,
        kind=kind,
        status="draft",
        received_date=received_date,
        warehouse_code=warehouse_code or None,
        delivery_note=delivery_note,
        note=note,
        created_by=actor.id,
        is_demo=po.is_demo,
    )
    session.add(gr)
    await session.flush()
    total = ZERO
    for x in sorted(picked, key=lambda x: x.seq):
        pl = po_lines.get(x.seq)
        if pl is None:
            raise AppError("PO_LINE_INVALID", f"Baris PO {x.seq} tidak ada.", status_code=422)
        _check_open(pl, done.get(pl.seq, ZERO), x.qty)
        amount = stock.rp(x.qty * pl.unit_price)
        session.add(
            GoodsReceiptLine(
                gr_id=gr.id,
                po_line_seq=pl.seq,
                item_code=pl.item_code,
                description=pl.description,
                qty=x.qty,
                uom=pl.uom,
                unit_price=pl.unit_price,
                amount=amount,
                to_stock=bool(warehouse_code and pl.item_code),
            )
        )
        total += amount
    gr.amount = total
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=gr.id,
        actor_id=actor.id,
        after={"number": gr.number, "po": po.number, "amount": total, "kind": kind},
    )
    return gr


def _check_open(pl: PurchaseOrderLine, received: Decimal, qty: Decimal) -> None:
    open_qty = pl.qty - received
    if qty > open_qty:
        raise AppError(
            "QTY_EXCEEDS_PO",
            f"Baris {pl.seq} ({pl.description}): sisa yang belum diterima "
            f"{open_qty.normalize():f} {pl.uom}; tidak dapat menerima {qty.normalize():f}.",
            status_code=422,
        )


async def _attachment_count(session: AsyncSession, gr: GoodsReceipt) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Attachment)
                .where(
                    Attachment.entity_type == DOC,
                    Attachment.entity_id == str(gr.id),
                    Attachment.archived_at.is_(None),
                )
            )
        ).scalar_one()
    )


async def post(session: AsyncSession, actor: Principal, gr: GoodsReceipt) -> GoodsReceipt:
    if gr.status != "draft":
        raise ConflictError("GR_NOT_DRAFT", f"{gr.number} sudah diposting atau dibatalkan.")
    po = await session.get(PurchaseOrder, gr.po_id, with_for_update=True)
    assert po is not None
    if po.status != "issued":
        raise ConflictError("PO_NOT_OPEN", f"{po.number} tidak dalam status terbit.")
    await _require_receiver(session, actor, po)
    if await _attachment_count(session, gr) == 0:
        what = "foto barang atau surat jalan" if gr.kind == "goods" else "BAST"
        raise AppError(
            "EVIDENCE_REQUIRED", f"Lampirkan {what} sebelum memposting GR.", status_code=422
        )
    po_lines = {x.seq: x for x in await po_service.lines_of(session, po.id)}
    done = await received_by_seq(session, po.id)
    lines = await lines_of(session, gr.id)
    for x in lines:  # re-check under the PO lock: parallel GRs cannot over-receive
        pl = po_lines.get(x.po_line_seq)
        if pl is None:
            raise ConflictError("PO_LINE_GONE", f"Baris PO {x.po_line_seq} tidak ada lagi.")
        _check_open(pl, done.get(pl.seq, ZERO), x.qty)

    budget_line = po_service.line_of(po)
    direct = sum((x.amount for x in lines if not x.to_stock), ZERO)
    to_stock = sum((x.amount for x in lines if x.to_stock), ZERO)
    if direct > 0:
        await bc.actualize(
            session,
            budget_line,
            direct,
            doc_type=DOC,
            doc_id=str(gr.id),
            by=actor.id,
            from_doc=(po_service.DOC, str(po.id)),
            note=gr.number,
        )
    if to_stock > 0:
        held = (await bc.held(session, budget_line, po_service.DOC, str(po.id)))["commit"]
        await bc.release(
            session,
            budget_line,
            min(held, to_stock),
            bucket="commit",
            doc_type=po_service.DOC,
            doc_id=str(po.id),
            by=actor.id,
            note=f"{gr.number} masuk stok {gr.warehouse_code}",
        )
        doc = stock.Doc(DOC, str(gr.id), gr.number, actor.id)
        for x in lines:
            if x.to_stock and x.item_code and gr.warehouse_code:
                await stock.receive(session, x.item_code, gr.warehouse_code, x.qty, x.amount, doc)

    jl: list[ledger.JLine] = []
    if direct > 0:
        jl.append(
            ledger.JLine(
                await ledger.expense_account(session, po.cost_element_code),
                debit=direct,
                cost_element=po.cost_element_code,
                memo=po.number,
                project_id=po.project_id,
                wbs_id=po.wbs_id,
                partner_type="vendor",
                partner_code=po.vendor_code,
            )
        )
    if to_stock > 0:
        jl.append(
            ledger.JLine(
                ledger.INVENTORY,
                debit=to_stock,
                memo=po.number,
                partner_type="vendor",
                partner_code=po.vendor_code,
            )
        )
    jl.append(
        ledger.JLine(
            ledger.GR_IR,
            credit=direct + to_stock,
            memo=po.number,
            project_id=po.project_id,
            wbs_id=po.wbs_id,
            partner_type="vendor",
            partner_code=po.vendor_code,
        )
    )
    entry = await ledger.post_journal(
        session,
        entry_date=gr.received_date,
        description=f"{gr.number} penerimaan {po.number}",
        lines=jl,
        source_type=DOC,
        source_id=gr.id,
        source_number=gr.number,
        by=actor.id,
        is_demo=gr.is_demo,
    )
    gr.status, gr.posted_at, gr.posted_by, gr.journal_id = "posted", _now(), actor.id, entry.id
    await session.flush()

    done = await received_by_seq(session, po.id)
    fully = all(done.get(seq, ZERO) >= pl.qty for seq, pl in po_lines.items())
    if fully:
        po.status = "closed"
        await bc.release(
            session,
            budget_line,
            None,
            bucket="commit",
            doc_type=po_service.DOC,
            doc_id=str(po.id),
            by=actor.id,
            note=f"{po.number} diterima penuh",
        )
        await audit.record(
            session,
            action="status_change",
            entity_type=po_service.DOC,
            entity_id=po.id,
            actor_id=actor.id,
            before={"status": "issued"},
            after={"status": "closed", "gr": gr.number},
        )
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.POST,
        entity_type=DOC,
        entity_id=gr.id,
        actor_id=actor.id,
        after={
            "number": gr.number,
            "direct": direct,
            "to_stock": to_stock,
            "journal": entry.number,
            "po_closed": fully,
        },
    )
    return gr


async def cancel(session: AsyncSession, actor: Principal, gr: GoodsReceipt) -> None:
    if gr.status != "draft":
        raise ConflictError(
            "GR_NOT_DRAFT", f"{gr.number} sudah diposting; koreksi dengan dokumen pembalik."
        )
    po = await session.get(PurchaseOrder, gr.po_id)
    assert po is not None
    await _require_receiver(session, actor, po)
    gr.status = "cancelled"
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type=DOC,
        entity_id=gr.id,
        actor_id=actor.id,
        before={"status": "draft"},
        after={"status": "cancelled"},
    )
