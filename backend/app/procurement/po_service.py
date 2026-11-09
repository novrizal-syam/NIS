"""Purchase order (PROCESS.md · PO): from the RFQ award; issue moves the budget from the PR's
pre-commitment to the PO's commitment (savings return to available); a revision with a higher
value needs re-approval (DOA po_revision)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.dms import service as dms
from app.master.models import Vendor
from app.procurement import po_pdf, pr_service, rfq_service
from app.procurement.models import (
    PriceHistory,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    Rfq,
)
from app.project.models import Project
from app.services import audit, letterhead, numbering
from app.services import budget_control as bc
from app.services.audit import AuditAction
from app.services.storage import Storage, current_storage
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest, ApprovalStep

DOC = "purchase_order"
PPN_KEY = "tax.ppn_effective_pct"
DEFAULT_PPN = 11  # PPN 12 % x DPP nilai lain 11/12 (ACCOUNTING.md)
PENALTY_CLAUSE = (
    "Keterlambatan pengiriman dikenakan denda 0,1% (satu permil) dari nilai PO per hari "
    "keterlambatan, maksimal 5% dari nilai PO, dan dapat dipotong dari pembayaran."
)


def _now() -> datetime:
    return datetime.now(UTC)


def _rp(v: Decimal) -> Decimal:
    return v.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def line_of(po: PurchaseOrder) -> bc.Line:
    return bc.Line(po.project_id, po.wbs_id, po.cost_element_code)


@dataclass(frozen=True)
class LineIn:
    seq: int
    item_code: str | None
    description: str
    qty: Decimal
    uom: str
    unit_price: Decimal


async def ppn_pct(session: AsyncSession) -> Decimal:
    return Decimal(str(await settings_store.get(session, PPN_KEY, DEFAULT_PPN)))


def totals(lines: list[LineIn], ppn: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    subtotal = sum((_rp(x.qty * x.unit_price) for x in lines), Decimal(0))
    tax = _rp(subtotal * ppn / 100)
    return subtotal, tax, subtotal + tax


async def lines_of(session: AsyncSession, po_id: uuid.UUID) -> list[PurchaseOrderLine]:
    rows = await session.execute(
        select(PurchaseOrderLine)
        .where(PurchaseOrderLine.po_id == po_id)
        .order_by(PurchaseOrderLine.seq)
    )
    return list(rows.scalars())


async def _write_lines(session: AsyncSession, po: PurchaseOrder, lines: list[LineIn]) -> None:
    if not lines:
        raise AppError("LINES_REQUIRED", "PO harus punya minimal satu baris.", status_code=422)
    for x in lines:
        if x.qty <= 0 or x.unit_price < 0:
            raise AppError(
                "LINE_INVALID", "Kuantitas harus > 0 dan harga tidak negatif.", status_code=422
            )
    await session.execute(delete(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id))
    for x in lines:
        session.add(
            PurchaseOrderLine(
                po_id=po.id,
                seq=x.seq,
                item_code=x.item_code,
                description=x.description,
                qty=x.qty,
                uom=x.uom,
                unit_price=x.unit_price,
                amount=_rp(x.qty * x.unit_price),
            )
        )
    po.subtotal, po.ppn_amount, po.total = totals(lines, po.ppn_pct)
    await session.flush()


async def create_from_award(session: AsyncSession, actor: Principal, rfq: Rfq) -> PurchaseOrder:
    if rfq.status != "awarded" or not rfq.awarded_vendor_code:
        raise ConflictError("RFQ_NOT_AWARDED", f"{rfq.number} belum ditetapkan pemenangnya.")
    if (
        await session.execute(select(PurchaseOrder.id).where(PurchaseOrder.rfq_id == rfq.id))
    ).first():
        raise ConflictError("PO_EXISTS", f"{rfq.number} sudah punya PO.")
    pr = await session.get(PurchaseRequisition, rfq.pr_id)
    assert pr is not None
    quote = next(
        q
        for q in await rfq_service.quotes_of(session, rfq.id)
        if q.vendor_code == rfq.awarded_vendor_code
    )
    prices = {ql.seq: ql.unit_price for ql in await rfq_service.quote_lines(session, quote.id)}
    po = PurchaseOrder(
        number=await numbering.next(session, "PO"),
        rfq_id=rfq.id,
        pr_id=pr.id,
        vendor_code=rfq.awarded_vendor_code,
        project_id=pr.project_id,
        wbs_id=pr.wbs_id,
        cost_element_code=pr.cost_element_code,
        status="draft",
        ppn_pct=await ppn_pct(session),
        delivery_location=pr.delivery_location,
        delivery_date=pr.need_date,
        payment_terms=quote.payment_terms or "30 hari setelah invoice dan BAST diterima",
        terms=PENALTY_CLAUSE,
        created_by=actor.id,
        is_demo=pr.is_demo,
    )
    session.add(po)
    await session.flush()
    await _write_lines(
        session,
        po,
        [
            LineIn(x.seq, x.item_code, x.description, x.qty, x.uom, prices[x.seq])
            for x in await pr_service.lines_of(session, pr.id)
        ],
    )
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=po.id,
        actor_id=actor.id,
        after={
            "number": po.number,
            "rfq": rfq.number,
            "vendor": po.vendor_code,
            "subtotal": po.subtotal,
        },
    )
    return po


async def update_draft(
    session: AsyncSession,
    actor: Principal,
    po: PurchaseOrder,
    *,
    lines: list[LineIn],
    delivery_date: date | None,
    delivery_location: str,
    payment_terms: str | None,
    terms: str | None,
) -> None:
    if po.status != "draft":
        raise ConflictError("PO_LOCKED", f"{po.number} sudah diterbitkan; gunakan revisi.")
    before = {"subtotal": po.subtotal, "delivery_date": po.delivery_date}
    po.delivery_date, po.delivery_location = delivery_date, delivery_location
    po.payment_terms, po.terms = payment_terms, terms
    await _write_lines(session, po, lines)
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=po.id,
        actor_id=actor.id,
        before=before,
        after={"subtotal": po.subtotal, "delivery_date": po.delivery_date},
    )


async def _store_pdf(
    session: AsyncSession, storage: Storage, actor: Principal, po: PurchaseOrder
) -> None:
    vendor = (
        await session.execute(select(Vendor).where(Vendor.code == po.vendor_code))
    ).scalar_one()
    project = await session.get(Project, po.project_id)
    assert project is not None
    data = po_pdf.render(
        await letterhead.load(session, storage),
        po,
        await lines_of(session, po.id),
        vendor,
        project_label=f"{project.number} · {project.name}",
        issued=numbering.today_jakarta(),
        signer=actor.user.full_name,
    )
    rev = f"-Rev{po.revision}" if po.revision else ""
    await dms.upload(
        session,
        storage,
        actor,
        entity_type=DOC,
        entity_id=str(po.id),
        filename=f"{po.number}{rev}.pdf",
        data=data,
        note=f"PO {po.number}{' Rev.' + str(po.revision) if po.revision else ''}",
    )


async def _price_history(session: AsyncSession, po: PurchaseOrder) -> None:
    for x in await lines_of(session, po.id):
        session.add(
            PriceHistory(
                item_code=x.item_code,
                description=x.description,
                vendor_code=po.vendor_code,
                uom=x.uom,
                unit_price=x.unit_price,
                source="po",
                doc_number=po.number,
                at=numbering.today_jakarta(),
            )
        )
    await session.flush()


async def issue(
    session: AsyncSession, storage: Storage, actor: Principal, po: PurchaseOrder
) -> bc.Balance:
    """Commit the PO subtotal (consuming the PR pre-commitment) and release what the PR still
    holds (savings). PPN is not budget (input VAT is recoverable)."""
    if po.status != "draft":
        raise ConflictError("PO_NOT_DRAFT", f"{po.number} sudah diterbitkan.")
    pr = await session.get(PurchaseRequisition, po.pr_id, with_for_update=True)
    assert pr is not None
    line = line_of(po)
    held_before = (await bc.held(session, line, pr_service.DOC, str(pr.id)))["pre_commit"]
    await bc.commit(
        session,
        line,
        po.subtotal,
        doc_type=DOC,
        doc_id=str(po.id),
        by=actor.id,
        from_doc=(pr_service.DOC, str(pr.id)),
        note=po.number,
    )
    savings = (await bc.held(session, line, pr_service.DOC, str(pr.id)))["pre_commit"]
    bal = await bc.release(
        session,
        line,
        None,
        bucket="pre_commit",
        doc_type=pr_service.DOC,
        doc_id=str(pr.id),
        by=actor.id,
        note=f"Sisa setelah {po.number}",
    )
    po.status, po.issued_at = "issued", _now()
    pr.status = "ordered"
    await session.flush()
    await _store_pdf(session, storage, actor, po)
    await _price_history(session, po)
    await audit.record(
        session,
        action="po_issued",
        entity_type=DOC,
        entity_id=po.id,
        actor_id=actor.id,
        after={"commit": po.subtotal, "pr_pre_commit": held_before, "savings_released": savings},
    )
    await audit.record(
        session,
        action="status_change",
        entity_type=pr_service.DOC,
        entity_id=pr.id,
        actor_id=actor.id,
        before={"status": "approved"},
        after={"status": "ordered", "po": po.number},
    )
    return bal


def _lines_payload(lines: list[LineIn]) -> list[dict[str, Any]]:
    return [
        {
            "seq": x.seq,
            "item_code": x.item_code,
            "description": x.description,
            "qty": str(x.qty),
            "uom": x.uom,
            "unit_price": str(x.unit_price),
        }
        for x in lines
    ]


def _lines_from_payload(rows: list[dict[str, Any]]) -> list[LineIn]:
    return [
        LineIn(
            int(r["seq"]),
            r.get("item_code"),
            r["description"],
            Decimal(r["qty"]),
            r["uom"],
            Decimal(r["unit_price"]),
        )
        for r in rows
    ]


async def _apply_revision(
    session: AsyncSession,
    storage: Storage,
    actor: Principal,
    po: PurchaseOrder,
    lines: list[LineIn],
    reason: str,
) -> None:
    line = line_of(po)
    old = po.subtotal
    new, _, _ = totals(lines, po.ppn_pct)
    if new > old:
        await bc.commit(
            session,
            line,
            new - old,
            doc_type=DOC,
            doc_id=str(po.id),
            by=actor.id,
            note=f"{po.number} Rev.{po.revision + 1}",
        )
    elif new < old:
        await bc.release(
            session,
            line,
            old - new,
            bucket="commit",
            doc_type=DOC,
            doc_id=str(po.id),
            by=actor.id,
            note=f"Penghematan {po.number} Rev.{po.revision + 1}",
        )
    await _write_lines(session, po, lines)
    po.revision += 1
    po.revision_reason, po.pending_revision, po.status = reason, None, "issued"
    await session.flush()
    await _store_pdf(session, storage, actor, po)
    await _price_history(session, po)
    await audit.record(
        session,
        action="po_revised",
        entity_type=DOC,
        entity_id=po.id,
        actor_id=actor.id,
        before={"subtotal": old},
        after={"subtotal": new, "revision": po.revision, "reason": reason},
    )


async def _check_received(session: AsyncSession, po: PurchaseOrder, lines: list[LineIn]) -> None:
    """A revision cannot drop a line or cut its quantity below what was already received."""
    from app.inventory import gr_service  # local: inventory imports procurement

    received = await gr_service.received_by_seq(session, po.id)
    new = {x.seq: x.qty for x in lines}
    for seq, qty in received.items():
        if qty > 0 and new.get(seq, Decimal(0)) < qty:
            raise AppError(
                "BELOW_RECEIVED",
                f"Baris {seq} sudah diterima {qty.normalize():f}; revisi tidak boleh di bawahnya.",
                status_code=422,
            )


async def revise(
    session: AsyncSession,
    storage: Storage,
    actor: Principal,
    po: PurchaseOrder,
    lines: list[LineIn],
    reason: str,
) -> ApprovalRequest | None:
    """Same or lower value: applied now (savings released). Higher: DOA po_revision first."""
    if po.status != "issued":
        raise ConflictError("PO_NOT_ISSUED", "Revisi hanya untuk PO yang sudah diterbitkan.")
    reason = reason.strip()
    if len(reason) < 5:
        raise AppError("REASON_REQUIRED", "Tulis alasan revisi.", status_code=422)
    for x in lines:
        if x.qty <= 0 or x.unit_price < 0:
            raise AppError(
                "LINE_INVALID", "Kuantitas harus > 0 dan harga tidak negatif.", status_code=422
            )
    await _check_received(session, po, lines)
    new, _, _ = totals(lines, po.ppn_pct)
    if new <= po.subtotal:
        await _apply_revision(session, storage, actor, po, lines, reason)
        return None
    check = await bc.check(session, line_of(po), new - po.subtotal)
    if not check.ok:
        raise bc.BudgetBlockedError(check)
    request = await engine.submit(
        session,
        actor,
        doc_type="po_revision",
        doc_id=po.id,
        doc_number=f"{po.number} Rev.{po.revision + 1}",
        title=f"Revisi {po.number}: {po.subtotal} -> {new}",
        amount=new,
        context={
            "old": str(po.subtotal),
            "new": str(new),
            "increase": str(new - po.subtotal),
            "reason": reason,
        },
        project_id=po.project_id,
    )
    po.status, po.request_id = "revision_pending", request.id
    po.pending_revision = {
        "lines": _lines_payload(lines),
        "reason": reason,
        "requested_by": str(actor.id),
    }
    await session.flush()
    return request


async def _check_increase(
    session: AsyncSession, request: ApprovalRequest, step: ApprovalStep, principal: Principal
) -> None:
    po = await session.get(PurchaseOrder, uuid.UUID(request.doc_id))
    assert po is not None and po.pending_revision
    new, _, _ = totals(_lines_from_payload(po.pending_revision["lines"]), po.ppn_pct)
    result = await bc.check(session, line_of(po), new - po.subtotal)
    if not result.ok:
        raise bc.BudgetBlockedError(result)


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    from app.auth.principal import load_principal  # local: avoid import cycle

    po = await session.get(PurchaseOrder, uuid.UUID(request.doc_id), with_for_update=True)
    assert po is not None and po.pending_revision
    requester = await session.get(User, uuid.UUID(po.pending_revision["requested_by"]))
    assert requester is not None
    storage = current_storage()
    await _apply_revision(
        session,
        storage,
        await load_principal(session, requester),
        po,
        _lines_from_payload(po.pending_revision["lines"]),
        po.pending_revision["reason"],
    )


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    po = await session.get(PurchaseOrder, uuid.UUID(request.doc_id), with_for_update=True)
    assert po is not None
    po.status, po.pending_revision, po.request_id = "issued", None, None
    await session.flush()
    await audit.record(
        session,
        action="po_revision_rejected",
        entity_type=DOC,
        entity_id=po.id,
        actor_id=None,
        after={"status": request.status},
    )


engine.register_document(
    "po_revision",
    on_approved=_on_approved,
    on_rejected=_on_rejected,
    before_approve=_check_increase,
)


async def cancel_draft(session: AsyncSession, actor: Principal, po: PurchaseOrder) -> None:
    if po.status != "draft":
        raise ConflictError("PO_NOT_DRAFT", "Hanya PO draf yang dapat dibatalkan.")
    po.status = "cancelled"
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type=DOC,
        entity_id=po.id,
        actor_id=actor.id,
        before={"status": "draft"},
        after={"status": "cancelled"},
    )
