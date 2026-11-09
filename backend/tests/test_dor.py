"""Phase 05a: DOR validations, pricing, offline sync, approval effects and SoD."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.contract.models import Contract, ContractRate
from app.crm.models import Opportunity
from app.finance.models import JournalEntry, JournalLine
from app.inventory import stock_service as stock
from app.master.models import Asset, Client, Employee, PriceItem
from app.notifications.models import Notification
from app.operations.models import AssetUsage, HseDaily, PayrollDay
from app.project.models import Project, ProjectBudgetLine, ProjectMember, ProjectWbs
from app.qhse.models import RiskAssessment
from app.services import budget_control as bc
from app.services.numbering import today_jakarta
from tests.test_inventory import _opening, masters  # noqa: F401

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal


def _cert(name: str, days: int, mandatory: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "number": "X-1",
        "expiry_date": (today_jakarta() + timedelta(days=days)).isoformat(),
        "mandatory": mandatory,
    }


async def _setup(
    sm: async_sessionmaker[AsyncSession], members: list[User], contract_value: int = 100 * M
) -> tuple[Project, dict[str, str]]:
    """Locked OFS project with a contract rate schedule, budget, crew, assets, site stock."""
    async with sm() as s:
        s.add(Client(code="C-1", name="PT KKKS"))
        s.add(
            PriceItem(
                code="SRV-FE",
                name="Field engineer",
                unit="hari",
                unit_cost=D(1_800_000),
                unit_price=D(3 * M),
                cost_element_code="MANPOWER",
            )
        )
        opp = Opportunity(
            number="OPP-26-001", company_name="PT KKKS", title="Well test", owner_id=members[0].id
        )
        s.add(opp)
        await s.flush()
        owner = members[0]
        c = Contract(
            number="CTR-26-001",
            opportunity_id=opp.id,
            client_code="C-1",
            company_name="PT KKKS",
            title="Well test",
            owner_id=owner.id,
            value=D(contract_value),
        )
        s.add(c)
        await s.flush()
        rates = {
            "pump": ContractRate(
                contract_id=c.id,
                seq=1,
                kind="equipment",
                description="Pump unit",
                unit="hari",
                rate=D(14 * M),
                standby_rate=D(7 * M),
                breakdown_rate=D(0),
            ),
            "fe": ContractRate(
                contract_id=c.id,
                seq=2,
                kind="personnel",
                price_item_code="SRV-FE",
                description="Field engineer",
                unit="hari",
                rate=D(3 * M),
            ),
            "chem": ContractRate(
                contract_id=c.id,
                seq=3,
                kind="consumable",
                description="Demulsifier",
                unit="drum",
                rate=D(6_600_000),
                unit_cost=D(6 * M),
                markup_pct=D(10),
            ),
        }
        s.add_all(rates.values())
        p = Project(
            number="PRJ-26-001",
            name="Well testing RK-12",
            company_name="PT KKKS",
            contract_id=c.id,
            client_code="C-1",
            status="locked",
            revenue=D(contract_value),
            contingency_pct=D(5),
            service_line="ofs",
            service_type="well_test",
        )
        s.add(p)
        await s.flush()
        w = ProjectWbs(project_id=p.id, code="EXEC", name="Execution", seq=1)
        s.add(w)
        await s.flush()
        for code in ("EQUIP-OWN", "MANPOWER", "CONSUMABLE"):
            s.add(
                ProjectBudgetLine(
                    project_id=p.id,
                    version=0,
                    wbs_id=w.id,
                    cost_element_code=code,
                    amount=D(100 * M),
                    source="quotation",
                )
            )
        for u in members:
            s.add(ProjectMember(project_id=p.id, user_id=u.id))
        # 05b: an approved HIRADC is required before the first DOR.
        s.add(
            RiskAssessment(
                number="HRA-T-001",
                project_id=p.id,
                kind="hiradc",
                title="HIRADC well testing",
                status="approved",
                hazards=[],
            )
        )
        s.add_all(
            [
                Asset(
                    code="AST-PMP",
                    name="Pump unit 600 HP",
                    asset_class="Pumping unit",
                    criticality="A",
                    internal_day_rate=D(9_500_000),
                    certificates=[_cert("Sertifikat MIGAS", 300)],
                ),
                Asset(
                    code="AST-OLD",
                    name="Pump lama",
                    asset_class="Pumping unit",
                    criticality="B",
                    certificates=[_cert("Sertifikat MIGAS", -3)],
                ),
                Asset(
                    code="AST-WARN",
                    name="Booster",
                    asset_class="Pumping unit",
                    criticality="B",
                    certificates=[_cert("Kalibrasi", 30), _cert("Opsional", -10, mandatory=False)],
                ),
                Employee(
                    code="E-1",
                    full_name="Andi Operator",
                    position="FE",
                    is_field=True,
                    certificates=[_cert("H2S", 200)],
                ),
                Employee(
                    code="E-2",
                    full_name="Budi Kadaluarsa",
                    position="FE",
                    is_field=True,
                    certificates=[_cert("H2S", -1)],
                ),
            ]
        )
        await s.commit()
        return p, {k: str(r.id) for k, r in rates.items()}


def _dor(rates: dict[str, str], **kw: Any) -> dict[str, Any]:
    return {
        "report_date": kw.pop("report_date", today_jakarta().isoformat()),
        "site_warehouse": "WH-RKN",
        "activities": "Flowing well RK-12 melalui separator, sampling tiap 2 jam.",
        "technical": {"oil_rate": 850, "choke": 32},
        "hse": {"incidents": 0, "toolbox_talks": 1},
        "equipment": kw.pop(
            "equipment",
            [
                {
                    "asset_code": "AST-PMP",
                    "rate_id": rates["pump"],
                    "operating": "18",
                    "standby": "4",
                    "breakdown": "0",
                    "rig": "2",
                }
            ],
        ),
        "crew": kw.pop("crew", [{"employee_code": "E-1", "rate_id": rates["fe"], "hours": "12"}]),
        "consumables": kw.pop(
            "consumables", [{"item_code": "ITM-1", "rate_id": rates["chem"], "qty": "2"}]
        ),
        **kw,
    }


async def _sync(
    client: AsyncClient,
    h: dict[str, str],
    p: Project,
    body: dict[str, Any],
    client_id: str | None = None,
    base_version: int | None = None,
) -> Any:
    return await client.post(
        "/api/operations/dors/sync",
        json={
            "project_id": str(p.id),
            "client_id": client_id or str(uuid.uuid4()),
            "base_version": base_version,
            "dor": body,
        },
        headers=h,
    )


async def test_validations_and_pricing(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    fe_user = await make_user("field_engineer")
    p, rates = await _setup(sessionmaker, [fe_user])
    await _opening(sessionmaker, "ITM-1", "WH-RKN", 4, 24 * M)  # 6 jt / drum at the site
    fe = await login(fe_user)

    opts = (
        await client.get(
            "/api/operations/dors/form-options", params={"project_id": str(p.id)}, headers=fe
        )
    ).json()
    assets = {a["code"]: a for a in opts["assets"]}
    assert "kedaluwarsa" in assets["AST-OLD"]["blocked"] and assets["AST-PMP"]["blocked"] is None
    assert assets["AST-WARN"]["blocked"] is None and "Kalibrasi" in assets["AST-WARN"]["warning"]
    assert {c["code"]: c["blocked"] is not None for c in opts["crew"]} == {
        "E-1": False,
        "E-2": True,
    }
    assert opts["default_site"] == "WH-RKN" and opts["template"]["label"] == "Well testing"

    async def preview(body: dict[str, Any]) -> dict[str, Any]:
        r = await client.post(
            "/api/operations/dors/preview", json={"project_id": str(p.id), "dor": body}, headers=fe
        )
        assert r.status_code == 200, r.text
        return r.json()

    ok = await preview(_dor(rates))
    # Pump: (18 x 14 jt + 4 x 7 jt + 2 x 14 jt) / 24 = 12.833.333; FE 3 jt; chem 2 x 6 jt x 1,1.
    assert ok["equipment"] == [["12833333", "9500000"]]
    assert ok["crew"] == [["3000000", "1800000"]]
    assert ok["consumables"] == [["13200000", "12000000"]]
    assert (ok["revenue"], ok["internal_cost"]) == ("29033333", "23300000")
    assert ok["errors"] == []

    bad = await preview(
        _dor(
            rates,
            equipment=[
                {"asset_code": "AST-PMP", "operating": "18", "standby": "3", "rig": "2"},
                {"asset_code": "AST-WARN", "operating": "24"},
            ],
            consumables=[{"item_code": "ITM-1", "qty": "5"}],
        )
    )
    assert any("AST-PMP" in e and "harus 24" in e for e in bad["errors"])
    assert any("melebihi stok site" in e for e in bad["errors"])
    assert any("AST-WARN" in w for w in bad["warnings"])
    # Breakdown is billed at 0 (no agreed breakdown rate).
    br = await preview(
        _dor(
            rates,
            equipment=[{"asset_code": "AST-PMP", "rate_id": rates["pump"], "breakdown": "24"}],
        )
    )
    assert br["equipment"] == [["0", "9500000"]]

    # Expired mandatory certificates cannot be selected at all.
    r = await _sync(
        client, fe, p, _dor(rates, equipment=[{"asset_code": "AST-OLD", "operating": "24"}])
    )
    assert r.status_code == 422 and r.json()["code"] == "SELECTION_BLOCKED"
    r = await _sync(client, fe, p, _dor(rates, crew=[{"employee_code": "E-2"}]))
    assert r.status_code == 422 and "Budi Kadaluarsa" in r.json()["message"]


async def test_offline_sync_idempotent_and_conflict(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    fe_user = await make_user("field_engineer")
    p, rates = await _setup(sessionmaker, [fe_user])
    await _opening(sessionmaker, "ITM-1", "WH-RKN", 4, 24 * M)
    fe = await login(fe_user)
    cid = str(uuid.uuid4())
    r = await _sync(client, fe, p, _dor(rates), client_id=cid)
    assert r.status_code == 201 and r.json()["version"] == 1
    first = r.json()
    # Same device saves again on top of version 1 (e.g. a queued retry): updated, version 2.
    r = await _sync(
        client, fe, p, _dor(rates, activities="Revisi aktivitas"), client_id=cid, base_version=1
    )
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["id"] == first["id"]
    # Another device still holding version 1 is told to reload.
    r = await _sync(client, fe, p, _dor(rates), client_id=cid, base_version=1)
    assert r.status_code == 409 and r.json()["code"] == "VERSION_CONFLICT"
    # A second DOR for the same project and day is refused.
    r = await _sync(client, fe, p, _dor(rates))
    assert r.status_code == 409 and r.json()["code"] == "DOR_EXISTS"
    got = (await client.get(f"/api/operations/dors/by-client/{cid}", headers=fe)).json()
    assert got["activities"] == "Revisi aktivitas"


async def test_approval_effects_in_one_transaction(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    fe_user = await make_user("field_engineer")
    sup_user = await make_user("ofs_superintendent")
    hos_user = await make_user("head_of_sales")
    # Contract 36 jt: this DOR (29.033.333) takes usage past 80 %.
    p, rates = await _setup(sessionmaker, [fe_user, sup_user], contract_value=36 * M)
    await _opening(sessionmaker, "ITM-1", "WH-RKN", 4, 24 * M)
    fe = await login(fe_user)
    sup = await login(sup_user)
    day = today_jakarta() - timedelta(days=2)
    r = await _sync(client, fe, p, _dor(rates, report_date=day.isoformat()))
    dor = r.json()
    r = await client.post(f"/api/operations/dors/{dor['id']}/submit", headers=fe)
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub["status"] == "submitted" and sub["late"]  # after 08:00 the next day

    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=sup
    )
    assert r.status_code == 200, r.text
    done = (await client.get(f"/api/operations/dors/{dor['id']}", headers=sup)).json()
    assert done["status"] == "approved" and done["internal_cost"] == "23300000"

    async with sessionmaker() as s:
        assert await stock.on_hand(s, "ITM-1", "WH-RKN") == D(2)
        rows = (
            (
                await s.execute(
                    select(JournalLine.account_code, JournalLine.debit, JournalLine.credit)
                    .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                    .where(JournalEntry.source_id == dor["id"])
                    .order_by(JournalEntry.number, JournalLine.seq)
                )
            )
            .tuples()
            .all()
        )
        assert [(a, int(d), int(c)) for a, d, c in rows] == [
            ("1220", 29_033_333, 0),
            ("4100", 0, 29_033_333),
            ("5300", 12 * M, 0),
            ("1310", 0, 12 * M),
        ]
        for ce, amount in (
            ("EQUIP-OWN", 9_500_000),
            ("MANPOWER", 1_800_000),
            ("CONSUMABLE", 12 * M),
        ):
            bal = await bc.available(s, await bc.resolve(s, p.id, "EXEC", ce))
            assert bal.actual == D(amount), ce
        usage = (await s.execute(select(AssetUsage))).scalar_one()
        assert (usage.asset_code, usage.operating, usage.rig) == ("AST-PMP", D(18), D(2))
        hse = (await s.execute(select(HseDaily))).scalar_one()
        assert (hse.manhours, hse.toolbox_talks) == (D(12), 1)
        pay = (await s.execute(select(PayrollDay))).scalar_one()
        assert (pay.employee_code, pay.work_date) == ("E-1", day)
        contract = (await s.execute(select(Contract))).scalar_one()
        assert contract.used_value == D(29_033_333)
        alerts = (
            await s.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == hos_user.id, Notification.kind == "contract_usage")
            )
        ).scalar_one()
        assert alerts == 1


async def test_submitter_cannot_approve_and_return_reopens(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    both = await make_user("field_engineer", "ofs_superintendent")
    sup_user = await make_user("ofs_superintendent")
    p, rates = await _setup(sessionmaker, [both, sup_user])
    await _opening(sessionmaker, "ITM-1", "WH-RKN", 4, 24 * M)
    h = await login(both)
    dor = (await _sync(client, h, p, _dor(rates))).json()
    sub = (await client.post(f"/api/operations/dors/{dor['id']}/submit", headers=h)).json()
    r = await client.post(f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=h)
    assert r.status_code == 403 and r.json()["code"] == "SOD_SELF_APPROVAL"
    sup = await login(sup_user)
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/reject",
        json={"comment": "Jam standby tidak sesuai log"},
        headers=sup,
    )
    assert r.status_code == 200, r.text
    back = (await client.get(f"/api/operations/dors/{dor['id']}", headers=h)).json()
    assert back["status"] == "returned" and back["can_edit"]
    assert back["return_reason"] == "Jam standby tidak sesuai log"
    async with sessionmaker() as s:
        assert await stock.on_hand(s, "ITM-1", "WH-RKN") == D(4)  # nothing posted
