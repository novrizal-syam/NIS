"""The only way to post to the general ledger (CLAUDE.md rule 7).

`post_journal()` runs inside the caller's transaction, so a journal and its source document
commit or roll back together. It refuses unbalanced entries, non-postable or inactive accounts,
Contingency, and dates in a closed fiscal period. Posted entries are corrected only by
`reverse()`."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError
from app.finance.models import JournalEntry, JournalLine
from app.master.models import Account, CostElement, FiscalPeriod
from app.services import audit, numbering, posting_rules
from app.services.audit import AuditAction

CONTINGENCY = "CONTINGENCY"
OVERRIDES_KEY = "ledger.posting_rules"

# Account codes used by posting rules (ACCOUNTING.md).
INVENTORY = "1310"
GR_IR = "2120"
CONSUMABLES = "5300"


@dataclass(frozen=True)
class JLine:
    account: str
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)
    memo: str | None = None
    project_id: uuid.UUID | None = None
    wbs_id: uuid.UUID | None = None
    cost_element: str | None = None
    cost_center: str | None = None
    asset: str | None = None
    partner_type: str | None = None
    partner_code: str | None = None


class LedgerError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status_code=422)


async def expense_account(session: AsyncSession, cost_element: str) -> str:
    """Expense account of a cost element (Contingency has none: never posted)."""
    ce = (
        await session.execute(select(CostElement).where(CostElement.code == cost_element))
    ).scalar_one_or_none()
    if ce is None or not ce.account_code:
        raise LedgerError(
            "COST_ELEMENT_NOT_POSTABLE",
            f"Elemen biaya {cost_element} tidak punya akun beban dan tidak dapat diposting.",
        )
    return ce.account_code


async def check_period(session: AsyncSession, on: date) -> str:
    code = f"{on.year}-{on.month:02d}"
    period = (
        await session.execute(
            select(FiscalPeriod).where(FiscalPeriod.year == on.year, FiscalPeriod.month == on.month)
        )
    ).scalar_one_or_none()
    if period is not None and period.status == "closed":
        raise LedgerError(
            "PERIOD_CLOSED", f"Periode {code} sudah ditutup; jurnal tidak dapat diposting."
        )
    return code


async def post_journal(
    session: AsyncSession,
    *,
    entry_date: date,
    description: str,
    lines: list[JLine],
    source_type: str,
    source_id: uuid.UUID | str,
    source_number: str | None = None,
    by: uuid.UUID | None,
    is_demo: bool = False,
    reversal_of: uuid.UUID | None = None,
    event: str | None = None,
) -> JournalEntry:
    if len(lines) < 2:
        raise LedgerError("JOURNAL_TOO_SHORT", "Jurnal minimal terdiri dari dua baris.")
    for x in lines:
        d, c = Decimal(x.debit), Decimal(x.credit)
        if d < 0 or c < 0 or (d > 0) == (c > 0):
            raise LedgerError(
                "JOURNAL_LINE_INVALID",
                f"Baris akun {x.account} harus berisi debit atau kredit (positif), tidak keduanya.",
            )
        if d != d.quantize(Decimal(1)) or c != c.quantize(Decimal(1)):
            raise LedgerError("JOURNAL_NOT_RUPIAH", "Nilai jurnal harus dalam rupiah bulat.")
        if x.cost_element == CONTINGENCY:
            raise LedgerError(
                "CONTINGENCY_NOT_POSTABLE", "Kontinjensi tidak pernah diposting langsung."
            )
    debit = sum((Decimal(x.debit) for x in lines), Decimal(0))
    credit = sum((Decimal(x.credit) for x in lines), Decimal(0))
    if debit != credit:
        raise LedgerError(
            "JOURNAL_UNBALANCED",
            f"Jurnal tidak seimbang: debit {debit} ≠ kredit {credit}.",
        )
    codes = {x.account for x in lines}
    accounts = {
        a.code: a
        for a in (await session.execute(select(Account).where(Account.code.in_(codes)))).scalars()
    }
    for code in sorted(codes):
        acc = accounts.get(code)
        if acc is None or not acc.is_active or not acc.is_postable:
            raise LedgerError(
                "ACCOUNT_NOT_POSTABLE",
                f"Akun {code} tidak ada, tidak aktif, atau bukan akun posting.",
            )
    period = await check_period(session, entry_date)
    entry = JournalEntry(
        number=await numbering.next(session, "JV", on=entry_date),
        entry_date=entry_date,
        period=period,
        description=description[:300],
        source_type=source_type,
        source_id=str(source_id),
        source_number=source_number,
        total=debit,
        reversal_of=reversal_of,
        event=event,
        posted_by=by,
        is_demo=is_demo,
    )
    session.add(entry)
    await session.flush()
    for seq, x in enumerate(lines, start=1):
        session.add(
            JournalLine(
                entry_id=entry.id,
                seq=seq,
                account_code=x.account,
                debit=Decimal(x.debit),
                credit=Decimal(x.credit),
                memo=x.memo,
                project_id=x.project_id,
                wbs_id=x.wbs_id,
                cost_element_code=x.cost_element,
                cost_center_code=x.cost_center,
                asset_code=x.asset,
                partner_type=x.partner_type,
                partner_code=x.partner_code,
            )
        )
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.POST,
        entity_type="journal_entry",
        entity_id=entry.id,
        actor_id=by,
        after={
            "number": entry.number,
            "source": f"{source_type}:{source_number or source_id}",
            "total": debit,
        },
    )
    return entry


async def lines_of(session: AsyncSession, entry_id: uuid.UUID) -> list[JournalLine]:
    rows = await session.execute(
        select(JournalLine).where(JournalLine.entry_id == entry_id).order_by(JournalLine.seq)
    )
    return list(rows.scalars())


async def reverse(
    session: AsyncSession,
    entry_id: uuid.UUID,
    *,
    on: date,
    reason: str,
    by: uuid.UUID | None,
) -> JournalEntry:
    """Post the mirror image of an entry (debits become credits) and link both."""
    orig = await session.get(JournalEntry, entry_id, with_for_update=True)
    if orig is None:
        raise LedgerError("JOURNAL_NOT_FOUND", "Jurnal tidak ditemukan.")
    if orig.reversed_by is not None or orig.reversal_of is not None:
        raise ConflictError("JOURNAL_REVERSED", f"{orig.number} sudah dibalik atau pembalik.")
    mirror = [
        JLine(
            account=x.account_code,
            debit=x.credit,
            credit=x.debit,
            memo=x.memo,
            project_id=x.project_id,
            wbs_id=x.wbs_id,
            cost_element=x.cost_element_code,
            cost_center=x.cost_center_code,
            asset=x.asset_code,
            partner_type=x.partner_type,
            partner_code=x.partner_code,
        )
        for x in await lines_of(session, orig.id)
    ]
    rev = await post_journal(
        session,
        entry_date=on,
        description=f"Pembalikan {orig.number}: {reason}",
        lines=mirror,
        source_type=orig.source_type,
        source_id=orig.source_id,
        source_number=orig.source_number,
        by=by,
        is_demo=orig.is_demo,
        reversal_of=orig.id,
        event=orig.event,
    )
    orig.reversed_by = rev.id
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.REVERSE,
        entity_type="journal_entry",
        entity_id=orig.id,
        actor_id=by,
        after={"reversal": rev.number},
        note=reason,
    )
    return rev


async def balance(session: AsyncSession, account: str, *, until: date | None = None) -> Decimal:
    """Debit minus credit of an account (optionally up to a date)."""
    stmt = (
        select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalLine.account_code == account)
    )
    if until is not None:
        stmt = stmt.where(JournalEntry.entry_date <= until)
    return Decimal((await session.execute(stmt)).scalar_one())


# ---------------------------------------------------------------- posting rules


@dataclass(frozen=True)
class Dims:
    project_id: uuid.UUID | None = None
    wbs_id: uuid.UUID | None = None
    cost_element: str | None = None
    partner_type: str | None = None
    partner_code: str | None = None
    asset: str | None = None


async def rules(session: AsyncSession) -> dict[str, posting_rules.Rule]:
    """The posting-rule table with finance overrides applied."""
    from app.setup import service as settings_store

    overrides = await settings_store.get(session, OVERRIDES_KEY, {}) or {}
    out = {}
    for key, rule in posting_rules.RULES.items():
        o = overrides.get(key) or {}
        legs = tuple(
            posting_rules.Leg(leg.role, leg.side, str(o.get(leg.role, leg.account)), leg.dims)
            for leg in rule.legs
        )
        out[key] = posting_rules.Rule(rule.event, rule.label, legs, rule.used_by, rule.example)
    return out


async def _resolve(session: AsyncSession, account: str, dims: Dims) -> str:
    if account == "@expense":
        if not dims.cost_element:
            raise LedgerError("COST_ELEMENT_REQUIRED", "Akun beban perlu elemen biaya.")
        return await expense_account(session, dims.cost_element)
    if account == "@variance":
        from app.setup import service as settings_store

        return str(await settings_store.get(session, "inventory.variance_account", "6100"))
    return account


@dataclass(frozen=True)
class Part:
    """One amount for one leg of a rule, with its own dimensions (e.g. one payable line per
    vendor in a payment run, one expense line per cost element in a settlement)."""

    role: str
    amount: Decimal
    dims: Dims | None = None
    memo: str | None = None


async def post_event(
    session: AsyncSession,
    event: str,
    amounts: dict[str, Decimal],
    *,
    entry_date: date,
    description: str,
    source_type: str,
    source_id: uuid.UUID | str,
    source_number: str | None = None,
    by: uuid.UUID | None,
    dims: Dims | None = None,
    memo: str | None = None,
    is_demo: bool = False,
    accounts: dict[str, str] | None = None,
) -> JournalEntry:
    """Post a financial event through its rule (posting_rules.RULES)."""
    return await post_parts(
        session,
        event,
        [Part(role, Decimal(v), dims, memo) for role, v in amounts.items()],
        entry_date=entry_date,
        description=description,
        source_type=source_type,
        source_id=source_id,
        source_number=source_number,
        by=by,
        is_demo=is_demo,
        accounts=accounts,
    )


async def post_parts(
    session: AsyncSession,
    event: str,
    parts: list[Part],
    *,
    entry_date: date,
    description: str,
    source_type: str,
    source_id: uuid.UUID | str,
    source_number: str | None = None,
    by: uuid.UUID | None,
    is_demo: bool = False,
    accounts: dict[str, str] | None = None,
) -> JournalEntry:
    """Like post_event, but a role may appear several times with its own dimensions.
    `accounts` replaces a role's account for this posting (e.g. the bank account's GL
    account instead of 1110)."""
    rule = (await rules(session)).get(event)
    if rule is None:
        raise LedgerError("UNKNOWN_EVENT", f"Aturan posting '{event}' tidak dikenal.")
    roles = {leg.role for leg in rule.legs}
    unknown = {p.role for p in parts} - roles
    if unknown:
        raise LedgerError("UNKNOWN_ROLE", f"Peran {sorted(unknown)} tidak ada di aturan {event}.")
    accounts = accounts or {}
    lines: list[JLine] = []
    for leg in rule.legs:
        for part in (p for p in parts if p.role == leg.role):
            amount = Decimal(part.amount)
            if amount == 0:
                continue
            dims = part.dims or Dims()
            side = leg.side if amount > 0 else ("credit" if leg.side == "debit" else "debit")
            value = abs(amount)
            lines.append(
                JLine(
                    await _resolve(session, accounts.get(leg.role, leg.account), dims),
                    debit=value if side == "debit" else Decimal(0),
                    credit=value if side == "credit" else Decimal(0),
                    memo=part.memo,
                    project_id=dims.project_id if "project" in leg.dims else None,
                    wbs_id=dims.wbs_id if "wbs" in leg.dims else None,
                    cost_element=dims.cost_element if "cost_element" in leg.dims else None,
                    asset=dims.asset if "asset" in leg.dims else None,
                    partner_type=dims.partner_type if "partner" in leg.dims else None,
                    partner_code=dims.partner_code if "partner" in leg.dims else None,
                )
            )
    return await post_journal(
        session,
        entry_date=entry_date,
        description=description,
        lines=lines,
        source_type=source_type,
        source_id=source_id,
        source_number=source_number,
        by=by,
        is_demo=is_demo,
        event=event,
    )
