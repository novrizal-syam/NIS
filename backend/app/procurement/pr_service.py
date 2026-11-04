"""Purchase requisition with automatic budget check (PROCESS.md · PR; DOA.md).

draft --submit--> blocked (budget check failed; shortfall shown, "Ajukan BCR")
              \\-> awaiting_approval (DOA: <= 50 jt HoO, <= 500 jt HoF&S, above Director)
awaiting_approval --final approval--> re-check + reserve() -> approved
                                   \\-> still short -> blocked + notify requester
awaiting_approval --reject (reason)--> draft
any open status --cancel--> cancelled (approved: releases the pre-commitment)
bcr_approved on the line -> blocked PRs that now fit -> awaiting_approval
"""

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import Principal, load_principal
from app.core.errors import AppError, ConflictError, ForbiddenError
from app.master.models import Item
from app.notifications import service as notifications
from app.procurement.models import PurchaseRequisition, PurchaseRequisitionLine
from app.project import bcr_service
from app.project.models import BudgetChangeRequest, Project, ProjectWbs
from app.services import audit, numbering
from app.services import budget_control as bc
from app.services.audit import AuditAction
from app.workflow import engine
from app.workflow.models import ApprovalRequest

DOC = "purchase_requisition"
EDITABLE = ("draft", "blocked")
STATUS_LABELS = {
    "draft": "Draf",
    "blocked": "Terblokir anggaran",
    "awaiting_approval": "Menunggu persetujuan",
    "approved": "Disetujui",
    "ordered": "Sudah dipesan (PO)",
    "cancelled": "Dibatalkan",
}
MILLION = Decimal(1_000_000)


def _now() -> datetime:
    return datetime.now(UTC)


def _rp(v: Decimal) -> str:
    from app.services.money import format_idr

    return format_idr(v)


def bcr_suggestion(shortfall: Decimal) -> Decimal:
    """Shortfall rounded up to the next Rp 1 jt (BCR prefill)."""
    return Decimal(math.ceil(shortfall / MILLION)) * MILLION


def line_of(pr: PurchaseRequisition) -> bc.Line:
    return bc.Line(pr.project_id, pr.wbs_id, pr.cost_element_code)


@dataclass(frozen=True)
class LineIn:
    item_code: str | None
    description: str
    qty: Decimal
    uom: str
    est_price: Decimal


async def lines_of(session: AsyncSession, pr_id: uuid.UUID) -> list[PurchaseRequisitionLine]:
    rows = await session.execute(
        select(PurchaseRequisitionLine)
        .where(PurchaseRequisitionLine.pr_id == pr_id)
        .order_by(PurchaseRequisitionLine.seq)
    )
    return list(rows.scalars())


async def _validate_header(
    session: AsyncSession, project_id: uuid.UUID, wbs_code: str, cost_element_code: str
) -> tuple[Project, ProjectWbs]:
    project = await session.get(Project, project_id)
    if project is None:
        raise AppError("PROJECT_INVALID", "Proyek tidak ditemukan.", status_code=422)
    if project.status != "locked":
        raise AppError(
            "PROJECT_NOT_LOCKED",
            f"PR hanya untuk proyek yang anggarannya terkunci ({project.number} belum).",
            status_code=422,
        )
    if cost_element_code == bc.CONTINGENCY:
        raise AppError(
            "CONTINGENCY_NOT_POSTABLE",
            "Kontinjensi tidak dapat dipakai langsung; ajukan BCR pelepasan kontinjensi.",
            status_code=422,
        )
    wbs = (
        await session.execute(
            select(ProjectWbs).where(
                ProjectWbs.project_id == project.id, ProjectWbs.code == wbs_code
            )
        )
    ).scalar_one_or_none()
    if wbs is None:
        raise AppError("WBS_INVALID", f"WBS {wbs_code} tidak ada di proyek ini.", status_code=422)
    return project, wbs


