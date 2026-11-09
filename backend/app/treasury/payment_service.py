"""Payment runs (07b; PROCESS.md · Payment run; DOA.md payment_run).

The AP Accountant (preparer) selects due items -> DOA payment_run (Head of Finance & Support
up to Rp 1 M, Director above) -> the Cashier releases: balance check, bank file, journal
(Dr 2110 per vendor / 2310 / 2240 / 2220 / 2230, Cr the bank's GL account), invoices paid,
PPh 23 bukti potong per vendor. Preparer, approver and releaser are three different people;
whoever changed a paid vendor's bank account may not approve or release the run.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.finance import ap_service as ap
from app.finance.models import VendorInvoice
from app.master.models import Vendor
from app.services import audit, ledger, numbering
from app.services.audit import AuditAction, AuditLog
from app.setup import service as settings_store
from app.treasury import adapters, bank_service
from app.treasury.lookup import by_code
from app.treasury.models import BankAccount, PaymentRun, PaymentRunItem
from app.workflow import engine
from app.workflow.models import ApprovalRequest, ApprovalStep

DOC = "payment_run"
OPEN = ("draft", "awaiting_approval", "approved")
ZERO = Decimal(0)
# Liabilities paid from their GL credit balance: kind -> (posting-rule role, account).
LIABILITIES: dict[str, tuple[str, str]] = {
    "salaries": ("salaries", "2310"),
    "bpjs": ("bpjs", "2240"),
    "pph21": ("pph21", "2220"),
    "pph23": ("pph23", "2230"),
}
KIND_LABELS = {
    "vendor_invoice": "Invoice vendor",
    "salaries": "Gaji bersih",
    "bpjs": "BPJS",
    "pph21": "PPh 21",
    "pph23": "PPh 23",
}
PAYEES_KEY = "treasury.payees"
DEFAULT_PAYEES = {
    "salaries": "Gaji karyawan (rekening payroll)",
    "bpjs": "BPJS Kesehatan & Ketenagakerjaan",
    "pph21": "Kas Negara (kode billing PPh 21)",
    "pph23": "Kas Negara (kode billing PPh 23)",
}
BANK_FIELDS = {"bank_name", "bank_account_no", "bank_account_name"}


@dataclass(frozen=True)
class ItemIn:
    kind: str
    amount: Decimal
    vendor_invoice_id: uuid.UUID | None = None
    reference: str | None = None


def _rp(v: Decimal) -> str:
    return "Rp " + f"{int(v):,}".replace(",", ".")


async def _in_other_runs(
    session: AsyncSession, run_id: uuid.UUID | None, *, vi_id: uuid.UUID | None, kind: str
) -> Decimal:
    stmt = (
        select(func.coalesce(func.sum(PaymentRunItem.amount), 0))
        .join(PaymentRun, PaymentRun.id == PaymentRunItem.run_id)
        .where(PaymentRun.status.in_(OPEN))
    )
    if run_id is not None:
        stmt = stmt.where(PaymentRun.id != run_id)
    if vi_id is not None:
        stmt = stmt.where(PaymentRunItem.vendor_invoice_id == vi_id)
    else:
        stmt = stmt.where(PaymentRunItem.kind == kind)
    return Decimal((await session.execute(stmt)).scalar_one())


async def liability_open(session: AsyncSession, kind: str) -> Decimal:
    """Credit balance of the liability account (what is owed now)."""
    return -await ledger.balance(session, LIABILITIES[kind][1])


async def due_items(session: AsyncSession, due_by: date) -> dict[str, Any]:
    """What can be selected: approved vendor invoices due by `due_by` and liability balances,
    each net of what other open runs already hold."""
    names = dict((await session.execute(select(Vendor.code, Vendor.name))).tuples().all())
    invoices = []
    for vi in await ap.payables(session, due_by=due_by):
        left = ap.outstanding(vi) - await _in_other_runs(session, None, vi_id=vi.id, kind="")
        if left <= 0:
            continue
        invoices.append(
            {
                "vendor_invoice_id": str(vi.id),
                "number": vi.number,
                "invoice_no": vi.invoice_no,
                "vendor_code": vi.vendor_code,
                "vendor_name": names.get(vi.vendor_code, vi.vendor_code),
                "due_date": vi.due_date.isoformat() if vi.due_date else None,
                "outstanding": format(left, "f"),
                "pph23": format(vi.pph23, "f"),
            }
        )
    liabilities = []
    for kind in LIABILITIES:
        left = await liability_open(session, kind) - await _in_other_runs(
            session, None, vi_id=None, kind=kind
        )
        if left > 0:
            liabilities.append(
                {"kind": kind, "label": KIND_LABELS[kind], "outstanding": format(left, "f")}
            )
    return {"invoices": invoices, "liabilities": liabilities}


async def _validate_items(
    session: AsyncSession, run_id: uuid.UUID | None, items: list[ItemIn]
) -> list[PaymentRunItem]:
    if not items:
        raise AppError("RUN_EMPTY", "Pilih minimal satu item untuk dibayar.", status_code=422)
    payees = {**DEFAULT_PAYEES, **(await settings_store.get(session, PAYEES_KEY, {}) or {})}
    out: list[PaymentRunItem] = []
    seen: set[Any] = set()
    for i, it in enumerate(items, start=1):
        amount = Decimal(it.amount)
        if amount <= 0 or amount != amount.to_integral_value():
            raise AppError(
                "AMOUNT_INVALID", f"Item {i}: nilai harus rupiah bulat > 0.", status_code=422
            )
        key = it.vendor_invoice_id or it.kind
        if key in seen:
            raise AppError("ITEM_DUPLICATE", f"Item {i} dipilih dua kali.", status_code=422)
        seen.add(key)
        if it.kind == "vendor_invoice":
            vi = (
                await session.get(VendorInvoice, it.vendor_invoice_id)
                if it.vendor_invoice_id
                else None
            )
            if vi is None:
                raise NotFoundError("VENDOR_INVOICE_NOT_FOUND", f"Item {i}: invoice tidak ada.")
            ap.ensure_payable(vi)
            left = ap.outstanding(vi) - await _in_other_runs(session, run_id, vi_id=vi.id, kind="")
            if amount > left:
                raise ConflictError(
                    "AMOUNT_EXCEEDS_OPEN",
                    f"{vi.number}: sisa yang bisa dibayar {_rp(left)}, diminta {_rp(amount)}.",
                )
            vendor = await by_code(session, Vendor, vi.vendor_code)
            out.append(
                PaymentRunItem(
                    seq=i,
                    kind="vendor_invoice",
                    vendor_invoice_id=vi.id,
                    vendor_code=vi.vendor_code,
                    payee=vendor.name if vendor else vi.vendor_code,
                    reference=f"{vi.number} / {vi.invoice_no}"[:120],
                    amount=amount,
                )
            )
        elif it.kind in LIABILITIES:
            left = await liability_open(session, it.kind) - await _in_other_runs(
                session, run_id, vi_id=None, kind=it.kind
            )
            if amount > left:
                raise ConflictError(
                    "AMOUNT_EXCEEDS_OPEN",
                    f"{KIND_LABELS[it.kind]}: saldo utang {_rp(max(left, ZERO))}, "
                    f"diminta {_rp(amount)}.",
                )
            out.append(
                PaymentRunItem(
                    seq=i,
                    kind=it.kind,
                    payee=str(payees.get(it.kind, KIND_LABELS[it.kind])),
                    reference=(it.reference or KIND_LABELS[it.kind])[:120],
                    amount=amount,
                )
            )
        else:
            raise AppError("KIND_INVALID", f"Item {i}: jenis tidak dikenal.", status_code=422)
    return out


async def items_of(session: AsyncSession, run_id: uuid.UUID) -> list[PaymentRunItem]:
    return list(
        (
            await session.execute(
                select(PaymentRunItem)
                .where(PaymentRunItem.run_id == run_id)
                .order_by(PaymentRunItem.seq)
            )
        ).scalars()
    )


async def _bank(session: AsyncSession, bank_account_id: uuid.UUID) -> BankAccount:
    acc = await bank_service.account_or_default(session, bank_account_id)
    if not acc.is_active or acc.currency != "IDR":
        raise AppError(
            "BANK_ACCOUNT_INVALID",
            "Payment run dibayar dari rekening IDR yang aktif.",
            status_code=422,
        )
    return acc


async def create(
    session: AsyncSession,
    actor: Principal,
    *,
    pay_date: date,
    bank_account_id: uuid.UUID,
    description: str | None,
    items: list[ItemIn],
) -> PaymentRun:
    await _bank(session, bank_account_id)
    rows = await _validate_items(session, None, items)
    run = PaymentRun(
        number=await numbering.next(session, "PAY", on=pay_date),
        pay_date=pay_date,
        bank_account_id=bank_account_id,
        description=(description or "").strip() or None,
        total=sum((x.amount for x in rows), ZERO),
        status="draft",
        created_by=actor.id,
    )
    session.add(run)
    await session.flush()
    for x in rows:
        x.run_id = run.id
        session.add(x)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=run.id,
        actor_id=actor.id,
        after={"number": run.number, "total": run.total, "items": len(rows)},
    )
    return run


async def update(
    session: AsyncSession,
    actor: Principal,
    run: PaymentRun,
    *,
    pay_date: date,
    bank_account_id: uuid.UUID,
    description: str | None,
    items: list[ItemIn],
) -> PaymentRun:
    if run.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{run.number} tidak lagi draf.")
    await _bank(session, bank_account_id)
    rows = await _validate_items(session, run.id, items)
    for old in await items_of(session, run.id):
        await session.delete(old)
    await session.flush()
    before = {"total": run.total}
    run.pay_date, run.bank_account_id = pay_date, bank_account_id
    run.description = (description or "").strip() or None
    run.total = sum((x.amount for x in rows), ZERO)
    for x in rows:
        x.run_id = run.id
        session.add(x)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=run.id,
        actor_id=actor.id,
        before=before,
        after={"total": run.total, "items": len(rows)},
    )
    return run


async def submit(session: AsyncSession, actor: Principal, run: PaymentRun) -> ApprovalRequest:
    if run.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{run.number} tidak lagi draf.")
    items = await items_of(session, run.id)
    await _validate_items(session, run.id, [_as_in(x) for x in items])
    req = await engine.submit(
        session,
        actor,
        doc_type=DOC,
        doc_id=run.id,
        doc_number=run.number,
        title=f"Payment run {run.number}: {len(items)} pembayaran",
        amount=run.total,
    )
    run.status, run.request_id, run.reject_reason = "awaiting_approval", req.id, None
    await session.flush()
    return req


def _as_in(x: PaymentRunItem) -> ItemIn:
    return ItemIn(x.kind, x.amount, x.vendor_invoice_id, x.reference)


async def cancel(session: AsyncSession, actor: Principal, run: PaymentRun, reason: str) -> None:
    if run.status not in ("draft", "approved"):
        raise ConflictError(
            "CANNOT_CANCEL",
            "Hanya payment run draf atau disetujui (belum dirilis) yang bisa dibatalkan.",
        )
    run.status = "cancelled"
    await session.flush()
    await audit.record(
        session,
        action="cancel",
        entity_type=DOC,
        entity_id=run.id,
        actor_id=actor.id,
        after={"status": "cancelled"},
        note=reason.strip(),
    )


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    run = await session.get(PaymentRun, uuid.UUID(request.doc_id), with_for_update=True)
    if run is None or run.status != "awaiting_approval":
        return
    run.status, run.approved_at = "approved", datetime.now(UTC)
    await session.flush()


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    run = await session.get(PaymentRun, uuid.UUID(request.doc_id), with_for_update=True)
    if run is None or run.status != "awaiting_approval":
        return
    acted = [s for s in request.steps if s.acted_by]
    run.status, run.request_id = "draft", None
    run.reject_reason = (acted[-1].comment if acted else None) or None
    await session.flush()


async def _bank_editors(
    session: AsyncSession, vendor_codes: set[str], people: set[uuid.UUID]
) -> set[uuid.UUID]:
    """Who among `people` changed the bank details of one of these vendors."""
    if not vendor_codes or not people:
        return set()
    ids = [
        str(v)
        for v in (
            await session.execute(select(Vendor.id).where(Vendor.code.in_(vendor_codes)))
        ).scalars()
    ]
    rows = (
        await session.execute(
            select(AuditLog.actor_id, AuditLog.changed, AuditLog.action).where(
                AuditLog.entity_type == "vendors",
                AuditLog.entity_id.in_(ids),
                AuditLog.actor_id.in_(people),
            )
        )
    ).all()
    return {
        actor
        for actor, changed, action in rows
        if actor and (action == AuditAction.CREATE or BANK_FIELDS & set(changed or []))
    }


async def approvers(
    session: AsyncSession, run: PaymentRun
) -> tuple[uuid.UUID | None, set[uuid.UUID]]:
    if run.request_id is None:
        return None, set()
    req = await session.get(ApprovalRequest, run.request_id)
    if req is None:
        return None, set()
    return req.requester_id, {s.acted_by for s in req.steps if s.acted_by}


async def _before_approve(
    session: AsyncSession, request: ApprovalRequest, _step: ApprovalStep, principal: Principal
) -> None:
    run = await session.get(PaymentRun, uuid.UUID(request.doc_id))
    if run is None:
        return
    if principal.id == run.created_by:
        raise ForbiddenError(
            "SOD_SELF_APPROVAL", "Penyusun payment run tidak dapat menyetujuinya sendiri."
        )
    vendors = {x.vendor_code for x in await items_of(session, run.id) if x.vendor_code}
    if await _bank_editors(session, vendors, {principal.id}):
        raise ForbiddenError(
            "SOD_BANK_EDITOR",
            "Anda mengubah rekening bank vendor di payment run ini; tidak boleh menyetujuinya.",
        )


engine.register_document(
    DOC, on_approved=_on_approved, on_rejected=_on_rejected, before_approve=_before_approve
)


def pph23_share(vi: VendorInvoice, paid: Decimal) -> Decimal:
    """PPh 23 attributable to this payment (pro rata on a partial payment)."""
    if vi.pph23 <= 0 or vi.payable <= 0:
        return ZERO
    if paid >= vi.payable:
        return Decimal(vi.pph23)
    return (Decimal(vi.pph23) * paid / Decimal(vi.payable)).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )


async def release(session: AsyncSession, actor: Principal, run: PaymentRun) -> PaymentRun:
    """Cashier: SoD, balance check, journal, invoices paid, bank file."""
    run = await session.get(PaymentRun, run.id, with_for_update=True) or run
    if run.status != "approved":
        raise ConflictError("NOT_APPROVED", f"{run.number} belum disetujui (status {run.status}).")
    requester, approved_by = await approvers(session, run)
    if actor.id in {run.created_by, requester}:
        raise ForbiddenError(
            "SOD_PREPARER_RELEASER", "Penyusun payment run tidak boleh merilisnya."
        )
    if actor.id in approved_by:
        raise ForbiddenError(
            "SOD_APPROVER_RELEASER", "Penyetuju payment run tidak boleh merilisnya."
        )
    items = await items_of(session, run.id)
    vendors = {x.vendor_code for x in items if x.vendor_code}
    if await _bank_editors(session, vendors, {actor.id}):
        raise ForbiddenError(
            "SOD_BANK_EDITOR",
            "Anda mengubah rekening bank vendor di payment run ini; tidak boleh merilisnya.",
        )
    acc = await _bank(session, run.bank_account_id)
    # Lock the bank account row: parallel releases on one account are serialised.
    await session.get(BankAccount, acc.id, with_for_update=True)
    available = await bank_service.balance(session, acc)
    if available < run.total:
        raise ConflictError(
            "INSUFFICIENT_BALANCE",
            f"Saldo {acc.name} {_rp(available)} tidak cukup untuk {run.number} {_rp(run.total)}.",
        )
    await _validate_items(session, run.id, [_as_in(x) for x in items])
    parts: list[ledger.Part] = []
    for x in items:
        if x.kind == "vendor_invoice":
            vi = await session.get(VendorInvoice, x.vendor_invoice_id, with_for_update=True)
            assert vi is not None
            parts.append(
                ledger.Part(
                    "payable",
                    x.amount,
                    ledger.Dims(partner_type="vendor", partner_code=x.vendor_code),
                    vi.number,
                )
            )
            vi.paid_amount = Decimal(vi.paid_amount) + x.amount
            if ap.outstanding(vi) <= 0:
                vi.status = "paid"
        else:
            parts.append(ledger.Part(LIABILITIES[x.kind][0], x.amount, None, x.reference))
    parts.append(ledger.Part("bank", run.total, None, run.number))
    entry = await ledger.post_parts(
        session,
        "payment_run",
        parts,
        entry_date=run.pay_date,
        description=f"Payment run {run.number}"
        + (f" — {run.description}" if run.description else ""),
        source_type=DOC,
        source_id=run.id,
        source_number=run.number,
        by=actor.id,
        accounts={"bank": acc.gl_account},
    )
    adapter = adapters.get(acc.adapter)
    file = await bank_file(session, run, acc)
    sent_ref = await adapter.send(file)
    run.status, run.journal_id = "released", entry.id
    run.released_by, run.released_at = actor.id, datetime.now(UTC)
    run.bank_file_ref = (sent_ref or file.filename)[:80]
    await session.flush()
    await audit.record(
        session,
        action="release",
        entity_type=DOC,
        entity_id=run.id,
        actor_id=actor.id,
        after={"status": "released", "journal": entry.number, "total": run.total},
    )
    return run


async def bank_file(
    session: AsyncSession, run: PaymentRun, acc: BankAccount | None = None
) -> adapters.BankFile:
    acc = acc or await bank_service.account_or_default(session, run.bank_account_id)
    transfers = []
    for x in await items_of(session, run.id):
        v = await by_code(session, Vendor, x.vendor_code) if x.vendor_code else None
        transfers.append(
            adapters.Transfer(
                seq=x.seq,
                payee=x.payee,
                bank_name=v.bank_name if v else None,
                account_no=v.bank_account_no if v else None,
                account_name=v.bank_account_name if v else None,
                amount=x.amount,
                reference=x.reference or "",
            )
        )
    return adapters.get(acc.adapter).build(run.number, run.pay_date, acc.account_no, transfers)


async def bukti_potong(session: AsyncSession, run: PaymentRun) -> dict[str, list[dict[str, Any]]]:
    """PPh 23 withheld per vendor for the invoices this run pays."""
    out: dict[str, list[dict[str, Any]]] = {}
    for x in await items_of(session, run.id):
        if x.kind != "vendor_invoice" or not x.vendor_code:
            continue
        vi = await session.get(VendorInvoice, x.vendor_invoice_id)
        if vi is None or vi.pph23 <= 0:
            continue
        share = pph23_share(vi, x.amount)
        dpp = (
            Decimal(vi.dpp)
            if share == vi.pph23
            else (Decimal(vi.dpp) * x.amount / Decimal(vi.payable)).quantize(Decimal(1))
        )
        out.setdefault(x.vendor_code, []).append(
            {
                "number": vi.number,
                "invoice_no": vi.invoice_no,
                "invoice_date": vi.invoice_date,
                "dpp": dpp,
                "rate": vi.pph23_pct,
                "pph23": share,
            }
        )
    return out


def to_dict(
    run: PaymentRun, items: list[PaymentRunItem], acc: BankAccount | None
) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "number": run.number,
        "pay_date": run.pay_date.isoformat(),
        "bank_account": ({"id": str(acc.id), "code": acc.code, "name": acc.name} if acc else None),
        "description": run.description,
        "total": format(run.total, "f"),
        "status": run.status,
        "request_id": str(run.request_id) if run.request_id else None,
        "reject_reason": run.reject_reason,
        "created_by": str(run.created_by) if run.created_by else None,
        "released_by": str(run.released_by) if run.released_by else None,
        "released_at": run.released_at.isoformat() if run.released_at else None,
        "journal_id": str(run.journal_id) if run.journal_id else None,
        "bank_file_ref": run.bank_file_ref,
        "items": [
            {
                "seq": x.seq,
                "kind": x.kind,
                "kind_label": KIND_LABELS.get(x.kind, x.kind),
                "vendor_invoice_id": str(x.vendor_invoice_id) if x.vendor_invoice_id else None,
                "vendor_code": x.vendor_code,
                "payee": x.payee,
                "reference": x.reference,
                "amount": format(x.amount, "f"),
            }
            for x in items
        ],
    }
