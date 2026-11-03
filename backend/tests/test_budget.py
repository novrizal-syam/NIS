"""Phase 03a: budget edit, Controller review, approval routing, baseline lock."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.project.models import (
    BudgetVersion,
    BudgetVersionLine,
    Project,
    ProjectBudgetLine,
    ProjectWbs,
)

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000


async def _project(
    sm: async_sessionmaker[AsyncSession],
    revenue: int,
    cost: dict[str, int],
    number: str = "PRJ-26-001",
) -> Project:
    async with sm() as s:
        p = Project(
            number=number,
            name="Well testing Blok X",
            company_name="PT KKKS",
            status="draft",
            revenue=Decimal(revenue),
            contingency_pct=Decimal(5),
        )
        s.add(p)
        await s.flush()
        w = ProjectWbs(project_id=p.id, code="EXEC", name="Execution", seq=1)
        s.add(w)
        await s.flush()
        for code, amount in cost.items():
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
        p.budget_total = Decimal(sum(cost.values()))
        await s.commit()
        return p


async def _planner(
    client: AsyncClient, make_user: MakeUser, login: Login, pid: Any
) -> dict[str, str]:
    le_user = await make_user("lead_engineer")
    hoo = await login(await make_user("head_of_operation"))
    r = await client.put(
        f"/api/projects/{pid}/manager", json={"manager_id": str(le_user.id)}, headers=hoo
    )
    assert r.status_code == 200, r.text
    return await login(le_user)


async def test_budget_editor_cost_element_by_wbs(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    p = await _project(sessionmaker, 1_000 * M, {"EQUIP-OWN": 500 * M, "CONTINGENCY": 25 * M})
    other_le = await login(await make_user("lead_engineer"))
    le = await _planner(client, make_user, login, p.id)

    # Not the assigned planner -> cannot see or edit.
    assert (await client.get(f"/api/projects/{p.id}", headers=other_le)).status_code == 404

    r = await client.post(
        f"/api/projects/{p.id}/wbs", json={"code": "MOB", "name": "Mobilisasi"}, headers=le
    )
    assert r.status_code == 201
    r = await client.post(
        f"/api/projects/{p.id}/wbs", json={"code": "WELL-01", "name": "Sumur 1"}, headers=le
    )
    assert [w["code"] for w in r.json()["wbs"]] == ["EXEC", "MOB", "WELL-01"]
    cells = [
        {"wbs_code": "EXEC", "cost_element_code": "EQUIP-OWN", "amount": "400000000"},
        {"wbs_code": "WELL-01", "cost_element_code": "MANPOWER", "amount": "150000000"},
        {"wbs_code": "MOB", "cost_element_code": "LOGISTICS", "amount": "75000000"},
        {"wbs_code": "EXEC", "cost_element_code": "CONTINGENCY", "amount": "31250000"},
    ]
    r = await client.put(f"/api/projects/{p.id}/budget", json={"cells": cells}, headers=le)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_cost"] == "656250000" and d["budget_total"] == "656250000"
    assert d["margin_pct"] == "34.38" and d["planned_margin"] == "343750000"
    reserve = [c for c in d["cells"] if c["cost_element_code"] == "CONTINGENCY"]
    assert reserve and reserve[0]["locked_reserve"] is True

    bad = await client.put(
        f"/api/projects/{p.id}/budget",
        json={"cells": [{"wbs_code": "EXEC", "cost_element_code": "MANPOWER", "amount": "10.5"}]},
        headers=le,
    )
    assert bad.status_code == 422
    dup = await client.put(
        f"/api/projects/{p.id}/budget", json={"cells": cells + cells[:1]}, headers=le
    )
    assert dup.status_code == 422 and dup.json()["code"] == "DUPLICATE_CELL"
    # WBS with budget cannot be removed.
    mob = next(w for w in d["wbs"] if w["code"] == "MOB")
    r = await client.delete(f"/api/projects/{p.id}/wbs/{mob['id']}", headers=le)
    assert r.status_code == 409 and r.json()["code"] == "WBS_HAS_BUDGET"


async def _submit(client: AsyncClient, le: dict[str, str], pid: Any) -> dict[str, Any]:
    r = await client.post(f"/api/projects/{pid}/submit-budget", headers=le)
    assert r.status_code == 200, r.text
    return r.json()


async def test_margin_threshold_at_controller_review(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    # Revenue 100 M, cost 85 M -> 15 % < 20 %.
    p = await _project(sessionmaker, 100 * M, {"EQUIP-OWN": 81 * M, "CONTINGENCY": 4 * M})
    le = await _planner(client, make_user, login, p.id)
    lc = await login(await make_user("lead_controller"))
    d = await _submit(client, le, p.id)
    assert d["status"] == "controller_review" and d["margin_pct"] == "15.00" and d["margin_warning"]
    rid = d["budget_request_id"]

    r = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=lc)
    assert r.status_code == 422 and r.json()["code"] == "MARGIN_BELOW_THRESHOLD"
    assert "15.00%" in r.json()["message"] and "20%" in r.json()["message"]
    r = await client.post(f"/api/workflow/requests/{rid}/reject", json={"comment": " "}, headers=lc)
    assert r.status_code == 422  # a note is required
    r = await client.post(
        f"/api/workflow/requests/{rid}/reject",
        json={"comment": "Margin di bawah 20%, tinjau harga sewa"},
        headers=lc,
    )
    assert r.status_code == 200
    d = (await client.get(f"/api/projects/{p.id}", headers=le)).json()
    assert (
        d["status"] == "draft" and d["budget_comment"] == "Margin di bawah 20%, tinjau harga sewa"
    )
    assert d["can_edit_budget"] is True


@pytest.mark.parametrize(
    ("cost", "approver"),
    [(2_000 * M, "head_of_operation"), (2_000 * M + 1, "director")],
)
async def test_amount_routing_and_lock(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    cost: int,
    approver: str,
) -> None:
    p = await _project(
        sessionmaker, 3_000 * M, {"EQUIP-OWN": cost - 100 * M, "CONTINGENCY": 100 * M}
    )
    le = await _planner(client, make_user, login, p.id)
    lc = await login(await make_user("lead_controller"))
    users = {
        "head_of_operation": await login(await make_user("head_of_operation")),
        "director": await login(await make_user("director")),
    }
    d = await _submit(client, le, p.id)
    assert d["approvers"] == ["lead_controller", approver]
    rid = d["budget_request_id"]

    # Locked while in review.
    r = await client.put(f"/api/projects/{p.id}/budget", json={"cells": []}, headers=le)
    assert r.status_code == 409 and r.json()["code"] == "BUDGET_LOCKED"

    other = "director" if approver == "head_of_operation" else "head_of_operation"
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=users[approver])
    ).status_code == 403
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=lc)
    ).status_code == 200
    d = (await client.get(f"/api/projects/{p.id}", headers=le)).json()
    assert d["status"] == "awaiting_approval"
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=users[other])
    ).status_code == 403
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=users[approver])
    ).status_code == 200

    d = (await client.get(f"/api/projects/{p.id}", headers=le)).json()
    assert d["status"] == "locked" and d["locked_at"] and d["can_edit_budget"] is False
    base = (await client.get(f"/api/projects/{p.id}/baseline", headers=le)).json()
    assert base["version"] == 0 and base["total_cost"] == str(cost)
    reserve = [x for x in base["lines"] if x["cost_element_code"] == "CONTINGENCY"]
    assert reserve[0]["locked_reserve"] is True and reserve[0]["wbs_code"] == "EXEC"


async def test_sod_and_edit_after_lock(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    p = await _project(sessionmaker, 1_000 * M, {"EQUIP-OWN": 600 * M, "CONTINGENCY": 30 * M})
    le = await _planner(client, make_user, login, p.id)
    d = await _submit(client, le, p.id)
    rid = d["budget_request_id"]
    # The submitter never approves; one person cannot approve both steps.
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=le)
    ).status_code == 403
    both = await login(await make_user("lead_controller", "head_of_operation"))
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=both)
    ).status_code == 200
    r = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=both)
    assert r.status_code == 403 and r.json()["code"] == "SOD_ALREADY_ACTED"
    hoo = await login(await make_user("head_of_operation"))
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=hoo)
    ).status_code == 200

    # After lock: every budget change is refused by the backend...
    for method, url, body in (
        ("PUT", f"/api/projects/{p.id}/budget", {"cells": []}),
        ("POST", f"/api/projects/{p.id}/wbs", {"code": "DEMOB", "name": "Demob"}),
        ("POST", f"/api/projects/{p.id}/submit-budget", None),
    ):
        r = await client.request(method, url, json=body, headers=le)
        assert r.status_code == 409 and r.json()["code"] == "BUDGET_LOCKED", url
    # ...and the baseline cannot be changed even directly in the database.
    version = (await session.execute(select(BudgetVersion))).scalar_one()
    with pytest.raises(DBAPIError):
        await session.execute(
            text("UPDATE budget_versions SET total_cost = 1 WHERE id = :i"), {"i": version.id}
        )
    await session.rollback()
    with pytest.raises(DBAPIError):
        await session.execute(text("DELETE FROM budget_version_lines"))
    await session.rollback()
    assert (await session.execute(select(BudgetVersionLine))).scalars().all()
