import io
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.master.specs import SPECS
from app.services.audit import AuditLog

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]

VENDOR = {"code": "V-001", "name": "PT Sumber Pompa", "category": "equipment_rental"}


async def test_vendor_crud_with_audit(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    h = await login(await make_user("procurement_officer"))
    res = await client.post("/api/master/vendors", json={**VENDOR, "rating": "4.5"}, headers=h)
    assert res.status_code == 201, res.text
    v = res.json()
    assert v["status"] == "qualified" and v["rating"] == "4.5" and v["legal_docs"] == []

    dup = await client.post("/api/master/vendors", json=VENDOR, headers=h)
    assert dup.status_code == 409 and dup.json()["code"] == "DUPLICATE_CODE"

    upd = await client.patch(
        f"/api/master/vendors/{v['id']}",
        json={
            "status": "csms_pending",
            "legal_docs": [{"name": "SIUP", "number": "123", "expiry_date": "2027-01-31"}],
        },
        headers=h,
    )
    assert upd.status_code == 200
    assert upd.json()["legal_docs"][0]["expiry_date"] == "2027-01-31"
    # Code is the natural key and cannot change.
    bad = await client.patch(f"/api/master/vendors/{v['id']}", json={"code": "X"}, headers=h)
    assert bad.status_code == 422

    listed = (await client.get("/api/master/vendors?status=csms_pending&q=pompa", headers=h)).json()
    assert listed["total"] == 1 and listed["items"][0]["code"] == "V-001"
    assert (await client.get("/api/master/vendors?status=qualified", headers=h)).json()[
        "total"
    ] == 0

    async with sessionmaker() as s:
        logs = (
            (
                await s.execute(
                    select(AuditLog).where(AuditLog.entity_type == "vendors").order_by(AuditLog.at)
                )
            )
            .scalars()
            .all()
        )
        assert [log.action for log in logs] == ["create", "update"]
        assert logs[1].before is not None and logs[1].after is not None
        assert logs[1].before["status"] == "qualified" and logs[1].after["status"] == "csms_pending"
        assert "status" in (logs[1].changed or [])


async def test_validation_messages_in_indonesian(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    h = await login(await make_user("procurement_officer"))
    res = await client.post(
        "/api/master/vendors", json={"code": "V-1", "category": "nope", "rating": 9}, headers=h
    )
    assert res.status_code == 422
    fields = {d["field"]: d["message"] for d in res.json()["details"]}
    assert fields == {
        "name": "wajib diisi",
        "category": "pilihan tidak valid",
        "rating": "nilainya terlalu besar",
    }

    res = await client.post(
        "/api/master/items",
        json={
            "code": "IT-1",
            "name": "Seal",
            "uom": "pcs",
            "category": "spare",
            "last_price": "1000.50",
        },
        headers=await login(await make_user("super_admin")),
    )
    assert res.status_code == 422
    assert "rupiah harus bilangan bulat" in res.json()["message"]


async def test_reference_must_exist(client: AsyncClient, make_user: MakeUser, login: Login) -> None:
    h = await login(await make_user("super_admin"))
    res = await client.post(
        "/api/master/price-items",
        json={
            "code": "P-1",
            "name": "Pump unit",
            "unit": "hari",
            "unit_cost": 1,
            "unit_price": 2,
            "cost_element_code": "NOPE",
        },
        headers=h,
    )
    assert res.status_code == 422 and res.json()["code"] == "REFERENCE_NOT_FOUND"


async def test_permissions_per_module(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    eng = await login(await make_user("engineer"))
    po = await login(await make_user("procurement_officer"))
    fin = await login(await make_user("finance_officer"))

    assert (await client.get("/api/master/vendors", headers=eng)).status_code == 200
    denied = await client.post("/api/master/vendors", json=VENDOR, headers=eng)
    assert denied.status_code == 403 and "Data Master" in denied.json()["message"]

    account = {"code": "9100", "name": "Uji", "account_type": "expense", "normal_balance": "debit"}
    # Chart of accounts is owned by Finance even though everyone may read it.
    assert (await client.post("/api/master/accounts", json=account, headers=po)).status_code == 403
    assert (await client.post("/api/master/accounts", json=account, headers=fin)).status_code == 201
    assert (
        len((await client.get("/api/master/accounts", headers=eng)).json()["items"]) == 25
    )  # page 1

    meta = (await client.get("/api/master/vendors/meta", headers=eng)).json()
    assert {f["name"]: f["default"] for f in meta["fields"]}["status"] == "qualified"
    assert meta["can"] == {"create": False, "edit": False, "delete": False, "export": False}


async def test_delete_in_use_is_refused(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    h = await login(await make_user("super_admin"))
    ce = (await client.get("/api/master/cost-elements?q=MANPOWER", headers=h)).json()["items"][0]
    await client.post(
        "/api/master/price-items",
        json={
            "code": "FE-01",
            "name": "Field engineer",
            "unit": "hari",
            "unit_cost": 1_500_000,
            "unit_price": 2_500_000,
            "cost_element_code": "MANPOWER",
        },
        headers=h,
    )
    res = await client.delete(f"/api/master/cost-elements/{ce['id']}", headers=h)
    assert res.status_code == 409 and res.json()["code"] == "IN_USE"
    item = (await client.get("/api/master/price-items", headers=h)).json()["items"][0]
    assert item["unit_price"] == "2500000"
    assert (
        await client.delete(f"/api/master/price-items/{item['id']}", headers=h)
    ).status_code == 204


EMPLOYEE = {
    "code": "EMP-001",
    "full_name": "Agus Operator",
    "position": "Operator",
    "is_field": True,
}


async def test_sensitive_fields_follow_pdp_permission(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    hcbp = await login(await make_user("hcbp_officer"))
    # Procurement officer may edit master data but has no sensitive-field permission.
    po = await login(await make_user("procurement_officer"))

    res = await client.post(
        "/api/master/employees",
        json={
            **EMPLOYEE,
            "basic_salary": 9_500_000,
            "nik": "3172010101900001",
            "bank_account_no": "1234567890",
        },
        headers=hcbp,
    )
    assert res.status_code == 201, res.text
    emp = res.json()
    assert emp["basic_salary"] == "9500000" and emp["nik"] == "3172010101900001"

    seen = (await client.get(f"/api/master/employees/{emp['id']}", headers=po)).json()
    for key in ("basic_salary", "nik", "npwp", "bank_account_no", "bank_name"):
        assert key not in seen
    assert seen["full_name"] == "Agus Operator"
    listed = (await client.get("/api/master/employees", headers=po)).json()["items"][0]
    assert "basic_salary" not in listed
    meta = (await client.get("/api/master/employees/meta", headers=po)).json()
    assert "basic_salary" not in {f["name"] for f in meta["fields"]}

    sneaky = await client.patch(
        f"/api/master/employees/{emp['id']}", json={"basic_salary": 1}, headers=po
    )
    assert sneaky.status_code == 403 and sneaky.json()["code"] == "SENSITIVE_FIELD_DENIED"
    ok = await client.patch(
        f"/api/master/employees/{emp['id']}", json={"position": "Senior Operator"}, headers=po
    )
    assert ok.status_code == 200

    assert (await client.get("/api/master/employees/export", headers=po)).status_code == 403
    # Admin may export master data but has no sensitive-field permission.
    admin = await login(await make_user("admin"))
    xlsx = await client.get("/api/master/employees/export", headers=admin)
    assert xlsx.status_code == 200, xlsx.text
    ws = load_workbook(io.BytesIO(xlsx.content)).active
    assert ws is not None
    headers = [c.value for c in ws[1]]
    assert "Gaji pokok" not in headers and "NIK (KTP)" not in headers
    full = load_workbook(
        io.BytesIO((await client.get("/api/master/employees/export", headers=hcbp)).content)
    ).active
    assert full is not None
    col = [c.value for c in full[1]].index("Gaji pokok") + 1
    assert full.cell(row=2, column=col).value == 9_500_000

    async with sessionmaker() as s:
        log = (
            await s.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "employees", AuditLog.action == "create"
                )
            )
        ).scalar_one()
        assert (
            log.after is not None
            and log.after["basic_salary"] == "***"
            and log.after["nik"] == "***"
        )


async def test_csv_import_all_or_nothing(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    h = await login(await make_user("super_admin"))
    template = (await client.get("/api/master/items/template", headers=h)).text
    assert template.lstrip("﻿").startswith(
        "code;name;uom;category;reorder_point;last_price;is_active"
    )

    bad = (
        b"code;name;uom;category;reorder_point;last_price\n"
        b"IT-1;Seal kit;pcs;spare;5;1.250.000\n"
        b"IT-2;;pcs;spare;x;100\n"
        b"IT-1;Duplicate;pcs;spare;1;1\n"
    )
    res = (
        await client.post("/api/master/items/import", files={"file": ("i.csv", bad)}, headers=h)
    ).json()
    assert res["ok"] is False and res["created"] == 0
    problems = {(e["row"], e["field"]) for e in res["errors"]}
    assert (3, "reorder_point") in problems and (4, None) in problems
    assert (await client.get("/api/master/items", headers=h)).json()["total"] == 0

    good = (
        b"code;name;uom;category;reorder_point;last_price\n"
        b"IT-1;Seal kit;pcs;spare;5;1.250.000\n"
        b"IT-2;Nitrogen hose;roll;hose;2,5;Rp 750.000\n"
    )
    res = (
        await client.post("/api/master/items/import", files={"file": ("i.csv", good)}, headers=h)
    ).json()
    assert res == {"ok": True, "created": 2, "updated": 0, "errors": []}
    again = b"code,name,last_price\r\nIT-1,Seal kit v2,1300000\r\n"  # comma CSV, update
    res = (
        await client.post("/api/master/items/import", files={"file": ("i.csv", again)}, headers=h)
    ).json()
    assert res["updated"] == 1
    items = {
        i["code"]: i for i in (await client.get("/api/master/items", headers=h)).json()["items"]
    }
    assert items["IT-1"]["name"] == "Seal kit v2" and items["IT-1"]["last_price"] == "1300000"
    assert items["IT-2"]["reorder_point"] == "2.5" and items["IT-2"]["last_price"] == "750000"


async def test_csv_import_refuses_sensitive_columns(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    po = await login(await make_user("procurement_officer"))
    csv_ = b"code;full_name;position;basic_salary\nEMP-9;Ani;Admin;5000000\n"
    res = (
        await client.post(
            "/api/master/employees/import", files={"file": ("e.csv", csv_)}, headers=po
        )
    ).json()
    assert res["ok"] is False and "Gaji pokok" in res["errors"][0]["message"]


async def test_entities_listing_and_unknown(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    h = await login(await make_user("engineer"))
    keys = {e["key"] for e in (await client.get("/api/master", headers=h)).json()}
    assert keys == {s.key for s in SPECS}
    assert (await client.get("/api/master/nope", headers=h)).status_code == 404


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.key)
async def test_every_entity_has_working_meta_and_list(
    client: AsyncClient, make_user: MakeUser, login: Login, spec: object
) -> None:
    h = await login(await make_user("super_admin"))
    key = spec.key  # type: ignore[attr-defined]
    assert (await client.get(f"/api/master/{key}/meta", headers=h)).status_code == 200
    assert (await client.get(f"/api/master/{key}", headers=h)).status_code == 200
    assert (await client.get(f"/api/master/{key}/export", headers=h)).status_code == 200
