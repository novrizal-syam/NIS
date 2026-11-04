"""Phase 03b: budget control service (available/check/reserve/commit/actualize/release)."""

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.core.config import get_settings
from app.notifications.models import Notification
from app.project.models import BudgetLedgerEntry, Project, ProjectBudgetLine, ProjectWbs
from app.services import budget_control as bc

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000


async def _project(
    sm: async_sessionmaker[AsyncSession],
    status: str = "locked",
    manager: User | None = None,
    number: str = "PRJ-26-001",
) -> Project:
    async with sm() as s:
        p = Project(
            number=number,
            name="Well testing",
            company_name="PT KKKS",
            status=status,
            revenue=Decimal(300 * M),
            contingency_pct=Decimal(5),
            manager_id=manager.id if manager else None,
        )
        s.add(p)
        await s.flush()
        w = ProjectWbs(project_id=p.id, code="EXEC", name="Execution", seq=1)
        s.add(w)
        await s.flush()
        for code, amount in (("EQUIP-OWN", 100 * M), ("MANPOWER", 50 * M), ("CONTINGENCY", 5 * M)):
            s.add(
                ProjectBudgetLine(
                    project_id=p.id,
                    version=0,
                    wbs_id=w.id,
                    cost_element_code=code,
                    amount=Decimal(amount),
                    source="quotation",
                    locked_reserve=code == "CONTINGENCY",
                )
            )
        await s.commit()
        return p


async def _line(s: AsyncSession, p: Project, ce: str = "EQUIP-OWN") -> bc.Line:
    return await bc.resolve(s, p.id, "EXEC", ce)