async def _replace_lines(
    session: AsyncSession, pr: PurchaseRequisition, lines: list[LineIn]
) -> None:
    if not lines:
        raise AppError("LINES_REQUIRED", "Isi minimal satu baris.", status_code=422)
    codes = {x.item_code for x in lines if x.item_code}
    items = {}
    if codes:
        items = {
            i.code: i
            for i in (await session.execute(select(Item).where(Item.code.in_(codes)))).scalars()
        }
    await session.execute(
        delete(PurchaseRequisitionLine).where(PurchaseRequisitionLine.pr_id == pr.id)
    )
    total = Decimal(0)
    for seq, x in enumerate(lines, start=1):
        if x.item_code and (x.item_code not in items or not items[x.item_code].is_active):
            raise AppError(
                "ITEM_INVALID",
                f"Item {x.item_code} tidak ditemukan atau tidak aktif.",
                status_code=422,
            )
        if x.qty <= 0 or x.est_price < 0:
            raise AppError(
                "LINE_INVALID", "Kuantitas harus > 0 dan harga tidak negatif.", status_code=422
            )
        amount = (x.qty * x.est_price).quantize(Decimal(1))
        total += amount
        session.add(
            PurchaseRequisitionLine(
                pr_id=pr.id,
                seq=seq,
                item_code=x.item_code,
                description=x.description,
                qty=x.qty,
                uom=x.uom,
                est_price=x.est_price,
                amount=amount,
            )
        )
    if total <= 0:
        raise AppError("TOTAL_ZERO", "Total PR harus lebih dari 0.", status_code=422)
    pr.total = total


async def create(
    session: AsyncSession,
    actor: Principal,
    *,
    project_id: uuid.UUID,
    wbs_code: str,
    cost_element_code: str,
    need_date: date,
    delivery_location: str,
    purpose: str | None,
    lines: list[LineIn],
) -> PurchaseRequisition:
    project, wbs = await _validate_header(session, project_id, wbs_code, cost_element_code)
    pr = PurchaseRequisition(
        number=await numbering.next(session, "PR"),
        project_id=project.id,
        wbs_id=wbs.id,
        cost_element_code=cost_element_code,
        requester_id=actor.id,
        need_date=need_date,
        delivery_location=delivery_location,
        purpose=purpose,
        status="draft",
        created_by=actor.id,
        is_demo=project.is_demo,
    )
    session.add(pr)
    await session.flush()
    await _replace_lines(session, pr, lines)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=pr.id,
        actor_id=actor.id,
        after={"number": pr.number, "total": pr.total, "line": f"{wbs.code}/{cost_element_code}"},
    )
    return pr


async def update(
    session: AsyncSession,
    actor: Principal,
    pr: PurchaseRequisition,
    *,
    wbs_code: str,
    cost_element_code: str,
    need_date: date,
    delivery_location: str,
    purpose: str | None,
    lines: list[LineIn],
) -> PurchaseRequisition:
    if pr.status not in EDITABLE:
        raise ConflictError(
            "PR_LOCKED", f"{pr.number} hanya dapat diubah saat Draf atau Terblokir."
        )
    before = {"total": pr.total, "need_date": pr.need_date, "cost_element": pr.cost_element_code}
    _, wbs = await _validate_header(session, pr.project_id, wbs_code, cost_element_code)
    pr.wbs_id, pr.cost_element_code = wbs.id, cost_element_code
    pr.need_date, pr.delivery_location, pr.purpose = need_date, delivery_location, purpose
    await _replace_lines(session, pr, lines)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=pr.id,
        actor_id=actor.id,
        before=before,
        after={"total": pr.total, "need_date": pr.need_date, "cost_element": pr.cost_element_code},
    )
    return pr


async def _to_approval(
    session: AsyncSession, requester: Principal, pr: PurchaseRequisition
) -> None:
    project = await session.get(Project, pr.project_id)
    wbs = await session.get(ProjectWbs, pr.wbs_id)
    assert project is not None and wbs is not None
    request = await engine.submit(
        session,
        requester,
        doc_type=DOC,
        doc_id=pr.id,
        doc_number=pr.number,
        title=f"PR {project.number} {wbs.code}/{pr.cost_element_code}",
        amount=pr.total,
        context={"project": project.number, "wbs": wbs.code, "cost_element": pr.cost_element_code},
        project_id=project.id,
    )
    pr.status, pr.request_id = "awaiting_approval", request.id
    pr.shortfall = pr.block_message = None
    await session.flush()


