"""Phase 05b: allocation gate, hour-based PM, corrective WO from DOR breakdown, PM importer,
HIRADC gate and SoD, QHSE statistics."""

import io
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.maintenance.models import Downtime, PmTask, WorkOrder
from app.master.models import Asset
from app.qhse.models import RiskAssessment
from app.services.numbering import today_jakarta
from tests.test_dor import _dor, _setup, _sync
from tests.test_inventory import _opening, masters  # noqa: F401

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000


async def _approve_dor(
    client: AsyncClient, fe: dict[str, str], sup: dict[str, str], p: Any, body: dict[str, Any]
) -> dict[str, Any]:
    dor = (await _sync(client, fe, p, body)).json()
    r = await client.post(f"/api/operations/dors/{dor['id']}/submit", headers=fe)
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/workflow/requests/{r.json()['request_id']}/approve", json={}, headers=sup
    )
    assert r.status_code == 200, r.text
    return dor


async def test_allocation_blocked_by_expired_certificate(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    fe_user = await make_user("field_engineer")
    p, _ = await _setup(sessionmaker, [fe_user])
    aic = await login(await make_user("asset_inventory_coordinator"))
    body = {"project_id": str(p.id), "start_date": today_jakarta().isoformat()}
    r = await client.post("/api/maintenance/assets/AST-OLD/allocate", json=body, headers=aic)
    assert r.status_code == 422 and r.json()["code"] == "ASSET_CERT_EXPIRED"
    assert "kedaluwarsa" in r.json()["message"]
    r = await client.post("/api/maintenance/assets/AST-PMP/allocate", json=body, headers=aic)
    assert r.status_code == 201, r.text
    assert r.json()["inspection"]["kind"] == "inspection_pre"
    r = await client.post("/api/maintenance/assets/AST-PMP/allocate", json=body, headers=aic)
    assert r.status_code == 409 and r.json()["code"] == "ASSET_ALLOCATED"
    reg = {a["code"]: a for a in (await client.get("/api/maintenance/assets", headers=aic)).json()}
    assert reg["AST-PMP"]["allocated_to"] == "PRJ-26-001" and reg["AST-OLD"]["cert_blocked"]
    r = await client.post(
        "/api/maintenance/assets/AST-PMP/release",
        json={"release_date": today_jakarta().isoformat()},
        headers=aic,
    )
    assert r.status_code == 200 and r.json()["inspection"]["kind"] == "inspection_post"


async def test_hour_pm_trigger_and_corrective_wo_from_breakdown(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    fe_user = await make_user("field_engineer")
    sup_user = await make_user("ofs_superintendent")
    p, rates = await _setup(sessionmaker, [fe_user, sup_user])
    await _opening(sessionmaker, "ITM-1", "WH-RKN", 10, 60 * M)
    async with sessionmaker() as s:
        await s.execute(
            update(Asset).where(Asset.code == "AST-PMP").values(equipment_type_code="PU-TRIPLEX")
        )
        s.add(
            PmTask(
                code="PM-TRX-30H",
                equipment_type_code="PU-TRIPLEX",
                title="Ganti oli power end",
                frequency="hours",
                interval_hours=30,
                form_code="FRM-MNT-07",
                checklist=["Kuras oli", "Ganti filter", "Isi oli baru"],
            )
        )
        await s.commit()
    fe, sup = await login(fe_user), await login(sup_user)
    aic = await login(await make_user("asset_inventory_coordinator"))
    today = today_jakarta()

    # Day 1: 18 h operating -> below 30 h, no PM yet.
    await _approve_dor(
        client, fe, sup, p, _dor(rates, report_date=(today - timedelta(days=1)).isoformat())
    )
    async with sessionmaker() as s:
        assert (await s.execute(select(WorkOrder))).scalars().all() == []

    # Day 2: 16 h operating + 6 h breakdown + 2 h rig -> meter 34 h >= 30 h: PM WO, and a
    # corrective WO + downtime for the breakdown.
    dor2 = await _approve_dor(
        client,
        fe,
        sup,
        p,
        _dor(
            rates,
            report_date=today.isoformat(),
            equipment=[
                {
                    "asset_code": "AST-PMP",
                    "rate_id": rates["pump"],
                    "operating": "16",
                    "breakdown": "6",
                    "rig": "2",
                    "remark": "Kebocoran seal plunger",
                }
            ],
        ),
    )
    async with sessionmaker() as s:
        wos = {w.kind: w for w in (await s.execute(select(WorkOrder))).scalars()}
        assert set(wos) == {"preventive", "corrective"}
        pm = wos["preventive"]
        assert pm.task_code == "PM-TRX-30H" and pm.due_hours == Decimal(30)
        assert [c["item"] for c in pm.checklist] == ["Kuras oli", "Ganti filter", "Isi oli baru"]
        cm = wos["corrective"]
        assert str(cm.dor_id) == dor2["id"] and "Kebocoran seal plunger" in cm.title
        down = (await s.execute(select(Downtime))).scalar_one()
        assert (down.hours, down.asset_code) == (Decimal(6), "AST-PMP")

    # Running the scheduler again does not duplicate the open PM.
    r = await client.post("/api/maintenance/pm-run", headers=aic)
    assert r.json()["created"] == 0

    # Complete the PM: checklist answered, part issued (Dr 5200 / Cr 1310), schedule reset.
    pm_id = str(pm.id)
    r = await client.post(f"/api/maintenance/work-orders/{pm_id}/complete", json={}, headers=aic)
    assert r.status_code == 422 and r.json()["code"] == "CHECKLIST_INCOMPLETE"
    r = await client.put(
        f"/api/maintenance/work-orders/{pm_id}",
        json={
            "checklist": [
                {"item": i, "result": "ok"} for i in ("Kuras oli", "Ganti filter", "Isi oli baru")
            ],
            "labour_hours": "3",
            "result": "Oli dan filter diganti",
        },
        headers=aic,
    )
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    r = await client.post(
        f"/api/maintenance/work-orders/{pm_id}/parts",
        json={"item_code": "ITM-1", "warehouse_code": "WH-RKN", "qty": "1"},
        headers=aic,
    )
    assert r.status_code == 200 and r.json()["parts_value"] == "6000000"
    r = await client.post(f"/api/maintenance/work-orders/{pm_id}/complete", json={}, headers=aic)
    assert r.status_code == 200 and r.json()["status"] == "done" and r.json()["signature_name"]
    detail = (await client.get("/api/maintenance/assets/AST-PMP", headers=aic)).json()
    sched = detail["schedules"][0]
    assert (sched["last_done_hours"], sched["next_due_hours"]) == ("34", "64")

    k = (await client.get("/api/maintenance/kpis", headers=aic)).json()
    row = next(x for x in k["rows"] if x["asset_code"] == "AST-PMP")
    assert row["failures"] == 1 and row["downtime_hours"] == "6"
    assert row["mttr_hours"] == "6.0" and row["mtbf_hours"] == "34.0"


async def test_hiradc_gate_sod_and_statistics(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    fe_user = await make_user("field_engineer")
    p, rates = await _setup(sessionmaker, [fe_user])
    await _opening(sessionmaker, "ITM-1", "WH-RKN", 4, 24 * M)
    async with sessionmaker() as s:  # start without an approved HIRADC
        await s.execute(RiskAssessment.__table__.delete())
        await s.commit()
    fe = await login(fe_user)
    dor = (await _sync(client, fe, p, _dor(rates))).json()
    r = await client.post(f"/api/operations/dors/{dor['id']}/submit", headers=fe)
    assert r.status_code == 422 and "HIRADC/JSA" in r.json()["message"]

    q1 = await login(await make_user("qhse_coordinator"))
    q2 = await login(await make_user("qhse_coordinator"))
    r = await client.post(
        "/api/qhse/risk-assessments",
        json={
            "project_id": str(p.id),
            "kind": "hiradc",
            "title": "HIRADC well testing RK-12",
            "hazards": [
                {"activity": "Flowing", "hazard": "Gas H2S", "likelihood": 3, "severity": 5},
            ],
        },
        headers=q1,
    )
    assert r.status_code == 422 and r.json()["code"] == "CONTROLS_REQUIRED"
    r = await client.post(
        "/api/qhse/risk-assessments",
        json={
            "project_id": str(p.id),
            "kind": "hiradc",
            "title": "HIRADC well testing RK-12",
            "hazards": [
                {
                    "activity": "Flowing",
                    "hazard": "Gas H2S",
                    "likelihood": 3,
                    "severity": 5,
                    "controls": "Detektor H2S, SCBA, briefing",
                    "residual_likelihood": 1,
                    "residual_severity": 5,
                }
            ],
        },
        headers=q1,
    )
    ra = r.json()
    assert ra["hazards"][0]["level"] == "high" and ra["hazards"][0]["residual_level"] == "low"
    r = await client.post(f"/api/qhse/risk-assessments/{ra['id']}/approve", headers=q1)
    assert r.status_code == 403 and r.json()["code"] == "SOD_SELF_APPROVAL"
    r = await client.post(f"/api/qhse/risk-assessments/{ra['id']}/approve", headers=q2)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = await client.post(f"/api/operations/dors/{dor['id']}/submit", headers=fe)
    assert r.status_code == 200, r.text

    # Statistics: a lost-time injury over 12 man-hours of approved DORs gives TRIR/LTIFR.
    r = await client.post(
        "/api/qhse/incidents",
        json={
            "project_id": str(p.id),
            "occurred_on": today_jakarta().isoformat(),
            "category": "lost_time",
            "description": "Jari terjepit saat rig-up",
            "lost_days": 2,
        },
        headers=q1,
    )
    inc = r.json()
    r = await client.post(
        f"/api/qhse/incidents/{inc['id']}/investigation", json={"close": True}, headers=q1
    )
    assert r.status_code == 422 and r.json()["code"] == "ROOT_CAUSE_REQUIRED"
    st = (await client.get("/api/qhse/statistics", headers=q1)).json()
    assert (st["lti"], st["recordable"], st["manhours"]) == (1, 1, "0")
    assert st["trir"] is None  # no approved man-hours yet
    csv = await client.get("/api/qhse/csms-export", headers=q1)
    assert csv.status_code == 200 and csv.content[:2] == b"PK"


def _workbook(rows_task: list[list[Any]], rows_asset: list[list[Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Task Library"
    ws.append(["Kode Tugas", "Jenis Peralatan", "Tugas", "Frekuensi", "Formulir", "Checklist"])
    for r in rows_task:
        ws.append(r)
    ws2 = wb.create_sheet("Equipment Register")
    ws2.append(
        ["Kode Aset", "Nama", "Jenis Peralatan", "Kritikalitas", "Sertifikat", "Berlaku s.d."]
    )
    for r in rows_asset:
        ws2.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_pm_plan_import(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    aic = await login(await make_user("asset_inventory_coordinator"))
    bad = _workbook([["T-1", "Pompa ajaib", "Cek", "Kadang-kadang", None, None]], [])
    r = await client.post(
        "/api/maintenance/pm-import",
        files={"file": ("pm.xlsx", bad, "application/octet-stream")},
        headers=aic,
    )
    assert r.status_code == 422
    assert any("tidak dikenal" in e for e in r.json()["details"]["errors"])
    good = _workbook(
        [
            [
                "PM-SEP-M",
                "WT-SEP",
                "Inspeksi bulanan separator",
                "Bulanan",
                "FRM-MNT-01",
                "Cek PSV; Cek gauge",
            ],
            ["PM-TRX-250", "Pump unit triplex", "Servis 250 jam", "250 jam", "FRM-MNT-07", None],
        ],
        [["AST-SEP-09", "Separator 12K", "WT-SEP", "A", "Sertifikat MIGAS", "2027-06-30"]],
    )
    r = await client.post(
        "/api/maintenance/pm-import",
        files={"file": ("pm.xlsx", good, "application/octet-stream")},
        headers=aic,
    )
    assert r.status_code == 200, r.text
    assert r.json() | {"errors": []} == {
        "tasks_created": 2,
        "tasks_updated": 0,
        "assets_created": 1,
        "assets_updated": 0,
        "errors": [],
    }
    tasks = {
        t["code"]: t for t in (await client.get("/api/maintenance/pm-tasks", headers=aic)).json()
    }
    assert (
        tasks["PM-TRX-250"]["frequency"] == "hours" and tasks["PM-TRX-250"]["interval_hours"] == 250
    )
    assert tasks["PM-SEP-M"]["checklist"] == ["Cek PSV", "Cek gauge"]
    assert tasks["PM-TRX-250"]["equipment_type_code"] == "PU-TRIPLEX"
    async with sessionmaker() as s:
        a = (await s.execute(select(Asset).where(Asset.code == "AST-SEP-09"))).scalar_one()
        assert a.equipment_type_code == "WT-SEP"
        assert a.certificates[0]["expiry_date"] == "2027-06-30"
