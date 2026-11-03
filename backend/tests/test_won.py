"""Phase 02c: Won -> contract + draft project in one transaction."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.contract import service as contracts
from app.contract.models import Contract
from app.core.errors import AppError
from app.crm.models import QuotationLine
from app.project import service as projects
from app.project.models import Project
from app.services.storage import Storage
from tests.test_quotation import _draft, _opportunity_in_quotation, prices  # noqa: F401

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


def _ql(element: str, cost: int) -> QuotationLine:
    return QuotationLine(cost_element_code=element, line_cost=Decimal(cost))


def test_budget_per_cost_element_and_contingency() -> None:
    per, contingency = projects.budget_from_lines(
        [_ql("EQUIP-OWN", 95_000_000), _ql("MANPOWER", 4_500_000), _ql("EQUIP-OWN", 1_000_001)],
        Decimal(5),
    )
    assert per == {"EQUIP-OWN": Decimal(96_000_001), "MANPOWER": Decimal(4_500_000)}
    # 5 % of 100,500,001 = 5,025,000.05 -> 5,025,000
    assert contingency == Decimal(5_025_000)
    assert contracts.rate_after_discount(Decimal(14_000_000), Decimal(10)) == Decimal(12_600_000)
    assert contracts.rate_after_discount(Decimal(3), Decimal("33.33")) == Decimal(2)
    assert contracts.consumable_rate(Decimal(1_000_000), Decimal("15")) == Decimal(1_150_000)


async def _sent(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    ae = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))
    hos = await login(await make_user("head_of_sales"))
    opp = await _opportunity_in_quotation(client, ae, director)
    q = await _draft(client, ae, opp, "10")
    rid = (await client.post(f"/api/quotations/{q['id']}/submit", headers=ae)).json()["request_id"]
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=hos)
    ).status_code == 200
    r = await client.post(f"/api/quotations/{q['id']}/send", json={}, headers=ae)
    assert r.status_code == 200, r.text
    return ae, opp, q


async def test_won_creates_contract_and_project(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    prices: None,  # noqa: F811
    storage: Storage,
) -> None:
    ae, opp, q = await _sent(client, make_user, login)
    url = f"/api/crm/opportunities/{opp['id']}"
    # The generic stage move cannot skip the contract.
    r = await client.post(f"{url}/stage", json={"to": "won"}, headers=ae)
    assert r.status_code == 409 and r.json()["code"] == "USE_WON_ACTION"

    r = await client.post(
        f"{url}/won",
        json={
            "po_number": "PO-4500012345",
            "start_date": "2027-01-05",
            "end_date": "2027-03-31",
            "payment_term_days": 45,
        },
        headers=ae,
    )
    assert r.status_code == 200, r.text
    won = r.json()
    assert won["contract_number"].startswith("CTR-") and won["project_number"].startswith("PRJ-")
    assert won["documents"] == 1

    detail = (await client.get(url, headers=ae)).json()
    assert detail["stage"] == "won" and detail["probability"] == 100
    assert detail["contract"]["number"] == won["contract_number"]
    assert detail["project"]["number"] == won["project_number"]

    # Contract: value and rate schedule after the 10 % discount.
    hos = await login(await make_user("head_of_sales"))
    c = (await client.get(f"/api/contracts/{won['contract_id']}", headers=hos)).json()
    assert c["value"] == "132750000" and c["po_number"] == "PO-4500012345"
    assert c["payment_term_days"] == 45 and c["usage_pct"] == "0.0"
    assert c["quotation_label"] == f"{q['number']} Rev.0"
    rates = {x["price_item_code"]: x for x in c["rates"]}
    assert rates["SRV-PUMP"]["kind"] == "equipment" and rates["SRV-PUMP"]["rate"] == "12600000"
    assert rates["SRV-PUMP"]["breakdown_rate"] == "0" and rates["SRV-PUMP"]["standby_rate"] is None
    assert rates["SRV-FE"]["kind"] == "personnel" and rates["SRV-FE"]["rate"] == "2700000"
    assert rates["SRV-FE"]["quoted_qty"] == "2.5"

    # Project: revenue = contract value; budget per cost element = quoted cost; contingency 5 %.
    p = (await client.get(f"/api/projects/{won['project_id']}", headers=hos)).json()
    assert p["status"] == "draft" and p["revenue"] == "132750000"
    budget = {x["cost_element_code"]: x["amount"] for x in p["budget"]}
    assert budget == {
        "CONTINGENCY": "4975000",
        "EQUIP-OWN": "95000000",
        "MANPOWER": "4500000",
    }
    assert p["budget_total"] == "104475000" and p["planned_margin"] == "28275000"
    assert p["contingency_pct"] == "5.00"

    files = (
        await client.get(
            "/api/attachments",
            params={"entity_type": "project", "entity_id": won["project_id"]},
            headers=hos,
        )
    ).json()
    assert [f["filename"] for f in files] == [f"Penawaran-{q['number']}-Rev0.pdf"]

    # Cannot win twice.
    again = await client.post(f"{url}/won", json={}, headers=ae)
    assert again.status_code == 409


async def test_won_rolls_back_on_failure(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    prices: None,  # noqa: F811
    storage: Storage,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ae, opp, _ = await _sent(client, make_user, login)
    original = projects.create_draft

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise AppError("BOOM", "Gagal membuat proyek (uji).", status_code=500)

    monkeypatch.setattr(projects, "create_draft", boom)
    r = await client.post(f"/api/crm/opportunities/{opp['id']}/won", json={}, headers=ae)
    assert r.status_code == 500 and r.json()["code"] == "BOOM"

    # Nothing was created, the opportunity is unchanged, and no number was consumed.
    assert (await session.execute(select(func.count()).select_from(Contract))).scalar_one() == 0
    assert (await session.execute(select(func.count()).select_from(Project))).scalar_one() == 0
    detail = (await client.get(f"/api/crm/opportunities/{opp['id']}", headers=ae)).json()
    assert detail["stage"] == "submitted" and detail["contract"] is None

    monkeypatch.setattr(projects, "create_draft", original)
    r = await client.post(f"/api/crm/opportunities/{opp['id']}/won", json={}, headers=ae)
    assert r.status_code == 200
    assert r.json()["contract_number"].endswith("-001")
    assert r.json()["project_number"].endswith("-001")


async def test_won_needs_sent_quotation_and_lost_keeps_winner_price(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    prices: None,  # noqa: F811
) -> None:
    ae = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))
    opp = await _opportunity_in_quotation(client, ae, director)
    await _draft(client, ae, opp, "0")
    url = f"/api/crm/opportunities/{opp['id']}"
    # Manually moved to Submitted without sending the quotation.
    await client.post(f"{url}/stage", json={"to": "submitted"}, headers=ae)
    r = await client.post(f"{url}/won", json={}, headers=ae)
    assert r.status_code == 409 and r.json()["code"] == "QUOTATION_NOT_SENT"

    r = await client.post(
        f"{url}/stage",
        json={"to": "lost", "reason": "Kalah harga", "winner_price": "120000000"},
        headers=ae,
    )
    assert r.status_code == 200
    d = (await client.get(url, headers=ae)).json()
    assert d["stage"] == "lost" and d["winner_price"] == "120000000"


async def test_contract_rates_and_access(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    prices: None,  # noqa: F811
    storage: Storage,
) -> None:
    ae, opp, _ = await _sent(client, make_user, login)
    won = (await client.post(f"/api/crm/opportunities/{opp['id']}/won", json={}, headers=ae)).json()
    cid = won["contract_id"]
    # The AE sees their own contract but cannot change it; Legal can.
    assert (await client.get(f"/api/contracts/{cid}", headers=ae)).status_code == 200
    other = await login(await make_user("account_executive"))
    assert (await client.get(f"/api/contracts/{cid}", headers=other)).status_code == 404
    rates_body = {
        "rates": [
            {
                "kind": "equipment",
                "description": "Pump unit",
                "unit": "hari",
                "rate": "12600000",
                "standby_rate": "6300000",
            },
            {
                "kind": "consumable",
                "description": "Nitrogen",
                "unit": "m3",
                "unit_cost": "1000000",
                "markup_pct": "15",
            },
            {
                "kind": "mobilisation",
                "description": "Mob/demob",
                "unit": "lot",
                "rate": "75000000",
            },
        ]
    }
    assert (
        await client.put(f"/api/contracts/{cid}/rates", json=rates_body, headers=ae)
    ).status_code == 403
    legal = await login(await make_user("legal_liaison"))
    r = await client.put(f"/api/contracts/{cid}/rates", json=rates_body, headers=legal)
    assert r.status_code == 200, r.text
    rates = r.json()["rates"]
    assert rates[0]["standby_rate"] == "6300000" and rates[0]["breakdown_rate"] == "0"
    assert rates[1]["rate"] == "1150000" and rates[1]["markup_pct"] == "15.00"
    bad = await client.put(
        f"/api/contracts/{cid}/rates",
        json={"rates": [{"kind": "consumable", "description": "N2", "unit": "m3"}]},
        headers=legal,
    )
    assert bad.status_code == 422 and bad.json()["code"] == "CONSUMABLE_COST_REQUIRED"
    r = await client.patch(
        f"/api/contracts/{cid}",
        json={"po_number": "SPK-01", "payment_term_days": 60, "start_date": "2027-01-01"},
        headers=legal,
    )
    assert r.status_code == 200 and r.json()["po_number"] == "SPK-01"

    # Projects: AE has no project permission; Head of Operation sees all.
    assert (await client.get("/api/projects", headers=ae)).status_code == 403
    hoo = await login(await make_user("head_of_operation"))
    listing = (await client.get("/api/projects", headers=hoo)).json()
    assert listing["total"] == 1 and listing["counts"]["draft"] == 1
    # Legal edits contracts but has no export right; Head of Sales exports.
    assert (await client.get("/api/contracts/export", headers=legal)).status_code == 403
    hos = await login(await make_user("head_of_sales"))
    export = await client.get("/api/contracts/export", headers=hos)
    assert export.status_code == 200 and export.content[:2] == b"PK"