async def test_available_and_check(
    sessionmaker: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    p = await _project(sessionmaker)
    line = await _line(session, p)
    bal = await bc.available(session, line)
    assert (bal.budget, bal.available, bal.used_pct) == (Decimal(100 * M), Decimal(100 * M), 0)
    ok = await bc.check(session, line, Decimal(60 * M))
    assert ok.ok and ok.shortfall == 0
    over = await bc.check(session, line, Decimal(120 * M))
    assert not over.ok and over.code == "BUDGET_EXCEEDED" and over.shortfall == Decimal(20 * M)
    assert "kurang Rp 20.000.000" in (over.message or "")


async def test_blocked_when_not_locked_contingency_or_invalid(
    sessionmaker: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    draft = await _project(sessionmaker, status="draft", number="PRJ-26-002")
    r = await bc.check(session, await _line(session, draft), Decimal(1))
    assert r.code == "PROJECT_NOT_LOCKED"
    locked = await _project(sessionmaker)
    r = await bc.check(session, await _line(session, locked, "CONTINGENCY"), Decimal(1))
    assert r.code == "CONTINGENCY_NOT_POSTABLE"
    r = await bc.check(session, await _line(session, locked), Decimal(0))
    assert r.code == "AMOUNT_INVALID"
    with pytest.raises(bc.BudgetBlockedError) as err:
        await bc.reserve(
            session,
            await _line(session, locked, "CONTINGENCY"),
            Decimal(1),
            doc_type="purchase_requisition",
            doc_id="PR-1",
            by=None,
        )
    assert err.value.code == "CONTINGENCY_NOT_POSTABLE"


async def test_reserve_commit_actualize_release(
    sessionmaker: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    p = await _project(sessionmaker)
    line = await _line(session, p)
    pr, po, gr = (
        ("purchase_requisition", "PR-26-001"),
        ("purchase_order", "PO-26-001"),
        ("goods_receipt", "GR-26-001"),
    )

    b = await bc.reserve(session, line, Decimal(60 * M), doc_type=pr[0], doc_id=pr[1], by=None)
    assert (b.pre_commit, b.available) == (Decimal(60 * M), Decimal(40 * M))

    # PO for 55 M consumes 55 M of the PR's pre-commitment; 5 M stays with the PR.
    b = await bc.commit(
        session, line, Decimal(55 * M), doc_type=po[0], doc_id=po[1], by=None, from_doc=pr
    )
    assert (b.pre_commit, b.commit, b.available) == (
        Decimal(5 * M),
        Decimal(55 * M),
        Decimal(40 * M),
    )
    assert (await bc.held(session, line, *pr))["pre_commit"] == Decimal(5 * M)

    # Savings: the caller releases the PR remainder; it returns to available.
    b = await bc.release(
        session, line, None, bucket="pre_commit", doc_type=pr[0], doc_id=pr[1], by=None
    )
    assert (b.pre_commit, b.available) == (Decimal(0), Decimal(45 * M))

    # GR actualises the PO's commitment.
    b = await bc.actualize(
        session, line, Decimal(55 * M), doc_type=gr[0], doc_id=gr[1], by=None, from_doc=po
    )
    assert (b.commit, b.actual, b.available) == (Decimal(0), Decimal(55 * M), Decimal(45 * M))

    # Direct actual without a commitment (e.g. DOR consumables) checks available.
    b = await bc.actualize(session, line, Decimal(10 * M), doc_type="dor", doc_id="DOR-1", by=None)
    assert b.available == Decimal(35 * M)

    # A commit larger than its PR only checks the uncovered part.
    await bc.reserve(session, line, Decimal(30 * M), doc_type=pr[0], doc_id="PR-26-002", by=None)
    with pytest.raises(bc.BudgetBlockedError) as err:
        await bc.commit(
            session,
            line,
            Decimal(40 * M),
            doc_type=po[0],
            doc_id="PO-26-002",
            by=None,
            from_doc=(pr[0], "PR-26-002"),
        )
    assert err.value.code == "BUDGET_EXCEEDED"
    assert err.value.result.shortfall == Decimal(5 * M)  # needs 10 M more, only 5 M available
    b = await bc.commit(
        session,
        line,
        Decimal(35 * M),
        doc_type=po[0],
        doc_id="PO-26-002",
        by=None,
        from_doc=(pr[0], "PR-26-002"),
    )
    assert b.available == Decimal(0) and b.used_pct == Decimal("100.0")

    # Never release more than a document holds.
    with pytest.raises(Exception) as rel:
        await bc.release(
            session, line, Decimal(1), bucket="pre_commit", doc_type=pr[0], doc_id=pr[1], by=None
        )
    assert getattr(rel.value, "code", None) == "RELEASE_EXCEEDS_HELD"
    await session.commit()

    # Balances are derived from the append-only ledger.
    rows = (await session.execute(select(func.count()).select_from(BudgetLedgerEntry))).scalar_one()
    # reserve 1, commit 2, release 1, actualize 2, direct actual 1, reserve 1, commit 2;
    # the blocked commit wrote nothing.
    assert rows == 10
    with pytest.raises(DBAPIError):
        await session.execute(text("UPDATE budget_ledger SET amount = 0"))
    await session.rollback()
    with pytest.raises(DBAPIError):
        await session.execute(text("DELETE FROM budget_ledger"))
    await session.rollback()


async def test_parallel_reserves_cannot_overspend(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    p = await _project(sessionmaker)

    async def attempt(i: int) -> bool:
        async with sessionmaker() as s:
            line = await _line(s, p)
            try:
                await bc.reserve(
                    s,
                    line,
                    Decimal(60 * M),
                    doc_type="purchase_requisition",
                    doc_id=f"PR-P{i}",
                    by=None,
                )
                await asyncio.sleep(0.2)  # hold the row lock while the other request waits
                await s.commit()
                return True
            except bc.BudgetBlockedError:
                await s.rollback()
                return False

    results = await asyncio.gather(attempt(1), attempt(2))
    assert sorted(results) == [False, True]
    async with sessionmaker() as s:
        bal = await bc.available(s, await _line(s, p))
        assert bal.pre_commit == Decimal(60 * M) and bal.available == Decimal(40 * M)


async def test_80_percent_notification_once(
    sessionmaker: async_sessionmaker[AsyncSession], session: AsyncSession, make_user: MakeUser
) -> None:
    planner = await make_user("lead_engineer")
    controller = await make_user("lead_controller")
    p = await _project(sessionmaker, manager=planner)
    line = await _line(session, p)
    await bc.reserve(session, line, Decimal(79 * M), doc_type="pr", doc_id="A", by=None)
    assert (await session.execute(select(func.count()).select_from(Notification))).scalar_one() == 0
    await bc.reserve(session, line, Decimal(2 * M), doc_type="pr", doc_id="B", by=None)
    await bc.reserve(session, line, Decimal(19 * M), doc_type="pr", doc_id="C", by=None)
    await session.commit()
    notes = (await session.execute(select(Notification))).scalars().all()
    assert sorted(n.user_id for n in notes) == sorted([planner.id, controller.id])
    assert all(n.kind == "budget_warning" and "81.0%" in n.title for n in notes)


async def test_test_endpoint_and_status_table(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = await _project(sessionmaker)
    admin = await login(await make_user("admin"))
    hoo = await login(await make_user("head_of_operation"))
    body = {
        "project_id": str(p.id),
        "wbs_code": "EXEC",
        "cost_element_code": "EQUIP-OWN",
        "amount": "120000000",
    }
    r = await client.post("/api/budget/test-check", json=body, headers=admin)
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["shortfall"] == "20000000"
    r = await client.post(
        "/api/budget/test-check",
        json={**body, "amount": "85000000", "action": "reserve"},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["balance"]["available"] == "15000000"
    assert (await client.post("/api/budget/test-check", json=body, headers=hoo)).status_code == 403

    status = (await client.get(f"/api/projects/{p.id}/budget-status", headers=hoo)).json()
    rows = {x["cost_element_code"]: x for x in status["lines"]}
    assert rows["EQUIP-OWN"]["pre_commit"] == "85000000" and rows["EQUIP-OWN"]["state"] == "warning"
    assert rows["MANPOWER"]["state"] == "ok" and rows["CONTINGENCY"]["locked_reserve"] is True
    assert status["totals"]["available"] == "70000000"

    monkeypatch.setattr(get_settings(), "app_env", "production")
    assert (
        await client.post("/api/budget/test-check", json=body, headers=admin)
    ).status_code == 404
