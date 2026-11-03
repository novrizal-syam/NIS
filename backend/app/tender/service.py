import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.crm import service as crm
from app.crm.models import Opportunity, Quotation
from app.dms.models import Attachment
from app.services import audit
from app.services.audit import AuditAction
from app.services.numbering import JAKARTA, today_jakarta
from app.tender.models import Tender, TenderDocument
from app.workflow import engine
from app.workflow.models import ApprovalRequest

DOC_ENTITY = "tender_document"

# Default checklist (section, name, mandatory). Editable per tender.
DEFAULT_DOCUMENTS: tuple[tuple[str, str, bool], ...] = (
    ("admin", "Surat penawaran bermeterai", True),
    ("admin", "Pakta integritas", True),
    ("admin", "Akta perusahaan & NIB", True),
    ("admin", "NPWP & SPT tahunan", True),
    ("admin", "Sertifikat CSMS", True),
    ("admin", "Jaminan penawaran (bid bond)", False),
    ("technical", "Metode kerja & jadwal", True),
    ("technical", "Daftar peralatan & sertifikat inspeksi", True),
    ("technical", "CV & sertifikat personel", True),
    ("technical", "Formulir TKDN", True),
    ("technical", "Rencana K3LL (HSE plan)", True),
    ("commercial", "Daftar kuantitas & harga (BOQ)", True),
    ("commercial", "Rekapitulasi harga", True),
)

RESULT_LABELS = {
    "won": "Menang",
    "lost": "Kalah",
    "disqualified": "Gugur",
    "cancelled": "Dibatalkan",
}


def _now() -> datetime:
    return datetime.now(UTC)


