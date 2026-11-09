"""Phase 08: CAPEX - business case, RUPS step above Rp 5 M, AUC postings with budget hard stop
and change request, commissioning BAST, capitalisation creates the asset, review timing."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.capex import calc
from app.master.models import Asset
from app.project.models import Project, ProjectBudgetLine
from app.services import ledger
from app.services.numbering import today_jakarta
from app.services.storage import Storage
from tests.test_inventory import masters  # noqa: F401

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF"


def test_business_case_calculator() -> None:
    assert calc.irr([D(-1000), D(1100)]) == D("10.00")
    c = calc.CaseIn(
        amount=D(100 * M),
        day_rate=D(1 * M),
        utilisation_pct=D(50),
        opex_pct=D(10),
        life_years=5,
        rental_annual=D(150 * M),
        lease_monthly=D(4 * M),
    )
    out = calc.evaluate(c)
    assert out.revenue_annual == D(182_500_000) and out.opex_annual == D(10 * M)
    assert out.cash_flow_annual == D(172_500_000)
    assert out.payback_years == D("0.58")
    assert out.npv == round(-100 * M + sum(D(172_500_000) / D("1.12") ** t for t in range(1, 6)))
    assert out.irr is not None and abs(calc.npv(out.irr, calc.flows(c))) < 10_000  # IRR to 0,01 %
    # Renting 150 jt a year for 5 years costs more than buying and maintaining.
    assert out.best_option == "buy" and out.pv_rent > out.pv_buy
    assert 0 < out.priority_score <= 100


def _body(amount: int, **kw: Any) -> dict[str, Any]:
    return {
        "title": "Separator 3 fasa 1440 psi",
        "rjpp_ref": "RJPP 2026-2030 · Well testing",
        "asset_class": "Well testing",
        "equipment_type_code": "WT-SEP",
        "amount": str(amount),
        "funding": "equity",
        "day_rate": "25000000",
        "internal_day_rate": "12000000",
        "utilisation_pct": "55",
        "opex_pct": "6",
        "life_years": 8,
        "salvage_pct": "10",
        "rental_annual": "900000000",
        "strategic_fit": 5,
        "risk": 4,
        "tax_group": "kelompok_2",
        **kw,
    }


async def _approve(client: AsyncClient, rid: str, h: dict[str, str]) -> None:
    r = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=h)
    assert r.status_code == 200, r.text


async def test_rups_step_above_threshold(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    hoo = await login(await make_user("head_of_operation"))
    director = await login(await make_user("director"))
    rups = await login(await make_user("shareholders"))
    big = (await client.post("/api/capex", json=_body(6_000 * M), headers=hoo)).json()
    assert big["status"] == "draft" and D(big["case"]["npv"]) != 0
    sub = (await client.post(f"/api/capex/{big['id']}/submit", headers=hoo)).json()
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=rups
    )
    assert r.status_code == 403  # RUPS acts only after the Director
    await _approve(client, sub["request_id"], director)
    mid = (await client.get(f"/api/capex/{big['id']}", headers=hoo)).json()
    assert mid["status"] == "awaiting_rups" and mid["project_id"] is None
    await _approve(client, sub["request_id"], rups)
    done = (await client.get(f"/api/capex/{big['id']}", headers=hoo)).json()
    assert done["status"] == "approved" and done["budget"] == str(6_000 * M)
    assert done["budget_status"]["available"] == str(6_000 * M)
    async with sessionmaker() as s:
        project = await s.get(Project, uuid.UUID(done["project_id"]))
        assert (
            project is not None and project.project_type == "capex" and project.status == "locked"
        )
        line = (
            await s.execute(
                select(ProjectBudgetLine).where(ProjectBudgetLine.project_id == project.id)
            )
        ).scalar_one()
        assert line.cost_element_code == "CAPEX" and line.amount == 6_000 * M
    # At or below Rp 5 M the Director alone approves.
    small = (await client.post("/api/capex", json=_body(900 * M), headers=hoo)).json()
    sub = (await client.post(f"/api/capex/{small['id']}/submit", headers=hoo)).json()
    await _approve(client, sub["request_id"], director)
    assert (await client.get(f"/api/capex/{small['id']}", headers=hoo)).json()[
        "status"
    ] == "approved"


async def test_auc_postings_change_request_and_capitalisation(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    hoo = await login(await make_user("head_of_operation"))
    director = await login(await make_user("director"))
    lc = await login(await make_user("lead_controller"))
    aic = await login(await make_user("asset_inventory_coordinator"))
    p = (await client.post("/api/capex", json=_body(1_000 * M), headers=hoo)).json()
    sub = (await client.post(f"/api/capex/{p['id']}/submit", headers=hoo)).json()
    await _approve(client, sub["request_id"], director)
    url = f"/api/capex/{p['id']}"

    # Milestone 1: Dr 1520 (CAPEX project) / Cr 2110 vendor.
    r = await client.post(
        f"{url}/milestones",
        json={"amount": str(600 * M), "description": "Termin 1 fabrikasi", "vendor_code": "V-A"},
        headers=lc,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "in_execution" and out["auc"] == str(600 * M)
    async with sessionmaker() as s:
        lines = await ledger.lines_of(s, uuid.UUID(out["journal_id"]))
        got = {
            (x.account_code, x.debit, x.credit, x.project_id is not None, x.partner_code)
            for x in lines
        }
        assert got == {
            ("1520", D(600 * M), D(0), True, None),
            ("2110", D(0), D(600 * M), False, "V-A"),
        }
    # Milestone 2 would overspend: hard stop, then a change request (DOA capex).
    body = {"amount": str(500 * M), "description": "Termin 2 instalasi", "vendor_code": "V-A"}
    r = await client.post(f"{url}/milestones", json=body, headers=lc)
    assert r.status_code == 409, r.text
    ch = (
        await client.post(
            f"{url}/changes",
            json={"amount": str(200 * M), "reason": "Kenaikan harga baja dan ongkos kirim"},
            headers=hoo,
        )
    ).json()
    await _approve(client, ch["request_id"], director)
    r = await client.post(f"{url}/milestones", json=body, headers=lc)
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["budget"] == str(1_200 * M) and after["auc"] == str(1_100 * M)
    assert after["budget_status"]["available"] == str(100 * M)
    assert [c["status"] for c in after["changes"]] == ["approved"]

    # Commissioning needs the BAST in the DMS.
    r = await client.post(
        f"{url}/commission",
        json={"attachment_id": str(uuid.uuid4()), "asset_code": "AST-SEP-02"},
        headers=aic,
    )
    assert r.status_code == 422 and r.json()["code"] == "BAST_REQUIRED"
    up = await client.post(
        "/api/attachments",
        data={"entity_type": "capex", "entity_id": p["id"], "note": "BAST commissioning"},
        files={"file": ("bast.pdf", PDF, "application/pdf")},
        headers=aic,
    )
    assert up.status_code == 201, up.text
    r = await client.post(
        f"{url}/commission",
        json={"attachment_id": up.json()["id"], "asset_code": "ast-sep-02"},
        headers=aic,
    )
    assert r.status_code == 200 and r.json()["status"] == "commissioned", r.text

    # Capitalisation: Dr 1510 / Cr 1520, asset created, depreciation from next month.
    on = today_jakarta()
    r = await client.post(f"{url}/capitalise", json={"on": on.isoformat()}, headers=lc)
    assert r.status_code == 200, r.text
    cap = r.json()
    assert cap["status"] == "capitalised" and cap["asset"] == {
        "code": "AST-SEP-02",
        "cost": str(1_100 * M),
    }
    assert cap["auc"] == "0"
    async with sessionmaker() as s:
        asset = (await s.execute(select(Asset).where(Asset.code == "AST-SEP-02"))).scalar_one()
        nxt = date(on.year + (on.month == 12), on.month % 12 + 1, 1)
        assert (asset.acquisition_cost, asset.internal_day_rate, asset.useful_life_months) == (
            D(1_100 * M),
            D(12 * M),
            96,
        )
        assert asset.depreciation_start == nxt and asset.salvage_value == 110 * M
        assert asset.equipment_type_code == "WT-SEP" and asset.tax_group == "kelompok_2"
        assert await ledger.balance(s, "1510") == 1_100 * M
        assert await ledger.balance(s, "1520") == 0
        project = await s.get(Project, uuid.UUID(cap["project_id"]))
        assert project is not None and project.status == "closed"
    # Post-investment review only from 6 months after capitalisation.
    r = await client.post(
        f"{url}/reviews", json={"months": 6, "comment": "Terlalu dini untuk ditinjau."}, headers=aic
    )
    assert r.status_code == 409 and r.json()["code"] == "REVIEW_NOT_DUE"
    act = (await client.get(f"{url}/actuals/6", headers=hoo)).json()
    assert act["days_worked"] == 0 and act["case_utilisation_pct"] == "55.00"
