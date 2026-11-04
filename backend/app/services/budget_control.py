"""Budget control: the ONLY way to consume a project budget (CLAUDE.md rule 8).

A budget line is (project, WBS, cost element). For each line:

    available = budget - pre_commit - commit - actual

`budget` is the current approved amount (project_budget_lines); the other three are sums of the
append-only `budget_ledger`. Every mutating call locks the budget line row (SELECT ... FOR UPDATE)
before reading balances, so two parallel requests on the same line are serialised and cannot
overspend. Nothing here commits: callers commit together with their source document.

    reserve()    PR approved          -> pre_commit +
    commit()     PO approved          -> commit +, consumes the PR's pre_commit
    actualize()  GR / DOR / issue ... -> actual +, consumes the PO's commit (if any)
    release()    cancel / savings     -> lowers what a document holds in a bucket
"""

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.project.models import BudgetLedgerEntry, Project, ProjectBudgetLine, ProjectWbs

Bucket = Literal["pre_commit", "commit", "actual"]
BUCKETS: tuple[Bucket, ...] = ("pre_commit", "commit", "actual")
CONTINGENCY = "CONTINGENCY"
WARN_PCT = Decimal(80)


@dataclass(frozen=True)
class Line:
    project_id: uuid.UUID
    wbs_id: uuid.UUID
    cost_element_code: str