async def create(session: AsyncSession, actor: Principal, opp: Opportunity) -> Tender:
    if not opp.is_tender:
        raise ConflictError(
            "NOT_A_TENDER", f"{opp.number} bukan tender. Tandai peluang sebagai tender dahulu."
        )
    if opp.stage in ("won", "lost"):
        raise ConflictError("OPPORTUNITY_CLOSED", f"{opp.number} sudah {opp.stage}.")
    if (await session.execute(select(Tender.id).where(Tender.opportunity_id == opp.id))).first():
        raise ConflictError("TENDER_EXISTS", f"{opp.number} sudah punya data tender.")
    latest = (
        await session.execute(
            select(Quotation.total_price)
            .where(Quotation.opportunity_id == opp.id)
            .order_by(Quotation.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    tender = Tender(
        opportunity_id=opp.id,
        owner_id=opp.owner_id,
        price=latest if latest else None,
        created_by=actor.id,
        is_demo=opp.is_demo,
    )
    session.add(tender)
    await session.flush()
    for seq, (section, name, mandatory) in enumerate(DEFAULT_DOCUMENTS, start=1):
        session.add(
            TenderDocument(
                tender_id=tender.id, section=section, seq=seq, name=name, mandatory=mandatory
            )
        )
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="tender",
        entity_id=tender.id,
        actor_id=actor.id,
        after={"opportunity": opp.number, "documents": len(DEFAULT_DOCUMENTS)},
    )
    return tender


# ---------------------------------------------------------------- checklist


@dataclass(frozen=True)
class DocState:
    doc: TenderDocument
    files: int
    status: str  # present | missing | na
    expired: bool


def reference_date(tender: Tender) -> date:
    """A document must still be valid at closing (or today, whichever is later)."""
    today = today_jakarta()
    if tender.closing_at is None:
        return today
    return max(today, tender.closing_at.astimezone(JAKARTA).date())


async def documents(session: AsyncSession, tender: Tender) -> list[DocState]:
    docs = list(
        (
            await session.execute(
                select(TenderDocument)
                .where(TenderDocument.tender_id == tender.id)
                .order_by(TenderDocument.section, TenderDocument.seq)
            )
        ).scalars()
    )
    counts: dict[str, int] = {}
    if docs:
        rows = await session.execute(
            select(Attachment.entity_id, func.count(func.distinct(Attachment.group_id)))
            .where(
                Attachment.entity_type == DOC_ENTITY,
                Attachment.entity_id.in_([str(d.id) for d in docs]),
                Attachment.archived_at.is_(None),
            )
            .group_by(Attachment.entity_id)
        )
        counts = dict(rows.tuples().all())
    ref = reference_date(tender)
    out = []
    for d in docs:
        n = counts.get(str(d.id), 0)
        expired = d.expiry_date is not None and d.expiry_date < ref
        if d.not_applicable:
            status = "na"
        elif n > 0 and not expired:
            status = "present"
        else:
            status = "missing"
        out.append(DocState(d, n, status, expired))
    return out


def readiness(tender: Tender, docs: list[DocState]) -> dict[str, Any]:
    missing = [d.doc.name for d in docs if d.doc.mandatory and d.status == "missing"]
    problems = []
    if missing:
        problems.append(f"{len(missing)} dokumen wajib belum ada atau kedaluwarsa")
    if not tender.price or tender.price <= 0:
        problems.append("harga penawaran belum diisi")
    return {"ready": not problems, "missing": missing, "problems": problems}


# ---------------------------------------------------------------- package approval


async def submit_package(
    session: AsyncSession, actor: Principal, tender: Tender, opp: Opportunity
) -> ApprovalRequest:
    if tender.package_status == "pending":
        raise ConflictError("PACKAGE_PENDING", "Paket tender masih menunggu persetujuan.")
    if tender.package_status == "approved":
        raise ConflictError("PACKAGE_APPROVED", "Paket tender sudah disetujui.")
    if tender.result:
        raise ConflictError("TENDER_CLOSED", "Hasil tender sudah dicatat.")
    state = readiness(tender, await documents(session, tender))
    if not state["ready"]:
        raise AppError(
            "PACKAGE_NOT_READY",
            "Paket tender belum lengkap: " + "; ".join(state["problems"]) + ".",
            status_code=422,
            details={"missing": state["missing"]},
        )
    request = await engine.submit(
        session,
        actor,
        doc_type="tender_package",
        doc_id=tender.id,
        doc_number=opp.number + (f" · {tender.tender_number}" if tender.tender_number else ""),
        title=f"Paket tender {opp.title} ({opp.company_name})",
        amount=tender.price,
        context={
            "opportunity_id": str(opp.id),
            "tender_number": tender.tender_number,
            "closing_at": tender.closing_at.isoformat() if tender.closing_at else None,
            "tkdn_offered_pct": str(tender.tkdn_offered_pct)
            if tender.tkdn_offered_pct is not None
            else None,
        },
    )
    tender.package_status, tender.request_id = "pending", request.id
    await session.flush()
    await audit.record(
        session,
        action="submit",
        entity_type="tender",
        entity_id=tender.id,
        actor_id=actor.id,
        after={"package": "pending", "price": tender.price},
    )
    return request


async def _hook(session: AsyncSession, request: ApprovalRequest, status: str) -> None:
    tender = await session.get(Tender, uuid.UUID(request.doc_id), with_for_update=True)
    assert tender is not None
    before = tender.package_status
    tender.package_status = status
    if status == "none":
        tender.request_id = None
    await session.flush()
    acted = [s for s in request.steps if s.acted_by]
    await audit.record(
        session,
        action="status_change",
        entity_type="tender",
        entity_id=tender.id,
        actor_id=acted[-1].acted_by if acted else request.requester_id,
        before={"package": before},
        after={"package": status},
    )


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    await _hook(session, request, "approved")


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    await _hook(session, request, "none" if request.status == "cancelled" else "rejected")


engine.register_document("tender_package", on_approved=_on_approved, on_rejected=_on_rejected)


# ---------------------------------------------------------------- submission & result


async def record_submission(
    session: AsyncSession,
    actor: Principal,
    tender: Tender,
    *,
    submitted_at: datetime,
    channel: str,
    receipt_number: str | None,
) -> None:
    if tender.package_status != "approved":
        raise ConflictError(
            "PACKAGE_NOT_APPROVED",
            "Catat pemasukan setelah paket tender disetujui (teknis dan komersial).",
        )
    before = {"submitted_at": tender.submitted_at, "channel": tender.submission_channel}
    tender.submitted_at, tender.submission_channel = submitted_at, channel
    tender.receipt_number = receipt_number
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="tender",
        entity_id=tender.id,
        actor_id=actor.id,
        before=before,
        after={"submitted_at": submitted_at, "channel": channel, "receipt": receipt_number},
        note="Pemasukan dokumen tender",
    )


async def record_result(
    session: AsyncSession,
    actor: Principal,
    tender: Tender,
    opp: Opportunity,
    *,
    result: str,
    rank: int | None,
    winner_name: str | None,
    winning_price: Decimal | None,
    lessons_learned: str | None,
) -> None:
    if tender.result:
        raise ConflictError("RESULT_EXISTS", "Hasil tender sudah dicatat.")
    if result != "cancelled" and tender.submitted_at is None:
        raise ConflictError(
            "NOT_SUBMITTED", "Catat pemasukan dokumen sebelum mencatat hasil tender."
        )
    lessons = (lessons_learned or "").strip() or None
    if result in ("lost", "disqualified") and (not lessons or len(lessons) < 10):
        raise AppError(
            "LESSONS_REQUIRED",
            "Tulis pelajaran yang dipetik (min. 10 karakter) untuk tender yang kalah/gugur.",
            status_code=422,
        )
    tender.result, tender.result_at, tender.rank = result, today_jakarta(), rank
    tender.winner_name = (winner_name or "").strip() or None
    tender.winning_price, tender.lessons_learned = winning_price, lessons
    await session.flush()
    await audit.record(
        session,
        action="tender_result",
        entity_type="tender",
        entity_id=tender.id,
        actor_id=actor.id,
        after={
            "result": result,
            "rank": rank,
            "winner": tender.winner_name,
            "winning_price": winning_price,
        },
    )
    # Not won: the opportunity ends as Lost through the 02a rules. Won: the user marks the
    # opportunity won ("Tandai Menang") so the contract and project are created (02c).
    if result != "won" and opp.stage in crm.OPEN_STAGES and opp.bid_status != "pending":
        reason = f"Tender {RESULT_LABELS[result].lower()}" + (
            f" (pemenang: {tender.winner_name})" if tender.winner_name else ""
        )
        await crm.move_stage(session, actor, opp, "lost", reason, winning_price)
