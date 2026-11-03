"""Business rules for leads, opportunities and bid/no-bid (PROCESS.md · Lead to contract)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, RolePermission, User, UserRole
from app.auth.permissions import Scope
from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.crm.models import BidDecision, Lead, Opportunity
from app.services import audit, numbering
from app.services.audit import AuditAction
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest

MODULE = "crm"

SOURCES = ("civd", "eproc", "invitation", "visit", "referral", "website", "exhibition")

# Qualification checklist (PROCESS.md): at least 3 of 5 to qualify.
QUALIFICATION = ("budget", "technical_fit", "start_6m", "decision_maker", "csms")
MIN_QUALIFIED = 3

# Bid/no-bid scores, each 1-5.
SCORES = (
    "strategic_fit",
    "technical",
    "availability",
    "csms",
    "margin",
    "risk",
)

LEAD_STATUSES = ("new", "contacted", "qualified", "disqualified")
LEAD_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"contacted", "disqualified"}),
    "contacted": frozenset({"qualified", "disqualified"}),
    "qualified": frozenset(),
    "disqualified": frozenset(),
}

STAGES = ("qualified", "quotation", "submitted", "won", "lost")
OPEN_STAGES = ("qualified", "quotation", "submitted")
# Manual moves. Qualified -> Quotation is only possible through an approved bid decision.
STAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "qualified": frozenset({"lost"}),
    "quotation": frozenset({"submitted", "lost"}),
    "submitted": frozenset({"won", "lost"}),
    "won": frozenset(),
    "lost": frozenset(),
}

LEAD_LABELS = {
    "new": "Baru",
    "contacted": "Dihubungi",
    "qualified": "Terkualifikasi",
    "disqualified": "Didiskualifikasi",
}
STAGE_LABELS = {
    "qualified": "Qualified",
    "quotation": "Quotation",
    "submitted": "Submitted",
    "won": "Won",
    "lost": "Lost",
}

# Settings keys (system_settings); defaults match docs/domain and are seeded by migration 0013.
BID_THRESHOLD = "crm.bid_threshold_pct"
WIN_RATE_TARGET = "crm.win_rate_target_pct"
CONTRACT_TARGET = "crm.contract_value_target_ytd"
DEFAULTS: dict[str, Any] = {
    BID_THRESHOLD: 60,
    WIN_RATE_TARGET: 45,
    CONTRACT_TARGET: 80_000_000_000,
}


@dataclass(frozen=True)
class CrmConfig:
    bid_threshold: Decimal
    win_rate_target: Decimal
    contract_target: Decimal


async def config(session: AsyncSession) -> CrmConfig:
    async def read(key: str) -> Decimal:
        return Decimal(str(await settings_store.get(session, key, DEFAULTS[key])))

    return CrmConfig(
        bid_threshold=await read(BID_THRESHOLD),
        win_rate_target=await read(WIN_RATE_TARGET),
        contract_target=await read(CONTRACT_TARGET),
    )


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- access


def may(principal: Principal, action: str, owner_id: uuid.UUID) -> bool:
    """Data scope for crm: `all` sees everything, any narrower scope means own records."""
    scope = principal.scope_for(MODULE, action)
    if scope is None:
        return False
    return scope == Scope.ALL or owner_id == principal.id


def ensure(principal: Principal, action: str, owner_id: uuid.UUID, label: str) -> None:
    if not may(principal, action, owner_id):
        if action == "view":
            raise NotFoundError("NOT_FOUND", f"{label} tidak ditemukan atau Anda tidak berizin.")
        raise ForbiddenError("PERMISSION_DENIED", f"Anda tidak berizin mengubah {label} ini.")


async def check_owner(
    session: AsyncSession, principal: Principal, owner_id: uuid.UUID | None
) -> uuid.UUID:
    """Users with `own` scope can only own their records; `all` may assign any sales user."""
    if owner_id is None or owner_id == principal.id:
        return principal.id
    if principal.scope_for(MODULE, "edit") != Scope.ALL:
        raise ForbiddenError(
            "OWNER_NOT_ALLOWED", "Anda hanya dapat membuat data atas nama Anda sendiri."
        )
    if owner_id not in {u["id"] for u in await owners(session)}:
        raise AppError(
            "OWNER_INVALID",
            "Pemilik harus pengguna aktif dengan izin Lead & Peluang.",
            status_code=422,
        )
    return owner_id


async def owners(session: AsyncSession) -> list[dict[str, Any]]:
    """Active users whose roles may create crm records (possible owners)."""
    rows = await session.execute(
        select(User.id, User.full_name)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .where(
            User.is_active.is_(True),
            UserRole.active_now(),
            RolePermission.module == MODULE,
            RolePermission.action == "create",
            Role.code != "super_admin",
        )
        .distinct()
        .order_by(User.full_name)
    )
    return [{"id": uid, "full_name": name} for uid, name in rows.all()]


# ---------------------------------------------------------------- leads


def qualification_count(q: dict[str, bool]) -> int:
    return sum(1 for k in QUALIFICATION if q.get(k))


def clean_qualification(q: dict[str, Any]) -> dict[str, bool]:
    unknown = set(q) - set(QUALIFICATION)
    if unknown:
        raise AppError("UNKNOWN_CRITERIA", "Kriteria kualifikasi tidak dikenal.", status_code=422)
    return {k: bool(q.get(k, False)) for k in QUALIFICATION}


def lead_snapshot(lead: Lead) -> dict[str, Any]:
    return {
        "company_name": lead.company_name,
        "client_code": lead.client_code,
        "contact_name": lead.contact_name,
        "contact_email": lead.contact_email,
        "contact_phone": lead.contact_phone,
        "source": lead.source,
        "need": lead.need,
        "estimated_value": lead.estimated_value,
        "status": lead.status,
        "qualification": lead.qualification,
        "owner_id": lead.owner_id,
    }


async def create_lead(session: AsyncSession, actor: Principal, data: dict[str, Any]) -> Lead:
    lead = Lead(
        number=await numbering.next(session, "LD"),
        status="new",
        status_changed_at=_now(),
        created_by=actor.id,
        **data,
    )
    session.add(lead)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="lead",
        entity_id=lead.id,
        actor_id=actor.id,
        after={"number": lead.number, **lead_snapshot(lead)},
    )
    return lead


async def update_lead(
    session: AsyncSession, actor: Principal, lead: Lead, changes: dict[str, Any]
) -> Lead:
    if lead.status == "disqualified":
        raise ConflictError(
            "LEAD_CLOSED", f"{lead.number} sudah didiskualifikasi dan tidak dapat diubah."
        )
    if lead.status == "qualified" and "qualification" in changes:
        raise ConflictError(
            "LEAD_QUALIFIED", "Checklist kualifikasi terkunci setelah lead terkualifikasi."
        )
    before = lead_snapshot(lead)
    for key, value in changes.items():
        setattr(lead, key, value)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="lead",
        entity_id=lead.id,
        actor_id=actor.id,
        before=before,
        after=lead_snapshot(lead),
    )
    return lead


async def transition_lead(
    session: AsyncSession, actor: Principal, lead: Lead, to: str, reason: str | None
) -> Lead:
    if to not in LEAD_TRANSITIONS.get(lead.status, frozenset()):
        raise ConflictError(
            "ILLEGAL_TRANSITION",
            f"Status lead tidak dapat diubah dari {LEAD_LABELS[lead.status]} "
            f"ke {LEAD_LABELS.get(to, to)}.",
        )
    if to == "qualified":
        n = qualification_count(lead.qualification)
        if n < MIN_QUALIFIED:
            raise AppError(
                "QUALIFICATION_INCOMPLETE",
                f"Lead baru terpenuhi {n} dari 5 kriteria; minimal {MIN_QUALIFIED} untuk "
                "kualifikasi.",
                status_code=422,
            )
    reason = (reason or "").strip() or None
    if to == "disqualified":
        if not reason or len(reason) < 5:
            raise AppError("REASON_REQUIRED", "Alasan diskualifikasi wajib diisi.", status_code=422)
        lead.disqualify_reason = reason
    before = lead.status
    lead.status, lead.status_changed_at = to, _now()
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type="lead",
        entity_id=lead.id,
        actor_id=actor.id,
        before={"status": before},
        after={"status": to, "reason": reason},
    )
    return lead


async def opportunity_of_lead(session: AsyncSession, lead_id: uuid.UUID) -> Opportunity | None:
    return (
        await session.execute(select(Opportunity).where(Opportunity.lead_id == lead_id))
    ).scalar_one_or_none()


def opp_snapshot(opp: Opportunity) -> dict[str, Any]:
    return {
        "title": opp.title,
        "company_name": opp.company_name,
        "client_code": opp.client_code,
        "owner_id": opp.owner_id,
        "value": opp.value,
        "probability": opp.probability,
        "expected_close": opp.expected_close,
        "is_tender": opp.is_tender,
        "stage": opp.stage,
        "winner_price": opp.winner_price,
    }


async def convert(
    session: AsyncSession, actor: Principal, lead: Lead, data: dict[str, Any]
) -> Opportunity:
    """'Jadikan Opportunity': only a qualified lead, only once."""
    if lead.status != "qualified":
        raise ConflictError(
            "LEAD_NOT_QUALIFIED",
            "Hanya lead yang sudah terkualifikasi yang dapat dijadikan opportunity.",
        )
    existing = await opportunity_of_lead(session, lead.id)
    if existing is not None:
        raise ConflictError("ALREADY_CONVERTED", f"{lead.number} sudah menjadi {existing.number}.")
    value = data.get("value")
    opp = Opportunity(
        number=await numbering.next(session, "OPP"),
        lead_id=lead.id,
        client_code=lead.client_code,
        company_name=lead.company_name,
        title=data["title"],
        owner_id=lead.owner_id,
        value=value if value is not None else (lead.estimated_value or Decimal(0)),
        probability=data.get("probability") or 20,
        expected_close=data.get("expected_close"),
        is_tender=data.get("is_tender", False),
        stage="qualified",
        stage_changed_at=_now(),
        created_by=actor.id,
        is_demo=lead.is_demo,
    )
    session.add(opp)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="opportunity",
        entity_id=opp.id,
        actor_id=actor.id,
        after={"number": opp.number, "lead": lead.number, **opp_snapshot(opp)},
    )
    await audit.record(
        session,
        action="converted",
        entity_type="lead",
        entity_id=lead.id,
        actor_id=actor.id,
        after={"opportunity": opp.number},
    )
    return opp


# ---------------------------------------------------------------- opportunities


def _ensure_open(opp: Opportunity) -> None:
    if opp.stage not in OPEN_STAGES:
        raise ConflictError(
            "OPPORTUNITY_CLOSED",
            f"{opp.number} sudah {STAGE_LABELS[opp.stage]} dan tidak dapat diubah.",
        )


def _ensure_no_pending_bid(opp: Opportunity) -> None:
    if opp.bid_status == "pending":
        raise ConflictError(
            "BID_PENDING",
            f"Keputusan bid/no-bid {opp.number} masih menunggu Direktur.",
        )


async def update_opportunity(
    session: AsyncSession, actor: Principal, opp: Opportunity, changes: dict[str, Any]
) -> Opportunity:
    _ensure_open(opp)
    before = opp_snapshot(opp)
    for key, value in changes.items():
        setattr(opp, key, value)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="opportunity",
        entity_id=opp.id,
        actor_id=actor.id,
        before=before,
        after=opp_snapshot(opp),
    )
    return opp


async def set_stage(
    session: AsyncSession,
    opp: Opportunity,
    to: str,
    *,
    actor_id: uuid.UUID | None,
    reason: str | None = None,
    note: str | None = None,
) -> None:
    before = opp.stage
    opp.stage, opp.stage_changed_at = to, _now()
    today = numbering.today_jakarta()
    if to == "won":
        opp.won_at, opp.probability = today, 100
    if to == "lost":
        opp.lost_at, opp.probability, opp.lost_reason = today, 0, reason
    await session.flush()
    await audit.record(
        session,
        action="stage_change",
        entity_type="opportunity",
        entity_id=opp.id,
        actor_id=actor_id,
        before={"stage": before},
        after={"stage": to, "reason": reason},
        note=note,
    )


async def move_stage(
    session: AsyncSession,
    actor: Principal,
    opp: Opportunity,
    to: str,
    reason: str | None,
    winner_price: Decimal | None = None,
) -> Opportunity:
    _ensure_no_pending_bid(opp)
    if to == "won" and opp.stage == "submitted":
        raise ConflictError(
            "USE_WON_ACTION",
            'Gunakan "Tandai Menang": kontrak dan proyek dibuat bersamaan.',
        )
    if opp.stage == "qualified" and to == "quotation":
        raise ConflictError(
            "BID_DECISION_REQUIRED",
            "Pindah ke Quotation hanya lewat keputusan bid yang disetujui Direktur.",
        )
    if to not in STAGE_TRANSITIONS.get(opp.stage, frozenset()):
        raise ConflictError(
            "ILLEGAL_TRANSITION",
            f"Tahap tidak dapat diubah dari {STAGE_LABELS[opp.stage]} "
            f"ke {STAGE_LABELS.get(to, to)}.",
        )
    reason = (reason or "").strip() or None
    if to == "lost" and (not reason or len(reason) < 5):
        raise AppError("REASON_REQUIRED", "Alasan kalah/batal wajib diisi.", status_code=422)
    if to == "lost" and winner_price is not None:
        if winner_price < 0:
            raise AppError("PRICE_INVALID", "Harga pemenang tidak boleh negatif.", status_code=422)
        opp.winner_price = winner_price
    await set_stage(session, opp, to, actor_id=actor.id, reason=reason)
    return opp


# ---------------------------------------------------------------- bid / no-bid


def score_percent(scores: dict[str, int]) -> Decimal:
    """Average of the six scores / 5, as a percentage with 2 decimals."""
    if set(scores) != set(SCORES):
        raise AppError("SCORES_INCOMPLETE", "Isi keenam skor bid/no-bid.", status_code=422)
    for key in SCORES:
        value = scores[key]
        if not isinstance(value, int) or not 1 <= value <= 5:
            raise AppError("SCORE_RANGE", "Setiap skor harus 1 sampai 5.", status_code=422)
    total = Decimal(sum(scores[k] for k in SCORES))
    pct = total / Decimal(len(SCORES) * 5) * 100
    return pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recommend(percent: Decimal, threshold: Decimal) -> str:
    return "bid" if percent >= threshold else "no_bid"


async def submit_bid_decision(
    session: AsyncSession,
    actor: Principal,
    opp: Opportunity,
    *,
    scores: dict[str, int],
    proposal: str,
    note: str | None,
) -> BidDecision:
    if opp.stage != "qualified":
        raise ConflictError(
            "NOT_QUALIFIED_STAGE",
            "Keputusan bid/no-bid hanya untuk opportunity di tahap Qualified.",
        )
    _ensure_no_pending_bid(opp)
    if proposal not in ("bid", "no_bid"):
        raise AppError("PROPOSAL_INVALID", "Usulan harus bid atau no-bid.", status_code=422)
    cfg = await config(session)
    pct = score_percent(scores)
    rec = recommend(pct, cfg.bid_threshold)
    note = (note or "").strip() or None
    if proposal != rec and (not note or len(note) < 10):
        raise AppError(
            "JUSTIFICATION_REQUIRED",
            f"Skor {pct}% merekomendasikan {'bid' if rec == 'bid' else 'no-bid'} "
            f"(batas {cfg.bid_threshold}%). Tulis alasan (min. 10 karakter) bila usulan berbeda.",
            status_code=422,
        )
    decision = BidDecision(
        opportunity_id=opp.id,
        scores={k: scores[k] for k in SCORES},
        percent=pct,
        threshold=cfg.bid_threshold,
        recommendation=rec,
        proposal=proposal,
        note=note,
        status="pending",
        created_by=actor.id,
        is_demo=opp.is_demo,
    )
    session.add(decision)
    await session.flush()
    label = "BID" if proposal == "bid" else "NO-BID"
    request = await engine.submit(
        session,
        actor,
        doc_type="bid_decision",
        doc_id=decision.id,
        doc_number=opp.number,
        title=f"{label} · {opp.title} ({opp.company_name}) · skor {pct}%",
        amount=opp.value,
        context={
            "opportunity_id": str(opp.id),
            "percent": str(pct),
            "threshold": str(cfg.bid_threshold),
            "recommendation": rec,
            "proposal": proposal,
            "note": note,
        },
    )
    decision.request_id = request.id
    opp.bid_status = "pending"
    await session.flush()
    await audit.record(
        session,
        action="bid_decision_submitted",
        entity_type="opportunity",
        entity_id=opp.id,
        actor_id=actor.id,
        after={"percent": pct, "recommendation": rec, "proposal": proposal, "note": note},
    )
    return decision


def _decider(request: ApprovalRequest) -> tuple[uuid.UUID | None, str | None]:
    acted = [s for s in request.steps if s.acted_by]
    if not acted:
        return None, None
    last = max(acted, key=lambda s: s.acted_at or _now())
    return last.acted_by, last.comment


async def _load(session: AsyncSession, request: ApprovalRequest) -> tuple[BidDecision, Opportunity]:
    decision = await session.get(BidDecision, uuid.UUID(request.doc_id))
    assert decision is not None
    opp = await session.get(Opportunity, decision.opportunity_id, with_for_update=True)
    assert opp is not None
    return decision, opp


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    decision, opp = await _load(session, request)
    decider, comment = _decider(request)
    decision.status, decision.decided_at, decision.decision_comment = (
        "approved",
        _now(),
        comment,
    )
    if decision.proposal == "bid":
        opp.bid_status = "bid"
        await set_stage(session, opp, "quotation", actor_id=decider, note="Bid disetujui")
    else:
        opp.bid_status = "no_bid"
        reason = f"No-bid disetujui Direktur. {decision.note or comment or ''}".strip()
        await set_stage(session, opp, "lost", actor_id=decider, reason=reason[:500])


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    decision, opp = await _load(session, request)
    decider, comment = _decider(request)
    decision.decided_at, decision.decision_comment = _now(), comment
    if request.status == "cancelled":
        # Withdrawn by the requester: back to Qualified, a new decision can be proposed.
        decision.status, opp.bid_status = "cancelled", "none"
        await session.flush()
        return
    decision.status = "rejected"
    if decision.proposal == "bid":
        opp.bid_status = "no_bid"
        reason = f"Bid ditolak Direktur: {comment or '-'}"
        await set_stage(session, opp, "lost", actor_id=decider, reason=reason[:500])
    else:
        # The Director does not accept walking away: stays Qualified for a bid proposal.
        opp.bid_status = "none"
        await session.flush()


engine.register_document("bid_decision", on_approved=_on_approved, on_rejected=_on_rejected)


# ---------------------------------------------------------------- dashboard


def year_start(today: date) -> date:
    return date(today.year, 1, 1)