@dataclass(frozen=True)
class Balance:
    budget: Decimal
    pre_commit: Decimal
    commit: Decimal
    actual: Decimal

    @property
    def used(self) -> Decimal:
        return self.pre_commit + self.commit + self.actual

    @property
    def available(self) -> Decimal:
        return self.budget - self.used

    @property
    def used_pct(self) -> Decimal:
        if self.budget <= 0:
            return Decimal(100) if self.used > 0 else Decimal(0)
        return (self.used / self.budget * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    code: str | None
    message: str | None
    shortfall: Decimal
    balance: Balance | None


class BudgetBlockedError(AppError):
    """Raised by reserve/commit/actualize when the budget does not allow the amount."""

    status_code = 409

    def __init__(self, result: CheckResult) -> None:
        super().__init__(
            result.code or "BUDGET_BLOCKED",
            result.message or "Anggaran tidak cukup.",
            details={"shortfall": str(result.shortfall)},
        )
        self.result = result


async def resolve(
    session: AsyncSession, project_id: uuid.UUID, wbs_code: str, cost_element_code: str
) -> Line:
    wbs = (
        await session.execute(
            select(ProjectWbs.id).where(
                ProjectWbs.project_id == project_id, ProjectWbs.code == wbs_code
            )
        )
    ).scalar_one_or_none()
    if wbs is None:
        raise NotFoundError("WBS_NOT_FOUND", f"WBS {wbs_code} tidak ada di proyek ini.")
    return Line(project_id, wbs, cost_element_code)


async def _budget_row(session: AsyncSession, line: Line, lock: bool) -> ProjectBudgetLine | None:
    stmt = select(ProjectBudgetLine).where(
        ProjectBudgetLine.project_id == line.project_id,
        ProjectBudgetLine.wbs_id == line.wbs_id,
        ProjectBudgetLine.cost_element_code == line.cost_element_code,
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def _sums(
    session: AsyncSession, line: Line, doc: tuple[str, str] | None = None
) -> dict[str, Decimal]:
    cond = [
        BudgetLedgerEntry.project_id == line.project_id,
        BudgetLedgerEntry.wbs_id == line.wbs_id,
        BudgetLedgerEntry.cost_element_code == line.cost_element_code,
    ]
    if doc is not None:
        cond += [BudgetLedgerEntry.doc_type == doc[0], BudgetLedgerEntry.doc_id == doc[1]]
    rows = await session.execute(
        select(BudgetLedgerEntry.bucket, func.coalesce(func.sum(BudgetLedgerEntry.amount), 0))
        .where(and_(*cond))
        .group_by(BudgetLedgerEntry.bucket)
    )
    out: dict[str, Decimal] = dict.fromkeys(BUCKETS, Decimal(0))
    for bucket, total in rows.tuples():
        out[bucket] = Decimal(total)
    return out


async def _balance(session: AsyncSession, line: Line, row: ProjectBudgetLine | None) -> Balance:
    s = await _sums(session, line)
    return Balance(
        budget=row.amount if row is not None else Decimal(0),
        pre_commit=s["pre_commit"],
        commit=s["commit"],
        actual=s["actual"],
    )


async def available(session: AsyncSession, line: Line) -> Balance:
    """Current balances of one budget line (no lock; for display)."""
    return await _balance(session, line, await _budget_row(session, line, lock=False))


async def held(session: AsyncSession, line: Line, doc_type: str, doc_id: str) -> dict[str, Decimal]:
    """What one document holds on a line, per bucket."""
    return await _sums(session, line, (doc_type, str(doc_id)))


def _rp(v: Decimal) -> str:
    from app.services.money import format_idr

    return format_idr(v)


async def _check(session: AsyncSession, line: Line, amount: Decimal, lock: bool) -> CheckResult:
    if amount <= 0 or amount != amount.to_integral_value():
        return CheckResult(
            False, "AMOUNT_INVALID", "Nilai harus rupiah bulat lebih dari 0.", Decimal(0), None
        )
    project = await session.get(Project, line.project_id)
    if project is None:
        return CheckResult(False, "PROJECT_NOT_FOUND", "Proyek tidak ditemukan.", amount, None)
    if project.status != "locked":
        return CheckResult(
            False,
            "PROJECT_NOT_LOCKED",
            f"Anggaran {project.number} belum terkunci; belum boleh dipakai.",
            amount,
            None,
        )
    if line.cost_element_code == CONTINGENCY:
        return CheckResult(
            False,
            "CONTINGENCY_NOT_POSTABLE",
            "Kontinjensi adalah cadangan terkunci; lepaskan lewat BCR, jangan dipakai langsung.",
            amount,
            None,
        )
    row = await _budget_row(session, line, lock=lock)
    bal = await _balance(session, line, row)
    if amount > bal.available:
        shortfall = amount - max(bal.available, Decimal(0))
        return CheckResult(
            False,
            "BUDGET_EXCEEDED",
            f"Anggaran tidak cukup: tersedia {_rp(max(bal.available, Decimal(0)))}, "
            f"diminta {_rp(amount)}, kurang {_rp(shortfall)}.",
            shortfall,
            bal,
        )
    return CheckResult(True, None, None, Decimal(0), bal)


async def check(session: AsyncSession, line: Line, amount: Decimal) -> CheckResult:
    """Would `amount` fit? Read-only; returns the shortfall when it does not."""
    return await _check(session, line, Decimal(amount), lock=False)


def _row(
    line: Line,
    kind: str,
    bucket: Bucket,
    amount: Decimal,
    doc_type: str,
    doc_id: str,
    by: uuid.UUID | None,
    note: str | None,
) -> BudgetLedgerEntry:
    return BudgetLedgerEntry(
        project_id=line.project_id,
        wbs_id=line.wbs_id,
        cost_element_code=line.cost_element_code,
        kind=kind,
        bucket=bucket,
        amount=amount,
        doc_type=doc_type,
        doc_id=str(doc_id),
        by=by,
        note=note,
    )


async def _consume(
    session: AsyncSession,
    line: Line,
    kind: str,
    bucket: Bucket,
    source: tuple[str, str] | None,
    amount: Decimal,
    by: uuid.UUID | None,
) -> Decimal:
    """Lower what the source document holds in `bucket` by up to `amount`; returns how much."""
    if source is None:
        return Decimal(0)
    have = (await held(session, line, source[0], source[1]))[bucket]
    take = min(have, amount)
    if take > 0:
        session.add(_row(line, kind, bucket, -take, source[0], source[1], by, None))
    return take


async def _post(
    session: AsyncSession,
    line: Line,
    *,
    kind: str,
    bucket: Bucket,
    amount: Decimal,
    doc_type: str,
    doc_id: str,
    by: uuid.UUID | None,
    consumes: tuple[Bucket, tuple[str, str]] | None,
    note: str | None,
) -> Balance:
    amount = Decimal(amount)
    # Lock first, then measure what the source frees, then check only the net new need.
    first = await _check(session, line, amount, lock=True)
    if first.code in {
        "AMOUNT_INVALID",
        "PROJECT_NOT_FOUND",
        "PROJECT_NOT_LOCKED",
        "CONTINGENCY_NOT_POSTABLE",
    }:
        raise BudgetBlockedError(first)
    freed = Decimal(0)
    if consumes is not None:
        have = (await held(session, line, consumes[1][0], consumes[1][1]))[consumes[0]]
        freed = min(have, amount)
    net = amount - freed
    if net > 0:
        result = await _check(session, line, net, lock=False)
        if not result.ok:
            raise BudgetBlockedError(result)
    if consumes is not None:
        await _consume(session, line, kind, consumes[0], consumes[1], amount, by)
    session.add(_row(line, kind, bucket, amount, doc_type, doc_id, by, note))
    await session.flush()
    bal = await available(session, line)
    await _alert(session, line, bal)
    return bal


async def reserve(
    session: AsyncSession,
    line: Line,
    amount: Decimal,
    *,
    doc_type: str,
    doc_id: str,
    by: uuid.UUID | None,
    note: str | None = None,
) -> Balance:
    """Pre-commitment (e.g. approved PR). Blocked when it does not fit."""
    return await _post(
        session,
        line,
        kind="pre_commit",
        bucket="pre_commit",
        amount=amount,
        doc_type=doc_type,
        doc_id=doc_id,
        by=by,
        consumes=None,
        note=note,
    )


async def commit(
    session: AsyncSession,
    line: Line,
    amount: Decimal,
    *,
    doc_type: str,
    doc_id: str,
    by: uuid.UUID | None,
    from_doc: tuple[str, str] | None = None,
    note: str | None = None,
) -> Balance:
    """Commitment (e.g. PO). Consumes up to `amount` of `from_doc`'s pre-commitment; only the
    part not covered by it is checked against available. Savings stay with `from_doc` until
    the caller releases them."""
    return await _post(
        session,
        line,
        kind="commit",
        bucket="commit",
        amount=amount,
        doc_type=doc_type,
        doc_id=doc_id,
        by=by,
        consumes=("pre_commit", (from_doc[0], str(from_doc[1]))) if from_doc else None,
        note=note,
    )


async def actualize(
    session: AsyncSession,
    line: Line,
    amount: Decimal,
    *,
    doc_type: str,
    doc_id: str,
    by: uuid.UUID | None,
    from_doc: tuple[str, str] | None = None,
    note: str | None = None,
) -> Balance:
    """Actual cost (GR, DOR, stock issue, cash-advance settlement, payroll allocation).
    Consumes up to `amount` of `from_doc`'s commitment when given."""
    return await _post(
        session,
        line,
        kind="actual",
        bucket="actual",
        amount=amount,
        doc_type=doc_type,
        doc_id=doc_id,
        by=by,
        consumes=("commit", (from_doc[0], str(from_doc[1]))) if from_doc else None,
        note=note,
    )


async def release(
    session: AsyncSession,
    line: Line,
    amount: Decimal | None,
    *,
    bucket: Bucket,
    doc_type: str,
    doc_id: str,
    by: uuid.UUID | None,
    note: str | None = None,
) -> Balance:
    """Give back what a document holds in `bucket` (all of it when amount is None), e.g. a
    cancelled PR or PO savings. Never more than the document holds."""
    await _budget_row(session, line, lock=True)
    have = (await held(session, line, doc_type, str(doc_id)))[bucket]
    take = have if amount is None else Decimal(amount)
    if take < 0 or take != take.to_integral_value():
        raise AppError("AMOUNT_INVALID", "Nilai harus rupiah bulat.", status_code=422)
    if take > have:
        raise AppError(
            "RELEASE_EXCEEDS_HELD",
            f"Dokumen hanya memegang {_rp(have)} pada baris ini; tidak dapat melepas {_rp(take)}.",
            status_code=409,
        )
    if take > 0:
        session.add(_row(line, "release", bucket, -take, doc_type, str(doc_id), by, note))
        await session.flush()
    return await available(session, line)


async def _alert(session: AsyncSession, line: Line, bal: Balance) -> None:
    """Notify the Planner and Lead Controllers once per line when usage reaches 80 %."""
    if bal.used_pct < WARN_PCT:
        return
    from app.notifications import service as notifications  # local: avoid import cycle
    from app.workflow.engine import holders_of_role

    project = await session.get(Project, line.project_id)
    wbs = await session.get(ProjectWbs, line.wbs_id)
    assert project is not None and wbs is not None
    users = await holders_of_role(session, "lead_controller")
    if project.manager_id:
        users.append(project.manager_id)
    exhausted = bal.available <= 0
    await notifications.notify(
        session,
        users,
        kind="budget_warning",
        title=f"Anggaran {project.number} {wbs.code}/{line.cost_element_code} "
        f"{'habis' if exhausted else 'terpakai ' + str(bal.used_pct) + '%'}",
        body=f"Terpakai {_rp(bal.used)} dari {_rp(bal.budget)}; tersedia "
        f"{_rp(max(bal.available, Decimal(0)))}.",
        link=f"/proyek/{project.id}",
        dedupe_key=f"budget80:{project.id}:{wbs.id}:{line.cost_element_code}",
    )


async def project_status(
    session: AsyncSession, project_id: uuid.UUID
) -> list[tuple[Line, str, Balance]]:
    """Every budget line of a project with balances (for the project detail table)."""
    rows = await session.execute(
        select(ProjectBudgetLine, ProjectWbs.code)
        .join(ProjectWbs, ProjectWbs.id == ProjectBudgetLine.wbs_id)
        .where(ProjectBudgetLine.project_id == project_id)
        .order_by(ProjectWbs.seq, ProjectBudgetLine.cost_element_code)
    )
    out = []
    for row, code in rows.tuples():
        line = Line(project_id, row.wbs_id, row.cost_element_code)
        out.append((line, code, await _balance(session, line, row)))
    return out
