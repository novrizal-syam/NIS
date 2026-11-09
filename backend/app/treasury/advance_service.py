"""Cash advances (07b; DOA cash_advance -> Head of Operation).

request -> approval -> Cashier disburses (Dr 1120 / Cr bank) -> the requester settles with a
receipt photo per line and cost element -> Cashier confirms: expenses (project actuals through
budget_control) Cr 1120, refund (Dr bank) or reimbursement (Cr bank) for the difference.
An advance not settled 14 days after disbursement raises an alert (job `advances`).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.dms.models import Attachment
from app.master.models import CostElement
from app.notifications import service as notifications
from app.project.models import Project
from app.services import audit, ledger, numbering
from app.services import budget_control as bc
from app.services.audit import AuditAction
from app.services.numbering import today_jakarta
from app.treasury import bank_service
from app.treasury.lookup import by_code
from app.treasury.models import BankAccount, CashAdvance, CashAdvanceLine
from app.workflow import engine
from app.workflow.models import ApprovalRequest

DOC = "cash_advance"
OVERDUE_DAYS = 14
ZERO = Decimal(0)
STATUS_LABELS = {
    "draft": "Draf",
    "awaiting_approval": "Menunggu persetujuan",
    "approved": "Disetujui",
    "disbursed": "Dicairkan",
    "settlement_submitted": "Pertanggungjawaban diajukan",
    "settled": "Selesai",
    "cancelled": "Dibatalkan",
}


@dataclass(frozen=True)
class LineIn:
    spent_on: date
    cost_element: str
    description: str
    amount: Decimal
    wbs_code: str | None = None
    attachment_id: uuid.UUID | None = None


def _rp(v: Decimal) -> str:
    return "Rp " + f"{int(v):,}".replace(",", ".")


def _amount(v: Decimal, what: str) -> Decimal:
    v = Decimal(v)
    if v <= 0 or v != v.to_integral_value():
        raise AppError("AMOUNT_INVALID", f"{what}: nilai harus rupiah bulat > 0.", status_code=422)
    return v


async def _employee(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    u = await session.get(User, user_id)
    return u.employee_code if u else None


def _partner(ca: CashAdvance) -> ledger.Dims:
    return ledger.Dims(
        partner_type="employee", partner_code=ca.employee_code or str(ca.requester_id)[:30]
    )


async def create(
    session: AsyncSession,
    actor: Principal,
    *,
    purpose: str,
    amount: Decimal,
    needed_date: date,
    project_id: uuid.UUID | None,
) -> CashAdvance:
    if project_id is not None and await session.get(Project, project_id) is None:
        raise NotFoundError("PROJECT_NOT_FOUND", "Proyek tidak ditemukan.")
    ca = CashAdvance(
        number=await numbering.next(session, "CA", on=today_jakarta()),
        requester_id=actor.id,
        employee_code=await _employee(session, actor.id),
        project_id=project_id,
        purpose=purpose.strip(),
        amount=_amount(amount, "Uang muka"),
        needed_date=needed_date,
        status="draft",
        created_by=actor.id,
    )
    session.add(ca)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=ca.id,
        actor_id=actor.id,
        after={"number": ca.number, "amount": ca.amount, "purpose": ca.purpose},
    )
    return ca


async def update(
    session: AsyncSession,
    actor: Principal,
    ca: CashAdvance,
    *,
    purpose: str,
    amount: Decimal,
    needed_date: date,
    project_id: uuid.UUID | None,
) -> CashAdvance:
    if ca.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{ca.number} tidak lagi draf.")
    before = {"amount": ca.amount, "purpose": ca.purpose}
    ca.purpose, ca.amount = purpose.strip(), _amount(amount, "Uang muka")
    ca.needed_date, ca.project_id = needed_date, project_id
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=ca.id,
        actor_id=actor.id,
        before=before,
        after={"amount": ca.amount, "purpose": ca.purpose},
    )
    return ca


async def submit(session: AsyncSession, actor: Principal, ca: CashAdvance) -> ApprovalRequest:
    if ca.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{ca.number} tidak lagi draf.")
    req = await engine.submit(
        session,
        actor,
        doc_type=DOC,
        doc_id=ca.id,
        doc_number=ca.number,
        title=f"Uang muka {ca.number}: {ca.purpose[:80]}",
        amount=ca.amount,
        project_id=ca.project_id,
    )
    ca.status, ca.request_id, ca.reject_reason = "awaiting_approval", req.id, None
    await session.flush()
    return req


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    ca = await session.get(CashAdvance, uuid.UUID(request.doc_id), with_for_update=True)
    if ca is not None and ca.status == "awaiting_approval":
        ca.status = "approved"
        await session.flush()


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    ca = await session.get(CashAdvance, uuid.UUID(request.doc_id), with_for_update=True)
    if ca is None or ca.status != "awaiting_approval":
        return
    acted = [s for s in request.steps if s.acted_by]
    ca.status, ca.request_id = "draft", None
    ca.reject_reason = (acted[-1].comment if acted else None) or None
    await session.flush()


engine.register_document(DOC, on_approved=_on_approved, on_rejected=_on_rejected)


def _not_requester(actor: Principal, ca: CashAdvance) -> None:
    if actor.id == ca.requester_id:
        raise ForbiddenError(
            "SOD_SELF_PAYMENT", "Anda tidak dapat mencairkan atau menyelesaikan uang muka sendiri."
        )


async def _bank(session: AsyncSession, bank_account_id: uuid.UUID | None) -> BankAccount:
    acc = await bank_service.account_or_default(session, bank_account_id)
    if not acc.is_active or acc.currency != "IDR":
        raise AppError(
            "BANK_ACCOUNT_INVALID",
            "Uang muka dibayar dari rekening IDR yang aktif.",
            status_code=422,
        )
    return acc


async def _ensure_balance(session: AsyncSession, acc: BankAccount, amount: Decimal) -> None:
    await session.get(BankAccount, acc.id, with_for_update=True)
    have = await bank_service.balance(session, acc)
    if have < amount:
        raise ConflictError(
            "INSUFFICIENT_BALANCE", f"Saldo {acc.name} {_rp(have)} tidak cukup untuk {_rp(amount)}."
        )


async def disburse(
    session: AsyncSession,
    actor: Principal,
    ca: CashAdvance,
    *,
    on: date,
    bank_account_id: uuid.UUID | None,
) -> CashAdvance:
    if ca.status != "approved":
        raise ConflictError("NOT_APPROVED", f"{ca.number} belum disetujui.")
    _not_requester(actor, ca)
    acc = await _bank(session, bank_account_id)
    await _ensure_balance(session, acc, ca.amount)
    entry = await ledger.post_parts(
        session,
        "cash_advance_disbursed",
        [
            ledger.Part("advance", ca.amount, _partner(ca), ca.number),
            ledger.Part("bank", ca.amount, None, ca.number),
        ],
        entry_date=on,
        description=f"Uang muka {ca.number}: {ca.purpose[:120]}",
        source_type=DOC,
        source_id=ca.id,
        source_number=ca.number,
        by=actor.id,
        accounts={"bank": acc.gl_account},
    )
    ca.status, ca.bank_account_id = "disbursed", acc.id
    ca.disbursed_by, ca.disbursed_at, ca.disbursement_journal_id = actor.id, on, entry.id
    await session.flush()
    await audit.record(
        session,
        action="disburse",
        entity_type=DOC,
        entity_id=ca.id,
        actor_id=actor.id,
        after={"status": "disbursed", "journal": entry.number},
    )
    return ca


async def lines_of(session: AsyncSession, advance_id: uuid.UUID) -> list[CashAdvanceLine]:
    return list(
        (
            await session.execute(
                select(CashAdvanceLine)
                .where(CashAdvanceLine.advance_id == advance_id)
                .order_by(CashAdvanceLine.seq)
            )
        ).scalars()
    )


async def submit_settlement(
    session: AsyncSession, actor: Principal, ca: CashAdvance, lines: list[LineIn], note: str | None
) -> CashAdvance:
    if ca.status != "disbursed":
        raise ConflictError(
            "NOT_DISBURSED", f"{ca.number} belum dicairkan atau sudah dipertanggungjawabkan."
        )
    if actor.id != ca.requester_id:
        raise ForbiddenError("NOT_REQUESTER", "Pertanggungjawaban diajukan oleh pemohon uang muka.")
    if not lines:
        raise AppError("SETTLEMENT_EMPTY", "Isi minimal satu baris biaya.", status_code=422)
    rows = []
    for i, x in enumerate(lines, start=1):
        ce = await by_code(session, CostElement, x.cost_element)
        if ce is None or not ce.is_active or ce.account_code is None:
            raise AppError(
                "COST_ELEMENT_INVALID",
                f"Baris {i}: elemen biaya {x.cost_element} tidak bisa dipakai.",
                status_code=422,
            )
        if ca.project_id is not None and not x.wbs_code:
            raise AppError("WBS_REQUIRED", f"Baris {i}: pilih WBS proyek.", status_code=422)
        att = await session.get(Attachment, x.attachment_id) if x.attachment_id else None
        if att is None or att.entity_type != DOC or att.entity_id != str(ca.id):
            raise AppError(
                "RECEIPT_REQUIRED",
                f"Baris {i}: lampirkan foto kuitansi/nota pada uang muka ini.",
                status_code=422,
            )
        amount = _amount(x.amount, f"Baris {i}")
        if ca.project_id is not None:
            line = await bc.resolve(session, ca.project_id, str(x.wbs_code), x.cost_element)
            res = await bc.check(session, line, amount)
            if not res.ok:
                raise bc.BudgetBlockedError(res)
        rows.append(
            CashAdvanceLine(
                advance_id=ca.id,
                seq=i,
                spent_on=x.spent_on,
                cost_element=x.cost_element,
                wbs_code=x.wbs_code if ca.project_id else None,
                description=x.description.strip()[:300],
                amount=amount,
                attachment_id=att.id,
            )
        )
    for old in await lines_of(session, ca.id):
        await session.delete(old)
    await session.flush()
    session.add_all(rows)
    ca.spent = sum((r.amount for r in rows), ZERO)
    ca.settlement_note = (note or "").strip() or None
    ca.status, ca.settlement_submitted_at = "settlement_submitted", datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        action="submit",
        entity_type=DOC,
        entity_id=ca.id,
        actor_id=actor.id,
        after={"status": ca.status, "spent": ca.spent, "lines": len(rows)},
    )
    return ca


async def return_settlement(
    session: AsyncSession, actor: Principal, ca: CashAdvance, reason: str
) -> CashAdvance:
    if ca.status != "settlement_submitted":
        raise ConflictError("NOT_SUBMITTED", "Pertanggungjawaban belum diajukan.")
    _not_requester(actor, ca)
    ca.status, ca.reject_reason = "disbursed", reason.strip()
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.REJECT,
        entity_type=DOC,
        entity_id=ca.id,
        actor_id=actor.id,
        after={"status": ca.status},
        note=reason.strip(),
    )
    await notifications.notify(
        session,
        [ca.requester_id],
        kind="cash_advance_returned",
        title=f"Pertanggungjawaban {ca.number} dikembalikan",
        body=reason.strip()[:300],
        link=f"/keuangan/treasury?tab=advances&id={ca.id}",
    )
    return ca


async def settle(
    session: AsyncSession, actor: Principal, ca: CashAdvance, *, on: date
) -> CashAdvance:
    """Cashier confirms: expenses per cost element (project actuals), refund or
    reimbursement for the difference, 1120 cleared."""
    if ca.status != "settlement_submitted":
        raise ConflictError("NOT_SUBMITTED", "Pertanggungjawaban belum diajukan.")
    _not_requester(actor, ca)
    lines = await lines_of(session, ca.id)
    acc = await _bank(session, ca.bank_account_id)
    diff = ca.spent - ca.amount
    if diff > 0:
        await _ensure_balance(session, acc, diff)
    parts: list[ledger.Part] = []
    for x in lines:
        dims = ledger.Dims(cost_element=x.cost_element)
        if ca.project_id is not None:
            bline = await bc.resolve(session, ca.project_id, str(x.wbs_code), x.cost_element)
            await bc.actualize(
                session,
                bline,
                x.amount,
                doc_type=DOC,
                doc_id=str(ca.id),
                by=actor.id,
                note=f"{ca.number} baris {x.seq}",
            )
            dims = ledger.Dims(
                project_id=ca.project_id, wbs_id=bline.wbs_id, cost_element=x.cost_element
            )
        parts.append(ledger.Part("expense", x.amount, dims, f"{ca.number}: {x.description}"))
    parts.append(ledger.Part("advance", ca.amount, _partner(ca), ca.number))
    if diff < 0:
        parts.append(ledger.Part("refund", -diff, None, f"Pengembalian {ca.number}"))
    elif diff > 0:
        parts.append(ledger.Part("reimbursement", diff, None, f"Penggantian {ca.number}"))
    entry = await ledger.post_parts(
        session,
        "cash_advance_settled",
        parts,
        entry_date=on,
        description=f"Pertanggungjawaban uang muka {ca.number}",
        source_type=DOC,
        source_id=ca.id,
        source_number=ca.number,
        by=actor.id,
        accounts={"refund": acc.gl_account, "reimbursement": acc.gl_account},
    )
    ca.status, ca.settled_by, ca.settled_at = "settled", actor.id, on
    ca.settlement_journal_id, ca.reject_reason = entry.id, None
    await session.flush()
    await audit.record(
        session,
        action="settle",
        entity_type=DOC,
        entity_id=ca.id,
        actor_id=actor.id,
        after={"status": "settled", "spent": ca.spent, "journal": entry.number},
    )
    return ca


async def cancel(session: AsyncSession, actor: Principal, ca: CashAdvance, reason: str) -> None:
    if ca.status not in ("draft", "approved"):
        raise ConflictError(
            "CANNOT_CANCEL",
            "Hanya uang muka draf atau disetujui (belum dicairkan) yang bisa dibatalkan.",
        )
    ca.status = "cancelled"
    await session.flush()
    await audit.record(
        session,
        action="cancel",
        entity_type=DOC,
        entity_id=ca.id,
        actor_id=actor.id,
        after={"status": "cancelled"},
        note=reason.strip(),
    )


async def overdue_alerts(session: AsyncSession, today: date | None = None) -> int:
    """Disbursed advances not settled after 14 days: tell the requester and the Cashiers."""
    today = today or today_jakarta()
    rows = list(
        (
            await session.execute(
                select(CashAdvance).where(
                    CashAdvance.status == "disbursed",
                    CashAdvance.disbursed_at <= today - timedelta(days=OVERDUE_DAYS),
                    CashAdvance.overdue_notified_at.is_(None),
                )
            )
        ).scalars()
    )
    cashiers = await engine.holders_of_role(session, "cashier")
    sent = 0
    for ca in rows:
        days = (today - ca.disbursed_at).days if ca.disbursed_at else OVERDUE_DAYS
        sent += await notifications.notify(
            session,
            list({ca.requester_id, *cashiers}),
            kind="cash_advance_overdue",
            title=f"Uang muka {ca.number} belum dipertanggungjawabkan ({days} hari)",
            body=f"{ca.purpose[:200]} — {_rp(ca.amount)}",
            link=f"/keuangan/treasury?tab=advances&id={ca.id}",
            dedupe_key=f"ca-overdue-{ca.id}",
        )
        ca.overdue_notified_at = datetime.now(UTC)
    await session.flush()
    return sent


def to_dict(ca: CashAdvance, lines: list[CashAdvanceLine] | None = None) -> dict[str, Any]:
    today = today_jakarta()
    return {
        "id": str(ca.id),
        "number": ca.number,
        "requester_id": str(ca.requester_id),
        "employee_code": ca.employee_code,
        "project_id": str(ca.project_id) if ca.project_id else None,
        "purpose": ca.purpose,
        "amount": format(ca.amount, "f"),
        "needed_date": ca.needed_date.isoformat(),
        "status": ca.status,
        "status_label": STATUS_LABELS.get(ca.status, ca.status),
        "request_id": str(ca.request_id) if ca.request_id else None,
        "reject_reason": ca.reject_reason,
        "disbursed_at": ca.disbursed_at.isoformat() if ca.disbursed_at else None,
        "days_open": (today - ca.disbursed_at).days
        if ca.disbursed_at and ca.status in ("disbursed", "settlement_submitted")
        else None,
        "overdue": bool(
            ca.disbursed_at
            and ca.status == "disbursed"
            and (today - ca.disbursed_at).days >= OVERDUE_DAYS
        ),
        "spent": format(ca.spent, "f"),
        "difference": format(ca.spent - ca.amount, "f")
        if ca.status
        in (
            "settlement_submitted",
            "settled",
        )
        else None,
        "settled_at": ca.settled_at.isoformat() if ca.settled_at else None,
        "settlement_note": ca.settlement_note,
        "disbursement_journal_id": str(ca.disbursement_journal_id)
        if ca.disbursement_journal_id
        else None,
        "settlement_journal_id": str(ca.settlement_journal_id)
        if ca.settlement_journal_id
        else None,
        "lines": [
            {
                "seq": x.seq,
                "spent_on": x.spent_on.isoformat(),
                "cost_element": x.cost_element,
                "wbs_code": x.wbs_code,
                "description": x.description,
                "amount": format(x.amount, "f"),
                "attachment_id": str(x.attachment_id) if x.attachment_id else None,
            }
            for x in (lines or [])
        ],
    }