async def _block(session: AsyncSession, pr: PurchaseRequisition, result: bc.CheckResult) -> None:
    pr.status, pr.request_id = "blocked", None
    pr.shortfall, pr.block_message = result.shortfall, (result.message or "")[:500]
    await session.flush()


async def submit(
    session: AsyncSession, actor: Principal, pr: PurchaseRequisition
) -> bc.CheckResult:
    if pr.status not in EDITABLE:
        raise ConflictError(
            "ILLEGAL_TRANSITION", f"{pr.number} tidak dapat diajukan dari status ini."
        )
    if pr.requester_id != actor.id:
        raise ForbiddenError("NOT_REQUESTER", "Hanya pemohon yang dapat mengajukan PR ini.")
    pr.submitted_at = _now()
    pr.reject_reason = None
    result = await bc.check(session, line_of(pr), pr.total)
    before = pr.status
    if result.ok:
        await _to_approval(session, actor, pr)
    else:
        await _block(session, pr, result)
    await audit.record(
        session,
        action="submit",
        entity_type=DOC,
        entity_id=pr.id,
        actor_id=actor.id,
        before={"status": before},
        after={"status": pr.status, "shortfall": pr.shortfall},
    )
    return result


async def _notify_requester(
    session: AsyncSession, pr: PurchaseRequisition, kind: str, title: str, body: str
) -> None:
    await notifications.notify(
        session, [pr.requester_id], kind=kind, title=title, body=body, link=f"/pengadaan/pr/{pr.id}"
    )


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    """Final approval: re-check and reserve; if it no longer fits, back to Blocked."""
    pr = await session.get(PurchaseRequisition, uuid.UUID(request.doc_id), with_for_update=True)
    assert pr is not None
    acted = [s for s in request.steps if s.acted_by]
    who = acted[-1].acted_by if acted else None
    try:
        await bc.reserve(
            session, line_of(pr), pr.total, doc_type=DOC, doc_id=str(pr.id), by=who, note=pr.number
        )
    except bc.BudgetBlockedError as exc:
        await _block(session, pr, exc.result)
        await audit.record(
            session,
            action="status_change",
            entity_type=DOC,
            entity_id=pr.id,
            actor_id=who,
            before={"status": "awaiting_approval"},
            after={"status": "blocked", "shortfall": pr.shortfall},
            note="Pemeriksaan ulang saat persetujuan akhir",
        )
        await _notify_requester(
            session, pr, "pr_blocked", f"{pr.number} terblokir anggaran", pr.block_message or ""
        )
        return
    pr.status, pr.approved_at = "approved", _now()
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type=DOC,
        entity_id=pr.id,
        actor_id=who,
        before={"status": "awaiting_approval"},
        after={"status": "approved", "pre_commit": pr.total},
    )


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    pr = await session.get(PurchaseRequisition, uuid.UUID(request.doc_id), with_for_update=True)
    assert pr is not None
    if pr.status == "cancelled":  # cancelled by the requester (engine.cancel)
        return
    acted = [s for s in request.steps if s.acted_by]
    comment = acted[-1].comment if acted else None
    pr.status, pr.request_id = "draft", None
    pr.reject_reason = comment if request.status == "rejected" else None
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type=DOC,
        entity_id=pr.id,
        actor_id=acted[-1].acted_by if acted else request.requester_id,
        before={"status": "awaiting_approval"},
        after={"status": "draft", "reason": comment},
    )


engine.register_document(DOC, on_approved=_on_approved, on_rejected=_on_rejected)


