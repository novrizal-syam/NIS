"""Phase 04a: purchase requisition with automatic budget check."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.notifications.models import Notification
from app.project.models import Project, ProjectBudgetLine, ProjectWbs
from app.services import budget_control as bc
from app.services.audit import AuditLog
from app.workflow import engine

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
PrincipalOf = Callable[..., Awaitable[Any]]
M = 1_000_000


async def _locked(
    sm: async_sessionmaker[AsyncSession], rent: int, manager: User | None = None
) -> Project:
    async with sm() as s:
        p = Project(
            number="PRJ-26-001",
            name="Well testing",
            company_name="PT KKKS",
            status="locked",
            revenue=Decimal(3_000 * M),
            contingency_pct=Decimal(5),
            manager_id=manager.id if manager else None,
        )
        s.add(p)
        await s.flush()
        w = ProjectWbs(project_id=p.id, code="EXEC", name="Execution", seq=1)
        s.add(w)
        await s.flush()
        for code, amount in (("EQUIP-RENT", rent), ("CONTINGENCY", 50 * M)):
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
        p.budget_total = Decimal(rent + 50 * M)
        await s.commit()
        return p


def _body(p: Project, amount: int, **kw: Any) -> dict[str, Any]:
    return {
        "project_id": str(p.id),
        "wbs_code": "EXEC",
        "cost_element_code": "EQUIP-RENT",
        "need_date": "2026-12-01",
        "delivery_location": "Lapangan Rokan, sumur RK-12",
        "purpose": "Sewa genset untuk well testing",
        "lines": [
            {
                "description": "Sewa genset 500 kVA",
                "qty": "1",
                "uom": "lot",
                "est_price": str(amount),
            }
        ],
        **kw,
    }


async def _pr(client: AsyncClient, h: dict[str, str], p: Project, amount: int) -> dict[str, Any]:
    r = await client.post("/api/procurement/prs", json=_body(p, amount), headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _submit(client: AsyncClient, h: dict[str, str], pr: dict[str, Any]) -> dict[str, Any]:
    r = await client.post(f"/api/procurement/prs/{pr['id']}/submit", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize(
    ("amount", "approver"),
    [
        (50 * M, "head_of_operation"),
        (50 * M + 1, "head_of_finance"),
        (500 * M, "head_of_finance"),
        (500 * M + 1, "director"),
    ],
)
async def test_routing_by_amount(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    amount: int,
    approver: str,
) -> None:
    p = await _locked(sessionmaker, 1_000 * M)
    eng = await login(await make_user("engineer"))
    d = await _submit(client, eng, await _pr(client, eng, p, amount))
    assert d["status"] == "awaiting_approval" and d["total"] == str(amount)
    assert [a["approver_role"] for a in d["approvals"]] == [approver]


async def test_blocked_with_shortfall_and_bcr_prefill(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    p = await _locked(sessionmaker, 55 * M)
    eng = await login(await make_user("engineer"))
    d = await _submit(client, eng, await _pr(client, eng, p, 150_500_000))
    assert d["status"] == "blocked" and d["request_id"] is None
    assert d["shortfall"] == "95500000" and d["bcr_suggestion"] == "96000000"
    assert "kurang Rp 95.500.000" in d["block_message"]
    assert d["can_request_bcr"] is True and d["budget"]["available"] == "55000000"
    # Blocked PRs can be edited and resubmitted; smaller amount fits.
    body = _body(p, 50 * M)
    r = await client.put(f"/api/procurement/prs/{d['id']}", json=body, headers=eng)
    assert r.status_code == 200 and r.json()["total"] == "50000000"
    d = await _submit(client, eng, r.json())
    assert d["status"] == "awaiting_approval"
    locked = await client.put(f"/api/procurement/prs/{d['id']}", json=body, headers=eng)
    assert locked.status_code == 409 and locked.json()["code"] == "PR_LOCKED"


async def test_contingency_and_unlocked_project_refused(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    p = await _locked(sessionmaker, 55 * M)
    eng = await login(await make_user("engineer"))
    r = await client.post(
        "/api/procurement/prs", json=_body(p, M, cost_element_code="CONTINGENCY"), headers=eng
    )
    assert r.status_code == 422 and r.json()["code"] == "CONTINGENCY_NOT_POSTABLE"
    async with sessionmaker() as s:
        row = await s.get(Project, p.id)
        assert row is not None
        row.status = "draft"
        await s.commit()
    r = await client.post("/api/procurement/prs", json=_body(p, M), headers=eng)
    assert r.status_code == 422 and r.json()["code"] == "PROJECT_NOT_LOCKED"


async def test_bcr_approval_moves_pr_second_stays_blocked(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    planner_user = await make_user("lead_engineer")
    p = await _locked(sessionmaker, 55 * M, manager=planner_user)
    planner = await login(planner_user)
    eng_user = await make_user("engineer")
    eng = await login(eng_user)
    director = await login(await make_user("director"))
    first = await _submit(client, eng, await _pr(client, eng, p, 150 * M))  # short 95 M
    second = await _submit(client, eng, await _pr(client, eng, p, 30 * M))  # fits alone
    assert second["status"] == "awaiting_approval"
    third = await _submit(client, eng, await _pr(client, eng, p, 80 * M))  # short 25 M
    assert (first["status"], third["status"]) == ("blocked", "blocked")

    r = await client.post(
        f"/api/projects/{p.id}/bcrs",
        json={
            "wbs_code": "EXEC",
            "cost_element_code": "EQUIP-RENT",
            "amount": first["bcr_suggestion"],
            "source": "budget_increase",
            "reason": "scope_change",
            "justification": "Genset tambahan untuk sumur RK-12",
            "ref_doc_type": "purchase_requisition",
            "ref_doc_id": first["id"],
        },
        headers=planner,
    )
    assert r.status_code == 201, r.text
    bcr = r.json()
    assert (
        await client.post(
            f"/api/workflow/requests/{bcr['request_id']}/approve", json={}, headers=director
        )
    ).status_code == 200

    d1 = (await client.get(f"/api/procurement/prs/{first['id']}", headers=eng)).json()
    d3 = (await client.get(f"/api/procurement/prs/{third['id']}", headers=eng)).json()
    # Budget now 150 M: the referenced PR (150 M) goes first and takes it all; the third stays.
    assert d1["status"] == "awaiting_approval" and d1["linked_bcr"]["number"] == bcr["number"]
    assert d3["status"] == "blocked" and d3["shortfall"] == "80000000"
    notes = (
        (await session.execute(select(Notification).where(Notification.kind == "pr_unblocked")))
        .scalars()
        .all()
    )
    assert [n.user_id for n in notes] == [eng_user.id]
    log = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.entity_id == first["id"], AuditLog.note.ilike("%setelah BCR-%")
                )
            )
        )
        .scalars()
        .all()
    )
    assert log


async def test_final_approval_rechecks_and_parallel_cannot_overspend(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    principal_of: PrincipalOf,
) -> None:
    p = await _locked(sessionmaker, 55 * M)
    eng = await login(await make_user("engineer"))
    a = await _submit(client, eng, await _pr(client, eng, p, 40 * M))
    b = await _submit(client, eng, await _pr(client, eng, p, 40 * M))
    assert a["status"] == b["status"] == "awaiting_approval"  # each fits alone
    approvers = [await make_user("head_of_operation"), await make_user("head_of_operation")]

    async def approve(user: User, rid: str) -> None:
        async with sessionmaker() as s:
            principal = await principal_of(user, s)
            await engine.approve(s, principal, uuid.UUID(rid))
            await asyncio.sleep(0.2)
            await s.commit()

    await asyncio.gather(
        approve(approvers[0], a["request_id"]), approve(approvers[1], b["request_id"])
    )
    da = (await client.get(f"/api/procurement/prs/{a['id']}", headers=eng)).json()
    db = (await client.get(f"/api/procurement/prs/{b['id']}", headers=eng)).json()
    assert sorted([da["status"], db["status"]]) == ["approved", "blocked"]
    blocked = da if da["status"] == "blocked" else db
    assert blocked["shortfall"] == "25000000"
    async with sessionmaker() as s:
        bal = await bc.available(s, await bc.resolve(s, p.id, "EXEC", "EQUIP-RENT"))
        assert bal.pre_commit == Decimal(40 * M) and bal.available == Decimal(15 * M)


async def test_requester_cannot_approve_reject_needs_reason_cancel_releases(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    p = await _locked(sessionmaker, 100 * M)
    both = await login(await make_user("engineer", "head_of_operation"))
    hoo = await login(await make_user("head_of_operation"))
    d = await _submit(client, both, await _pr(client, both, p, 30 * M))
    rid = d["request_id"]
    r = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=both)
    assert r.status_code == 403 and r.json()["code"] == "SOD_SELF_APPROVAL"
    r = await client.post(f"/api/workflow/requests/{rid}/reject", json={"comment": ""}, headers=hoo)
    assert r.status_code == 422
    r = await client.post(
        f"/api/workflow/requests/{rid}/reject",
        json={"comment": "Harga terlalu tinggi"},
        headers=hoo,
    )
    assert r.status_code == 200
    d = (await client.get(f"/api/procurement/prs/{d['id']}", headers=both)).json()
    assert d["status"] == "draft" and d["reject_reason"] == "Harga terlalu tinggi"

    d = await _submit(client, both, d)
    assert (
        await client.post(f"/api/workflow/requests/{d['request_id']}/approve", json={}, headers=hoo)
    ).status_code == 200
    d = (await client.get(f"/api/procurement/prs/{d['id']}", headers=both)).json()
    assert d["status"] == "approved" and d["budget"]["held_by_pr"] == "30000000"
    assert d["budget"]["available"] == "70000000"

    r = await client.post(
        f"/api/procurement/prs/{d['id']}/cancel", json={"reason": "x"}, headers=both
    )
    assert r.status_code == 422
    r = await client.post(
        f"/api/procurement/prs/{d['id']}/cancel",
        json={"reason": "Proyek ditunda klien"},
        headers=both,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "cancelled" and d["budget"]["available"] == "100000000"
    assert d["budget"]["held_by_pr"] == "0"
