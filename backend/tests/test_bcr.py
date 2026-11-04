"""Phase 03c: Budget Change Request and budget versions."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.project import bcr_service
from app.services import budget_control as bc
from tests.test_budget import _planner, _project, _submit

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000


async def _locked(
    client: AsyncClient, make_user: MakeUser, login: Login, sm: async_sessionmaker[AsyncSession]
) -> tuple[Any, dict[str, str], dict[str, str], dict[str, str]]:
    """Locked project: revenue 1,000 M; EQUIP-OWN 500 M + MANPOWER 100 M + contingency 30 M
    = 630 M total (baseline v0). Returns project, planner, Head of Operation, Director."""
    p = await _project(
        sm, 1_000 * M, {"EQUIP-OWN": 500 * M, "MANPOWER": 100 * M, "CONTINGENCY": 30 * M}
    )
    le = await _planner(client, make_user, login, p.id)
    lc = await login(await make_user("lead_controller"))
    hoo = await login(await make_user("head_of_operation"))
    director = await login(await make_user("director"))
    rid = (await _submit(client, le, p.id))["budget_request_id"]
    for h in (lc, hoo):
        assert (
            await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=h)
        ).status_code == 200
    return p, le, hoo, director


def _bcr(source: str, amount: int, **kw: Any) -> dict[str, Any]:
    return {
        "wbs_code": "EXEC",
        "cost_element_code": "EQUIP-OWN",
        "amount": str(amount),
        "source": source,
        "reason": "scope_change",
        "justification": "Tambahan hari operasi pompa sesuai VO klien",
        **kw,
    }


@pytest.mark.parametrize(
    ("body", "approver"),
    [
        (_bcr("budget_increase", 63 * M), "head_of_operation"),  # exactly 10 % of 630 M
        (
            _bcr("budget_increase", 63 * M + 1),
            "director",
        ),  # rounds to 10.00 % (asserted below)
        (_bcr("budget_increase", 64 * M), "director"),  # 10.16 %
        (_bcr("contingency_release", 20 * M), "head_of_operation"),
        (
            _bcr("transfer", 20 * M, from_wbs_code="EXEC", from_cost_element_code="MANPOWER"),
            "head_of_operation",
        ),
        (
            _bcr("budget_increase", 10 * M, revenue_change="15000000", reason="client_variation"),
            "director",
        ),
    ],
)
async def test_routing_at_10_percent(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    body: dict[str, Any],
    approver: str,
) -> None:
    p, le, _, _ = await _locked(client, make_user, login, sessionmaker)
    r = await client.post(f"/api/projects/{p.id}/bcrs", json=body, headers=le)
    assert r.status_code == 201, r.text
    if body["amount"] == str(63 * M + 1):
        # 63,000,001 / 630,000,000 = 10.0000002 % -> stored as 10.00 %, so it stays with the
        # Head of Operation: the threshold compares the 2-decimal percentage.
        assert r.json()["increase_pct"] == "10.00"
        assert r.json()["approver"] == "head_of_operation"
        return
    assert r.json()["approver"] == approver


async def test_contingency_release_limit_and_new_version(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    p, le, hoo, _ = await _locked(client, make_user, login, sessionmaker)
    r = await client.post(
        f"/api/projects/{p.id}/bcrs", json=_bcr("contingency_release", 31 * M), headers=le
    )
    assert r.status_code == 422 and r.json()["code"] == "CONTINGENCY_INSUFFICIENT"
    assert "Rp 30.000.000" in r.json()["message"]

    first = (
        await client.post(
            f"/api/projects/{p.id}/bcrs", json=_bcr("contingency_release", 20 * M), headers=le
        )
    ).json()
    second = (
        await client.post(
            f"/api/projects/{p.id}/bcrs", json=_bcr("contingency_release", 15 * M), headers=le
        )
    ).json()
    assert (
        await client.post(
            f"/api/workflow/requests/{first['request_id']}/approve", json={}, headers=hoo
        )
    ).status_code == 200
    # Only 10 M contingency left: the second, submitted earlier, is re-checked and refused.
    r = await client.post(
        f"/api/workflow/requests/{second['request_id']}/approve", json={}, headers=hoo
    )
    assert r.status_code == 422 and r.json()["code"] == "CONTINGENCY_INSUFFICIENT"

    v = (await client.get(f"/api/projects/{p.id}/versions", headers=le)).json()
    assert [x["version"] for x in v["versions"]] == [0, 1]
    assert v["versions"][1]["kind"] == "bcr" and first["number"] in v["versions"][1]["note"]
    # Total unchanged: contingency moved into EQUIP-OWN.
    assert v["versions"][0]["total_cost"] == v["versions"][1]["total_cost"] == "630000000"
    lines = {(x["wbs_code"], x["cost_element_code"]): x for x in v["lines"]}
    assert lines[("EXEC", "EQUIP-OWN")]["baseline"] == "500000000"
    assert lines[("EXEC", "EQUIP-OWN")]["current"] == "520000000"
    assert lines[("EXEC", "CONTINGENCY")]["current"] == "10000000"
    assert lines[("EXEC", "CONTINGENCY")]["change"] == "-20000000"
    bcrs = (await client.get(f"/api/projects/{p.id}/bcrs", headers=le)).json()
    assert {b["number"]: b["status"] for b in bcrs}[first["number"]] == "approved"


async def test_transfer_limited_by_available(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    p, le, hoo, _ = await _locked(client, make_user, login, sessionmaker)
    # 70 M of MANPOWER is pre-committed -> 30 M available to transfer.
    line = await bc.resolve(session, p.id, "EXEC", "MANPOWER")
    await bc.reserve(
        session, line, Decimal(70 * M), doc_type="purchase_requisition", doc_id="PR-1", by=None
    )
    await session.commit()
    body = _bcr("transfer", 31 * M, from_wbs_code="EXEC", from_cost_element_code="MANPOWER")
    r = await client.post(f"/api/projects/{p.id}/bcrs", json=body, headers=le)
    assert r.status_code == 422 and r.json()["code"] == "TRANSFER_EXCEEDS_AVAILABLE"
    ok = await client.post(
        f"/api/projects/{p.id}/bcrs", json={**body, "amount": str(30 * M)}, headers=le
    )
    assert ok.status_code == 201
    assert (
        await client.post(
            f"/api/workflow/requests/{ok.json()['request_id']}/approve", json={}, headers=hoo
        )
    ).status_code == 200
    async with sessionmaker() as s:
        assert (await bc.available(s, line)).available == 0
        equip = await bc.resolve(s, p.id, "EXEC", "EQUIP-OWN")
        assert (await bc.available(s, equip)).budget == Decimal(530 * M)


async def test_baseline_untouched_and_bcr_approved_hook(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p, le, _, director = await _locked(client, make_user, login, sessionmaker)
    before = (await client.get(f"/api/projects/{p.id}/baseline", headers=le)).json()
    seen: list[bcr_service.BcrRef] = []

    async def listener(_: AsyncSession, ref: bcr_service.BcrRef) -> None:
        seen.append(ref)

    monkeypatch.setattr(bcr_service, "_listeners", [listener])
    body = _bcr(
        "budget_increase", 100 * M, ref_doc_type="purchase_requisition", ref_doc_id="PR-26-007"
    )
    r = (await client.post(f"/api/projects/{p.id}/bcrs", json=body, headers=le)).json()
    assert r["approver"] == "director"
    assert (
        await client.post(
            f"/api/workflow/requests/{r['request_id']}/approve", json={}, headers=director
        )
    ).status_code == 200

    after = (await client.get(f"/api/projects/{p.id}/baseline", headers=le)).json()
    assert after == before  # v0 never changes
    d = (await client.get(f"/api/projects/{p.id}", headers=le)).json()
    assert d["total_cost"] == "730000000" and d["status"] == "locked"
    assert len(seen) == 1 and seen[0].cost_element_code == "EQUIP-OWN"
    assert (seen[0].ref_doc_type, seen[0].ref_doc_id) == ("purchase_requisition", "PR-26-007")


async def test_bcr_needs_locked_project_and_valid_target(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    draft = await _project(sessionmaker, 1_000 * M, {"EQUIP-OWN": 500 * M}, number="PRJ-26-009")
    le = await _planner(client, make_user, login, draft.id)
    r = await client.post(
        f"/api/projects/{draft.id}/bcrs", json=_bcr("budget_increase", M), headers=le
    )
    assert r.status_code == 409 and r.json()["code"] == "PROJECT_NOT_LOCKED"
    p, le2, _, _ = await _locked(client, make_user, login, sessionmaker)
    r = await client.post(
        f"/api/projects/{p.id}/bcrs",
        json=_bcr("budget_increase", M, cost_element_code="CONTINGENCY"),
        headers=le2,
    )
    assert r.status_code == 422 and r.json()["code"] == "TARGET_CONTINGENCY"
    r = await client.post(
        f"/api/projects/{p.id}/bcrs",
        json=_bcr("transfer", M, from_wbs_code="EXEC", from_cost_element_code="EQUIP-OWN"),
        headers=le2,
    )
    assert r.status_code == 422 and r.json()["code"] == "TRANSFER_SAME_LINE"
