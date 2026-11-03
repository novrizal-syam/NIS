"""Quotations: lines from the price database, discount, revisions, DOA by margin, sending
(PROCESS.md · Lead to contract; DOA.md: margin >= 25% Head of Sales, < 25% Director)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.crm import service as crm
from app.crm.models import Lead, Opportunity, Quotation, QuotationLine
from app.master.models import CostElement, PriceItem
from app.services import audit, numbering
from app.services.audit import AuditAction
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest

MODULE = "quotation"
STATUSES = ("draft", "submitted", "approved", "rejected", "sent", "superseded")
EDITABLE = ("draft",)
REVISABLE = ("approved", "rejected", "sent")
STATUS_LABELS = {
    "draft": "Draf",
    "submitted": "Menunggu persetujuan",
    "approved": "Disetujui",
    "rejected": "Ditolak",
    "sent": "Terkirim",
    "superseded": "Digantikan revisi",
}

MARGIN_WARNING = "quotation.margin_warning_pct"
DEFAULT_MARGIN_WARNING = 20
LETTER_DEPT = "SLS"


async def margin_warning_pct(session: AsyncSession) -> Decimal:
    value = await settings_store.get(session, MARGIN_WARNING, DEFAULT_MARGIN_WARNING)
    return Decimal(str(value))


def _now() -> datetime:
    return datetime.now(UTC)


def _rp(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- totals


@dataclass(frozen=True)
class LineIn:
    price_item_code: str | None
    description: str
    unit: str
    qty: Decimal
    unit_cost: Decimal
    unit_price: Decimal
    cost_element_code: str | None = None


DEFAULT_COST_ELEMENT = "SUBCONTRACT"  # free lines without a price item or chosen element


@dataclass(frozen=True)
class LineTotals:
    line_cost: Decimal
    line_price: Decimal


@dataclass(frozen=True)
class Totals:
    lines: tuple[LineTotals, ...]
    subtotal: Decimal
    discount_amount: Decimal
    total_price: Decimal
    total_cost: Decimal
    margin: Decimal
    margin_pct: Decimal


def compute(lines: list[LineIn], discount_pct: Decimal) -> Totals:
    """Each line rounds to whole rupiah; the discount applies to the selling price only.
    Margin % = (total price - total cost) / total price, two decimals."""
    if not Decimal(0) <= discount_pct <= Decimal(100):
        raise AppError("DISCOUNT_RANGE", "Diskon harus antara 0 dan 100%.", status_code=422)
    per_line = tuple(
        LineTotals(line_cost=_rp(x.qty * x.unit_cost), line_price=_rp(x.qty * x.unit_price))
        for x in lines
    )
    subtotal = sum((x.line_price for x in per_line), Decimal(0))
    total_cost = sum((x.line_cost for x in per_line), Decimal(0))
    discount_amount = _rp(subtotal * discount_pct / 100)
    total_price = subtotal - discount_amount
    margin = total_price - total_cost
    margin_pct = (
        (margin / total_price * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if total_price > 0
        else Decimal("0.00")
    )
    return Totals(per_line, subtotal, discount_amount, total_price, total_cost, margin, margin_pct)


# ---------------------------------------------------------------- loading


async def lines_of(session: AsyncSession, quotation_id: uuid.UUID) -> list[QuotationLine]:
    rows = await session.execute(
        select(QuotationLine)
        .where(QuotationLine.quotation_id == quotation_id)
        .order_by(QuotationLine.seq)
    )
    return list(rows.scalars())


async def latest_revision(session: AsyncSession, number: str) -> int:
    value = await session.execute(
        select(func.max(Quotation.revision)).where(Quotation.number == number)
    )
    return int(value.scalar_one() or 0)


async def revisions(session: AsyncSession, number: str) -> list[Quotation]:
    rows = await session.execute(
        select(Quotation).where(Quotation.number == number).order_by(Quotation.revision.desc())
    )
    return list(rows.scalars())


def label(q: Quotation) -> str:
    return f"{q.number} Rev.{q.revision}"


def snapshot(q: Quotation, lines: list[QuotationLine]) -> dict[str, Any]:
    return {
        "status": q.status,
        "discount_pct": q.discount_pct,
        "subtotal": q.subtotal,
        "total_price": q.total_price,
        "total_cost": q.total_cost,
        "margin_pct": q.margin_pct,
        "valid_until": q.valid_until,
        "lines": [
            {
                "item": x.price_item_code,
                "description": x.description,
                "qty": x.qty,
                "unit_cost": x.unit_cost,
                "unit_price": x.unit_price,
            }
            for x in lines
        ],
    }


# ---------------------------------------------------------------- create / edit


async def _ensure_stage(opp: Opportunity) -> None:
    if opp.stage not in ("quotation", "submitted"):
        raise ConflictError(
            "OPPORTUNITY_NOT_IN_QUOTATION",
            f"{opp.number} belum di tahap Quotation. Bid harus disetujui Direktur dahulu.",
        )


async def create(session: AsyncSession, actor: Principal, opp: Opportunity) -> Quotation:
    await _ensure_stage(opp)
    existing = (
        await session.execute(
            select(Quotation.number).where(Quotation.opportunity_id == opp.id).limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        raise ConflictError(
            "QUOTATION_EXISTS",
            f"{opp.number} sudah punya penawaran {existing}. Buat revisi dari penawaran itu.",
        )
    q = Quotation(
        number=await numbering.next(session, "QT"),
        revision=0,
        opportunity_id=opp.id,
        owner_id=opp.owner_id,
        status="draft",
        discount_pct=Decimal(0),
        valid_until=None,
        terms=DEFAULT_TERMS,
        created_by=actor.id,
        is_demo=opp.is_demo,
    )
    session.add(q)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="quotation",
        entity_id=q.id,
        actor_id=actor.id,
        after={"number": label(q), "opportunity": opp.number},
    )
    return q


DEFAULT_TERMS = (
    "Harga belum termasuk PPN.\n"
    "Pembayaran 30 hari setelah invoice dan BAST diterima.\n"
    "Mobilisasi 14 hari setelah PO/SPK diterima."
)


async def _price_items(session: AsyncSession, codes: set[str]) -> dict[str, PriceItem]:
    if not codes:
        return {}
    rows = await session.execute(select(PriceItem).where(PriceItem.code.in_(codes)))
    return {p.code: p for p in rows.scalars()}


async def save_draft(
    session: AsyncSession,
    actor: Principal,
    q: Quotation,
    *,
    lines: list[LineIn],
    discount_pct: Decimal,
    valid_until: date | None,
    notes: str | None,
    terms: str | None,
) -> Quotation:
    if q.status not in EDITABLE:
        raise ConflictError(
            "QUOTATION_LOCKED",
            f"{label(q)} sudah {STATUS_LABELS[q.status].lower()}; buat revisi untuk mengubahnya.",
        )
    items = await _price_items(session, {x.price_item_code for x in lines if x.price_item_code})
    for x in lines:
        if x.price_item_code and (
            x.price_item_code not in items or not items[x.price_item_code].is_active
        ):
            raise AppError(
                "PRICE_ITEM_INVALID",
                f"Item harga {x.price_item_code} tidak ditemukan atau tidak aktif.",
                status_code=422,
            )
        if x.qty <= 0:
            raise AppError("QTY_INVALID", "Kuantitas harus lebih dari 0.", status_code=422)
        if x.unit_cost < 0 or x.unit_price < 0:
            raise AppError("PRICE_INVALID", "Harga dan biaya tidak boleh negatif.", status_code=422)
    known = set((await session.execute(select(CostElement.code))).scalars())
    elements: list[str] = []
    for x in lines:
        code = (
            items[x.price_item_code].cost_element_code
            if x.price_item_code
            else (x.cost_element_code or DEFAULT_COST_ELEMENT)
        )
        if code not in known or code == "CONTINGENCY":
            raise AppError(
                "COST_ELEMENT_INVALID", f"Elemen biaya {code} tidak valid.", status_code=422
            )
        elements.append(code)
    before = snapshot(q, await lines_of(session, q.id))
    totals = compute(lines, discount_pct)
    await session.execute(delete(QuotationLine).where(QuotationLine.quotation_id == q.id))
    for seq, (x, t, element) in enumerate(zip(lines, totals.lines, elements, strict=True), start=1):
        session.add(
            QuotationLine(
                quotation_id=q.id,
                seq=seq,
                price_item_code=x.price_item_code,
                cost_element_code=element,
                description=x.description,
                unit=x.unit,
                qty=x.qty,
                unit_cost=x.unit_cost,
                unit_price=x.unit_price,
                line_cost=t.line_cost,
                line_price=t.line_price,
            )
        )
    q.discount_pct = discount_pct
    q.subtotal, q.discount_amount = totals.subtotal, totals.discount_amount
    q.total_price, q.total_cost = totals.total_price, totals.total_cost
    q.margin, q.margin_pct = totals.margin, totals.margin_pct
    q.valid_until, q.notes, q.terms = valid_until, notes, terms
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="quotation",
        entity_id=q.id,
        actor_id=actor.id,
        before=before,
        after=snapshot(q, await lines_of(session, q.id)),
    )
    return q


# ---------------------------------------------------------------- DOA


async def submit(
    session: AsyncSession, actor: Principal, q: Quotation, opp: Opportunity
) -> ApprovalRequest:
    if q.status != "draft":
        raise ConflictError("ILLEGAL_TRANSITION", f"{label(q)} bukan draf.")
    await _ensure_stage(opp)
    lines = await lines_of(session, q.id)
    if not lines or q.total_price <= 0:
        raise AppError(
            "QUOTATION_EMPTY",
            "Isi minimal satu baris dengan harga sebelum diajukan.",
            status_code=422,
        )
    warn = await margin_warning_pct(session)
    request = await engine.submit(
        session,
        actor,
        doc_type="quotation",
        doc_id=q.id,
        doc_number=label(q),
        title=f"Penawaran {opp.title} ({opp.company_name}) · margin {q.margin_pct}%",
        amount=q.total_price,
        context={
            "margin_pct": str(q.margin_pct),
            "discount_pct": str(q.discount_pct),
            "total_cost": str(q.total_cost),
            "opportunity_id": str(opp.id),
            "opportunity": opp.number,
            "low_margin": q.margin_pct < warn,
        },
    )
    q.status, q.request_id, q.submitted_at = "submitted", request.id, _now()
    q.decided_at = q.decision_comment = None
    await session.flush()
    await audit.record(
        session,
        action="submit",
        entity_type="quotation",
        entity_id=q.id,
        actor_id=actor.id,
        before={"status": "draft"},
        after={"status": "submitted", "margin_pct": q.margin_pct, "rule": request.rule_snapshot},
    )
    return request


def _decision(request: ApprovalRequest) -> tuple[uuid.UUID | None, str | None]:
    acted = [s for s in request.steps if s.acted_by]
    if not acted:
        return None, None
    last = max(acted, key=lambda s: s.acted_at or _now())
    return last.acted_by, last.comment


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    q = await session.get(Quotation, uuid.UUID(request.doc_id), with_for_update=True)
    assert q is not None
    who, comment = _decision(request)
    q.status, q.decided_at, q.decision_comment = "approved", _now(), comment
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type="quotation",
        entity_id=q.id,
        actor_id=who,
        before={"status": "submitted"},
        after={"status": "approved"},
    )


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    q = await session.get(Quotation, uuid.UUID(request.doc_id), with_for_update=True)
    assert q is not None
    who, comment = _decision(request)
    # Withdrawn by the requester -> back to draft; rejected -> stays rejected (revise to fix).
    new = "draft" if request.status == "cancelled" else "rejected"
    q.status, q.decided_at, q.decision_comment = new, _now(), comment
    if new == "draft":
        q.request_id = q.submitted_at = None
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type="quotation",
        entity_id=q.id,
        actor_id=who or request.requester_id,
        before={"status": "submitted"},
        after={"status": new, "comment": comment},
    )


engine.register_document("quotation", on_approved=_on_approved, on_rejected=_on_rejected)


# ---------------------------------------------------------------- revisions


async def revise(
    session: AsyncSession, actor: Principal, q: Quotation, opp: Opportunity, reason: str | None
) -> Quotation:
    if q.revision != await latest_revision(session, q.number):
        raise ConflictError("NOT_LATEST", "Revisi hanya dapat dibuat dari revisi terakhir.")
    if q.status not in REVISABLE:
        raise ConflictError(
            "NOT_REVISABLE",
            "Revisi dibuat dari penawaran yang sudah disetujui, ditolak, atau terkirim. "
            "Draf dapat diubah langsung.",
        )
    if opp.stage in ("won", "lost"):
        raise ConflictError("OPPORTUNITY_CLOSED", f"{opp.number} sudah {opp.stage}.")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise AppError("REASON_REQUIRED", "Tulis alasan revisi (min. 5 karakter).", status_code=422)
    new = Quotation(
        number=q.number,
        revision=q.revision + 1,
        opportunity_id=q.opportunity_id,
        owner_id=q.owner_id,
        status="draft",
        discount_pct=q.discount_pct,
        subtotal=q.subtotal,
        discount_amount=q.discount_amount,
        total_price=q.total_price,
        total_cost=q.total_cost,
        margin=q.margin,
        margin_pct=q.margin_pct,
        valid_until=q.valid_until,
        notes=q.notes,
        terms=q.terms,
        revision_reason=reason,
        created_by=actor.id,
        is_demo=q.is_demo,
    )
    session.add(new)
    await session.flush()
    for x in await lines_of(session, q.id):
        session.add(
            QuotationLine(
                quotation_id=new.id,
                seq=x.seq,
                price_item_code=x.price_item_code,
                cost_element_code=x.cost_element_code,
                description=x.description,
                unit=x.unit,
                qty=x.qty,
                unit_cost=x.unit_cost,
                unit_price=x.unit_price,
                line_cost=x.line_cost,
                line_price=x.line_price,
            )
        )
    previous = q.status
    q.status = "superseded"
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type="quotation",
        entity_id=q.id,
        actor_id=actor.id,
        before={"status": previous},
        after={"status": "superseded", "by": label(new)},
    )
    await audit.record(
        session,
        action="revision",
        entity_type="quotation",
        entity_id=new.id,
        actor_id=actor.id,
        after={"number": label(new), "from": label(q), "reason": reason},
    )
    return new


# ---------------------------------------------------------------- send


async def client_contact(session: AsyncSession, opp: Opportunity) -> tuple[str | None, str | None]:
    if opp.lead_id is None:
        return None, None
    lead = await session.get(Lead, opp.lead_id)
    return (lead.contact_name, lead.contact_email) if lead else (None, None)


async def mark_sent(
    session: AsyncSession,
    actor: Principal,
    q: Quotation,
    opp: Opportunity,
    *,
    letter_id: uuid.UUID,
    email_to: str | None,
) -> None:
    previous = q.status
    q.status, q.sent_at, q.letter_id, q.sent_to_email = "sent", _now(), letter_id, email_to
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type="quotation",
        entity_id=q.id,
        actor_id=actor.id,
        before={"status": previous},
        after={"status": "sent", "email": email_to},
    )
    if opp.value != q.total_price:
        before_value = opp.value
        opp.value = q.total_price  # the pipeline follows the quoted price
        await audit.record(
            session,
            action=AuditAction.UPDATE,
            entity_type="opportunity",
            entity_id=opp.id,
            actor_id=actor.id,
            before={"value": before_value},
            after={"value": opp.value},
            note=f"Nilai dari {label(q)}",
        )
    if opp.stage == "quotation":
        await crm.set_stage(session, opp, "submitted", actor_id=actor.id, note=label(q))


def ensure_sendable(q: Quotation, opp: Opportunity, latest: int) -> None:
    if q.status != "approved":
        raise ConflictError("NOT_APPROVED", f"{label(q)} harus disetujui sebelum dikirim ke klien.")
    if q.revision != latest:
        raise ConflictError("NOT_LATEST", "Hanya revisi terakhir yang dapat dikirim.")
    if opp.stage not in ("quotation", "submitted"):
        raise ConflictError("OPPORTUNITY_CLOSED", f"{opp.number} sudah {opp.stage}.")
