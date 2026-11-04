"""RFQ from an Approved PR (PROCESS.md · RFQ; DOA.md · rfq_award).

Invite >= 3 qualified vendors of one category (CSMS pending / blacklisted / inactive are not
selectable), record quotes, score them (price 60 % lowest/price, delivery 20 % fastest/days,
rating 20 % rating/5; weights in settings) and award. Awarding a vendor that is not the best score
needs a written reason and goes through DOA `rfq_award`.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.master.models import Vendor
from app.procurement import pr_service
from app.procurement.models import (
    PriceHistory,
    PurchaseRequisition,
    PurchaseRequisitionLine,
    Rfq,
    RfqQuote,
    RfqQuoteLine,
)
from app.services import audit, numbering
from app.services.audit import AuditAction
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest

DOC = "rfq"
MIN_VENDORS = 3
EXCLUDED = ("csms_pending", "blacklisted")
WEIGHTS_KEY = "rfq.weights"
DEFAULT_WEIGHTS = {"price": 60, "delivery": 20, "rating": 20}


def _now() -> datetime:
    return datetime.now(UTC)


async def weights(session: AsyncSession) -> dict[str, Decimal]:
    w = await settings_store.get(session, WEIGHTS_KEY, DEFAULT_WEIGHTS)
    return {k: Decimal(str(w.get(k, DEFAULT_WEIGHTS[k]))) for k in DEFAULT_WEIGHTS}


def excluded_reason(v: Vendor) -> str | None:
    if not v.is_active:
        return "tidak aktif"
    if v.status == "csms_pending":
        return "CSMS belum disetujui"
    if v.status == "blacklisted":
        return "masuk daftar hitam"
    return None


async def eligible_vendors(session: AsyncSession, category: str) -> list[tuple[Vendor, str | None]]:
    rows = await session.execute(
        select(Vendor).where(Vendor.category == category).order_by(Vendor.name)
    )
    return [(v, excluded_reason(v)) for v in rows.scalars()]


async def create(
    session: AsyncSession,
    actor: Principal,
    pr: PurchaseRequisition,
    *,
    category: str,
    vendor_codes: list[str],
    due_date: date | None,
) -> Rfq:
    if pr.status != "approved":
        raise ConflictError("PR_NOT_APPROVED", f"RFQ hanya dari PR yang disetujui ({pr.number}).")
    open_rfq = (
        await session.execute(
            select(Rfq.number).where(Rfq.pr_id == pr.id, Rfq.status != "cancelled")
        )
    ).scalar_one_or_none()
    if open_rfq:
        raise ConflictError("RFQ_EXISTS", f"{pr.number} sudah punya {open_rfq}.")
    codes = list(dict.fromkeys(vendor_codes))
    vendors = {
        v.code: v
        for v in (await session.execute(select(Vendor).where(Vendor.code.in_(codes)))).scalars()
    }
    problems = []
    for code in codes:
        v = vendors.get(code)
        if v is None:
            problems.append(f"{code} tidak ditemukan")
        elif v.category != category:
            problems.append(f"{v.name} bukan kategori {category}")
        elif reason := excluded_reason(v):
            problems.append(f"{v.name} {reason}")
    if problems:
        raise AppError(
            "VENDOR_NOT_SELECTABLE",
            "Vendor tidak dapat dipilih: " + "; ".join(problems) + ".",
            status_code=422,
        )
    if len(codes) < MIN_VENDORS:
        raise AppError(
            "MIN_VENDORS",
            f"Undang minimal {MIN_VENDORS} vendor yang memenuhi syarat.",
            status_code=422,
        )
    rfq = Rfq(
        number=await numbering.next(session, "RFQ"),
        pr_id=pr.id,
        category=category,
        due_date=due_date,
        status="open",
        created_by=actor.id,
        is_demo=pr.is_demo,
    )
    session.add(rfq)
    await session.flush()
    for code in codes:
        session.add(
            RfqQuote(rfq_id=rfq.id, vendor_code=code, status="invited", created_by=actor.id)
        )
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=rfq.id,
        actor_id=actor.id,
        after={"number": rfq.number, "pr": pr.number, "vendors": codes},
    )
    return rfq


async def quotes_of(session: AsyncSession, rfq_id: uuid.UUID) -> list[RfqQuote]:
    rows = await session.execute(
        select(RfqQuote).where(RfqQuote.rfq_id == rfq_id).order_by(RfqQuote.created_at)
    )
    return list(rows.scalars())


async def quote_lines(session: AsyncSession, quote_id: uuid.UUID) -> list[RfqQuoteLine]:
    rows = await session.execute(
        select(RfqQuoteLine).where(RfqQuoteLine.quote_id == quote_id).order_by(RfqQuoteLine.seq)
    )
    return list(rows.scalars())


async def record_quote(
    session: AsyncSession,
    actor: Principal,
    rfq: Rfq,
    quote: RfqQuote,
    *,
    unit_prices: dict[int, Decimal],
    delivery_days: int,
    payment_terms: str | None,
    valid_until: date | None,
    note: str | None,
    declined: bool = False,
) -> RfqQuote:
    if rfq.status != "open":
        raise ConflictError("RFQ_CLOSED", f"{rfq.number} sudah ditutup.")
    if declined:
        quote.status, quote.total, quote.quoted_at = "declined", None, _now()
        await session.execute(delete(RfqQuoteLine).where(RfqQuoteLine.quote_id == quote.id))
        await session.flush()
        return quote
    pr_lines = await pr_service.lines_of(session, rfq.pr_id)
    if set(unit_prices) != {x.seq for x in pr_lines}:
        raise AppError("QUOTE_INCOMPLETE", "Isi harga untuk setiap baris PR.", status_code=422)
    if delivery_days < 0:
        raise AppError("DELIVERY_INVALID", "Waktu kirim tidak boleh negatif.", status_code=422)
    await session.execute(delete(RfqQuoteLine).where(RfqQuoteLine.quote_id == quote.id))
    total = Decimal(0)
    for x in pr_lines:
        price = unit_prices[x.seq]
        if price < 0:
            raise AppError("PRICE_INVALID", "Harga tidak boleh negatif.", status_code=422)
        amount = (x.qty * price).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        total += amount
        session.add(RfqQuoteLine(quote_id=quote.id, seq=x.seq, unit_price=price, amount=amount))
    quote.status, quote.total, quote.delivery_days = "quoted", total, delivery_days
    quote.payment_terms, quote.valid_until, quote.note = payment_terms, valid_until, note
    quote.quoted_at = _now()
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=rfq.id,
        actor_id=actor.id,
        after={"quote": quote.vendor_code, "total": total, "days": delivery_days},
    )
    return quote


@dataclass(frozen=True)
class Score:
    vendor_code: str
    price: Decimal
    delivery: Decimal
    rating: Decimal
    total: Decimal


def score(quotes: list[tuple[RfqQuote, Decimal | None]], w: dict[str, Decimal]) -> list[Score]:
    """Quoted vendors only. price = lowest/price, delivery = fastest/days (0 days counts as 1),
    rating = rating/5 (no rating = 0). Points out of the weights (default 100)."""
    quoted = [(q, r) for q, r in quotes if q.status == "quoted" and q.total is not None]
    if not quoted:
        return []
    lowest = min(q.total for q, _ in quoted if q.total is not None)
    fastest = min(max(q.delivery_days or 0, 1) for q, _ in quoted)
    out = []
    q2 = Decimal("0.01")
    for q, rating in quoted:
        assert q.total is not None
        p = (lowest / q.total) if q.total > 0 else Decimal(1)
        d = Decimal(fastest) / Decimal(max(q.delivery_days or 0, 1))
        r = (rating or Decimal(0)) / Decimal(5)
        out.append(
            Score(
                q.vendor_code,
                (p * w["price"]).quantize(q2, ROUND_HALF_UP),
                (d * w["delivery"]).quantize(q2, ROUND_HALF_UP),
                (r * w["rating"]).quantize(q2, ROUND_HALF_UP),
                (p * w["price"] + d * w["delivery"] + r * w["rating"]).quantize(q2, ROUND_HALF_UP),
            )
        )
    return sorted(out, key=lambda s: (-s.total, s.vendor_code))


async def scores(session: AsyncSession, rfq: Rfq) -> list[Score]:
    quotes = await quotes_of(session, rfq.id)
    ratings = dict(
        (
            await session.execute(
                select(Vendor.code, Vendor.rating).where(
                    Vendor.code.in_([q.vendor_code for q in quotes])
                )
            )
        )
        .tuples()
        .all()
    )
    return score([(q, ratings.get(q.vendor_code)) for q in quotes], await weights(session))


async def _finish_award(
    session: AsyncSession, rfq: Rfq, vendor_code: str, by: uuid.UUID | None
) -> None:
    rfq.status, rfq.awarded_vendor_code, rfq.awarded_at = "awarded", vendor_code, _now()
    rfq.pending_vendor_code = None
    # Price history: every received quote (per item / vendor).
    pr_lines = {x.seq: x for x in await pr_service.lines_of(session, rfq.pr_id)}
    for q in await quotes_of(session, rfq.id):
        if q.status != "quoted":
            continue
        for ql in await quote_lines(session, q.id):
            pl: PurchaseRequisitionLine = pr_lines[ql.seq]
            session.add(
                PriceHistory(
                    item_code=pl.item_code,
                    description=pl.description,
                    vendor_code=q.vendor_code,
                    uom=pl.uom,
                    unit_price=ql.unit_price,
                    source="rfq_quote",
                    doc_number=rfq.number,
                    at=(q.quoted_at or _now()).date(),
                )
            )
    await session.flush()
    await audit.record(
        session,
        action="rfq_awarded",
        entity_type=DOC,
        entity_id=rfq.id,
        actor_id=by,
        after={"vendor": vendor_code, "reason": rfq.award_reason},
    )


async def award(
    session: AsyncSession, actor: Principal, rfq: Rfq, vendor_code: str, reason: str | None
) -> ApprovalRequest | None:
    if rfq.status != "open":
        raise ConflictError("RFQ_CLOSED", f"{rfq.number} tidak terbuka untuk penetapan.")
    ranked = await scores(session, rfq)
    if not ranked:
        raise AppError("NO_QUOTES", "Belum ada penawaran vendor.", status_code=422)
    if vendor_code not in {s.vendor_code for s in ranked}:
        raise AppError("VENDOR_NOT_QUOTED", "Vendor ini belum memberi penawaran.", status_code=422)
    best = ranked[0]
    reason = (reason or "").strip() or None
    rfq.award_reason = reason
    if vendor_code == best.vendor_code:
        await _finish_award(session, rfq, vendor_code, actor.id)
        return None
    if not reason or len(reason) < 10:
        raise AppError(
            "AWARD_REASON_REQUIRED",
            f"Vendor terpilih bukan skor terbaik ({best.vendor_code}, {best.total}). "
            "Tulis alasan (min. 10 karakter); penetapan disetujui Head of Finance & Support.",
            status_code=422,
        )
    pr = await session.get(PurchaseRequisition, rfq.pr_id)
    assert pr is not None
    chosen = next(s for s in ranked if s.vendor_code == vendor_code)
    quote_total = next(
        q.total for q in await quotes_of(session, rfq.id) if q.vendor_code == vendor_code
    )
    request = await engine.submit(
        session,
        actor,
        doc_type="rfq_award",
        doc_id=rfq.id,
        doc_number=rfq.number,
        title=f"Penetapan {vendor_code} untuk {pr.number} (bukan skor terbaik)",
        amount=quote_total,
        context={
            "non_best_score": True,
            "vendor": vendor_code,
            "vendor_score": str(chosen.total),
            "best_vendor": best.vendor_code,
            "best_score": str(best.total),
            "reason": reason,
        },
        project_id=pr.project_id,
    )
    rfq.status, rfq.pending_vendor_code, rfq.request_id = "award_pending", vendor_code, request.id
    await session.flush()
    return request


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    rfq = await session.get(Rfq, uuid.UUID(request.doc_id), with_for_update=True)
    assert rfq is not None and rfq.pending_vendor_code
    acted = [s for s in request.steps if s.acted_by]
    await _finish_award(
        session, rfq, rfq.pending_vendor_code, acted[-1].acted_by if acted else None
    )


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    rfq = await session.get(Rfq, uuid.UUID(request.doc_id), with_for_update=True)
    assert rfq is not None
    rfq.status, rfq.pending_vendor_code, rfq.request_id = "open", None, None
    await session.flush()


engine.register_document("rfq_award", on_approved=_on_approved, on_rejected=_on_rejected)


def score_dict(s: Score) -> dict[str, Any]:
    return {
        "vendor_code": s.vendor_code,
        "price": str(s.price),
        "delivery": str(s.delivery),
        "rating": str(s.rating),
        "total": str(s.total),
    }