async def cancel(
    session: AsyncSession, actor: Principal, pr: PurchaseRequisition, reason: str
) -> None:
    if pr.requester_id != actor.id:
        raise ForbiddenError("NOT_REQUESTER", "Hanya pemohon yang dapat membatalkan PR ini.")
    if pr.status == "cancelled":
        raise ConflictError("ALREADY_CANCELLED", f"{pr.number} sudah dibatalkan.")
    if pr.status == "ordered":
        raise ConflictError(
            "PR_ORDERED", f"{pr.number} sudah dipesan lewat PO; batalkan PO-nya terlebih dahulu."
        )
    reason = reason.strip()
    if len(reason) < 5:
        raise AppError("REASON_REQUIRED", "Alasan pembatalan wajib diisi.", status_code=422)
    before = pr.status
    pr.status, pr.cancel_reason = "cancelled", reason
    await session.flush()
    if before == "awaiting_approval" and pr.request_id:
        await engine.cancel(session, actor, pr.request_id, reason)
    released = Decimal(0)
    if before == "approved":
        held = (await bc.held(session, line_of(pr), DOC, str(pr.id)))["pre_commit"]
        await bc.release(
            session,
            line_of(pr),
            None,
            bucket="pre_commit",
            doc_type=DOC,
            doc_id=str(pr.id),
            by=actor.id,
            note=f"{pr.number} dibatalkan",
        )
        released = held
    await audit.record(
        session,
        action="status_change",
        entity_type=DOC,
        entity_id=pr.id,
        actor_id=actor.id,
        before={"status": before},
        after={"status": "cancelled", "reason": reason, "released": released},
    )


# ---------------------------------------------------------------- bcr_approved


async def after_bcr(session: AsyncSession, ref: bcr_service.BcrRef) -> list[str]:
    """Referenced PR first, then other blocked PRs on the same line by submit date. Those that
    fit (cumulatively) go to approval; the rest stay Blocked with an updated shortfall."""
    bcr = await session.get(BudgetChangeRequest, ref.bcr_id)
    label = bcr.number if bcr else "BCR"
    rows = list(
        (
            await session.execute(
                select(PurchaseRequisition)
                .where(
                    PurchaseRequisition.project_id == ref.project_id,
                    PurchaseRequisition.wbs_id == ref.wbs_id,
                    PurchaseRequisition.cost_element_code == ref.cost_element_code,
                    PurchaseRequisition.status == "blocked",
                )
                .order_by(PurchaseRequisition.submitted_at)
                .with_for_update()
            )
        ).scalars()
    )
    if ref.ref_doc_type == DOC and ref.ref_doc_id:
        rows.sort(key=lambda p: str(p.id) != ref.ref_doc_id and p.number != ref.ref_doc_id)
    remaining = (
        await bc.available(session, bc.Line(ref.project_id, ref.wbs_id, ref.cost_element_code))
    ).available
    moved = []
    for pr in rows:
        if pr.total <= remaining:
            remaining -= pr.total
            requester = await session.get(User, pr.requester_id)
            assert requester is not None
            await _to_approval(session, await load_principal(session, requester), pr)
            pr.bcr_id = ref.bcr_id
            moved.append(pr.number)
            await audit.record(
                session,
                action="status_change",
                entity_type=DOC,
                entity_id=pr.id,
                actor_id=None,
                before={"status": "blocked"},
                after={"status": "awaiting_approval"},
                note=f"Diperiksa ulang setelah {label}",
            )
            await _notify_requester(
                session,
                pr,
                "pr_unblocked",
                f"{pr.number} lanjut ke persetujuan",
                f"Anggaran cukup setelah {label}.",
            )
        else:
            pr.shortfall = pr.total - max(remaining, Decimal(0))
            pr.block_message = f"Anggaran tidak cukup setelah {label}: kurang {_rp(pr.shortfall)}."
            await audit.record(
                session,
                action="budget_recheck",
                entity_type=DOC,
                entity_id=pr.id,
                actor_id=None,
                after={"status": "blocked", "shortfall": pr.shortfall},
                note=f"Diperiksa ulang setelah {label}",
            )
    await session.flush()
    return moved


async def _after_bcr_listener(session: AsyncSession, ref: bcr_service.BcrRef) -> None:
    await after_bcr(session, ref)


bcr_service.on_bcr_approved(_after_bcr_listener)


def snapshot(pr: PurchaseRequisition) -> dict[str, Any]:
    return {"number": pr.number, "status": pr.status, "total": pr.total}
