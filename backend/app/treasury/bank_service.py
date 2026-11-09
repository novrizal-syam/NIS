"""Bank accounts, balances from the GL, bank reconciliation (07b).

Reconciliation pairs one statement line (bank_lines, debits negative) with one GL line on the
bank account's GL account (debit - credit equal to the statement amount):
  1. reference: the journal's number or source number appears in the statement text, same
     amount, value date within RECON_DAYS days;
  2. amount_date: exactly one unreconciled GL line with the same amount within RECON_DAYS days.
Everything else stays on the unmatched list for a manual match.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.billing.models import BankLine
from app.core.errors import AppError, ConflictError, NotFoundError
from app.finance.models import JournalEntry, JournalLine
from app.master.models import Account
from app.services import audit, ledger
from app.services.audit import AuditAction
from app.treasury.models import BankAccount

RECON_DAYS = 3
ZERO = Decimal(0)


async def account_or_default(
    session: AsyncSession, account_id: uuid.UUID | None = None
) -> BankAccount:
    if account_id is not None:
        acc = await session.get(BankAccount, account_id)
    else:
        acc = (
            await session.execute(
                select(BankAccount)
                .where(BankAccount.is_active.is_(True))
                .order_by(BankAccount.is_default.desc(), BankAccount.code)
                .limit(1)
            )
        ).scalar_one_or_none()
    if acc is None:
        raise NotFoundError("BANK_ACCOUNT_NOT_FOUND", "Rekening bank tidak ditemukan.")
    return acc


async def balance(session: AsyncSession, acc: BankAccount, until: date | None = None) -> Decimal:
    return await ledger.balance(session, acc.gl_account, until=until)


async def accounts(session: AsyncSession) -> list[dict[str, Any]]:
    rows = list((await session.execute(select(BankAccount).order_by(BankAccount.code))).scalars())
    open_lines = dict(
        (
            await session.execute(
                select(BankLine.bank_account_id, func.count())
                .where(BankLine.journal_line_id.is_(None))
                .group_by(BankLine.bank_account_id)
            )
        )
        .tuples()
        .all()
    )
    out = []
    for a in rows:
        out.append(
            {
                "id": str(a.id),
                "code": a.code,
                "name": a.name,
                "bank_name": a.bank_name,
                "account_no": a.account_no,
                "currency": a.currency,
                "gl_account": a.gl_account,
                "adapter": a.adapter,
                "is_default": a.is_default,
                "is_active": a.is_active,
                "balance": format(await balance(session, a), "f"),
                "unreconciled_statement_lines": open_lines.get(a.id, 0),
            }
        )
    return out


async def save_account(
    session: AsyncSession, actor: Principal, data: dict[str, Any], acc: BankAccount | None = None
) -> BankAccount:
    gl = await session.get(Account, data["gl_account"])
    if gl is None or not gl.is_postable or gl.account_type != "asset":
        raise AppError(
            "GL_ACCOUNT_INVALID",
            "Akun GL rekening bank harus akun aset yang bisa diposting (mis. 1110).",
            status_code=422,
        )
    clash = (
        await session.execute(
            select(BankAccount.id).where(
                BankAccount.gl_account == data["gl_account"],
                BankAccount.id != (acc.id if acc else uuid.uuid4()),
            )
        )
    ).first()
    if clash:
        raise ConflictError(
            "GL_ACCOUNT_TAKEN", f"Akun GL {data['gl_account']} sudah dipakai rekening lain."
        )
    before = None
    if acc is None:
        acc = BankAccount(created_by=actor.id, **data)
        session.add(acc)
    else:
        before = {k: getattr(acc, k) for k in data}
        for k, v in data.items():
            setattr(acc, k, v)
    if data.get("is_default"):
        for other in (await session.execute(select(BankAccount))).scalars():
            if other is not acc:
                other.is_default = False
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE if before is None else AuditAction.UPDATE,
        entity_type="bank_account",
        entity_id=acc.id,
        actor_id=actor.id,
        before=before,
        after=data,
    )
    return acc


# ---------------------------------------------------------------- reconciliation


async def _gl_lines(
    session: AsyncSession, acc: BankAccount, *, only_open: bool = True
) -> list[tuple[JournalLine, JournalEntry]]:
    stmt = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalLine.account_code == acc.gl_account)
    )
    if only_open:
        taken = select(BankLine.journal_line_id).where(BankLine.journal_line_id.is_not(None))
        stmt = stmt.where(JournalLine.id.not_in(taken))
    return list((await session.execute(stmt.order_by(JournalEntry.entry_date))).tuples().all())


def _signed(x: JournalLine) -> Decimal:
    return Decimal(x.debit) - Decimal(x.credit)


async def auto_match(session: AsyncSession, actor: Principal, acc: BankAccount) -> int:
    lines = list(
        (
            await session.execute(
                select(BankLine)
                .where(BankLine.bank_account_id == acc.id, BankLine.journal_line_id.is_(None))
                .order_by(BankLine.value_date)
            )
        ).scalars()
    )
    gl = await _gl_lines(session, acc)
    used: set[uuid.UUID] = set()
    matched = 0
    for b in lines:
        near = [
            (jl, je)
            for jl, je in gl
            if jl.id not in used
            and _signed(jl) == b.amount
            and abs((je.entry_date - b.value_date).days) <= RECON_DAYS
        ]
        text = f"{b.description} {b.reference or ''}".upper()
        by_ref = [
            (jl, je)
            for jl, je in near
            if je.number.upper() in text or (je.source_number and je.source_number.upper() in text)
        ]
        pick, rule = (by_ref[0], "reference") if len(by_ref) == 1 else (None, None)
        if pick is None and len(near) == 1:
            pick, rule = near[0], "amount_date"
        if pick is None:
            continue
        used.add(pick[0].id)
        b.journal_line_id, b.recon_rule = pick[0].id, rule
        b.reconciled_by, b.reconciled_at = actor.id, datetime.now(UTC)
        matched += 1
    await session.flush()
    return matched


async def match(
    session: AsyncSession, actor: Principal, line: BankLine, journal_line_id: uuid.UUID
) -> BankLine:
    if line.journal_line_id is not None:
        raise ConflictError("LINE_RECONCILED", "Baris mutasi sudah direkonsiliasi.")
    acc = await account_or_default(session, line.bank_account_id)
    jl = await session.get(JournalLine, journal_line_id)
    if jl is None or jl.account_code != acc.gl_account:
        raise AppError(
            "GL_LINE_INVALID",
            f"Baris jurnal bukan milik akun {acc.gl_account} rekening ini.",
            status_code=422,
        )
    if _signed(jl) != line.amount:
        raise AppError(
            "AMOUNT_MISMATCH",
            f"Nilai berbeda: mutasi {line.amount}, jurnal {_signed(jl)}. "
            "Selisih (mis. biaya bank) dicatat dulu dengan jurnal manual.",
            status_code=422,
        )
    taken = (
        await session.execute(select(BankLine.id).where(BankLine.journal_line_id == jl.id))
    ).first()
    if taken:
        raise ConflictError("GL_LINE_RECONCILED", "Baris jurnal sudah direkonsiliasi.")
    line.journal_line_id, line.recon_rule = jl.id, "manual"
    line.reconciled_by, line.reconciled_at = actor.id, datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        action="reconcile",
        entity_type="bank_line",
        entity_id=line.id,
        actor_id=actor.id,
        after={"journal_line_id": str(jl.id)},
    )
    return line


async def unmatch(session: AsyncSession, actor: Principal, line: BankLine) -> BankLine:
    if line.journal_line_id is None:
        raise ConflictError("LINE_NOT_RECONCILED", "Baris mutasi belum direkonsiliasi.")
    before = str(line.journal_line_id)
    line.journal_line_id = line.recon_rule = line.reconciled_by = line.reconciled_at = None
    await session.flush()
    await audit.record(
        session,
        action="unreconcile",
        entity_type="bank_line",
        entity_id=line.id,
        actor_id=actor.id,
        before={"journal_line_id": before},
    )
    return line


async def reconciliation(
    session: AsyncSession, acc: BankAccount, as_of: date | None = None
) -> dict[str, Any]:
    """Statement vs book for one account: unmatched statement lines, unmatched GL lines and
    the reconciled statement balance."""
    stmt_rows = list(
        (
            await session.execute(
                select(BankLine)
                .where(BankLine.bank_account_id == acc.id)
                .order_by(BankLine.value_date, BankLine.created_at)
            )
        ).scalars()
    )
    if as_of:
        stmt_rows = [b for b in stmt_rows if b.value_date <= as_of]
    gl_open = [
        (jl, je)
        for jl, je in await _gl_lines(session, acc)
        if as_of is None or je.entry_date <= as_of
    ]
    book = await balance(session, acc, as_of)
    statement_total = sum((b.amount for b in stmt_rows), ZERO)
    return {
        "account": {"id": str(acc.id), "code": acc.code, "name": acc.name},
        "book_balance": format(book, "f"),
        "statement_movement": format(statement_total, "f"),
        "reconciled": sum(1 for b in stmt_rows if b.journal_line_id),
        "unmatched_statement": [
            {
                "id": str(b.id),
                "value_date": b.value_date.isoformat(),
                "amount": format(b.amount, "f"),
                "description": b.description,
                "reference": b.reference,
                "import_ref": b.import_ref,
            }
            for b in stmt_rows
            if b.journal_line_id is None
        ],
        "unmatched_book": [
            {
                "id": str(jl.id),
                "entry_date": je.entry_date.isoformat(),
                "number": je.number,
                "source_number": je.source_number,
                "description": je.description,
                "amount": format(_signed(jl), "f"),
            }
            for jl, je in gl_open
        ],
    }
