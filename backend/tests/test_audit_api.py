from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.auth.models import User

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


async def _vendor(client: AsyncClient, h: dict[str, str]) -> dict[str, str]:
    res = await client.post(
        "/api/master/vendors",
        json={"code": "V-9", "name": "PT Uji", "category": "chemicals"},
        headers=h,
    )
    assert res.status_code == 201
    v: dict[str, str] = res.json()
    await client.patch(f"/api/master/vendors/{v['id']}", json={"status": "blacklisted"}, headers=h)
    return v


async def test_audit_screen_requires_permission_and_filters(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    po = await login(await make_user("procurement_officer"))
    v = await _vendor(client, po)
    assert (await client.get("/api/audit", headers=po)).status_code == 403

    lc = await login(await make_user("lead_controller"))  # audit view + export
    page = (await client.get("/api/audit?entity_type=vendors", headers=lc)).json()
    assert [i["action"] for i in page["items"]] == ["update", "create"]  # newest first
    upd = page["items"][0]
    assert upd["action_label"] == "Ubah" and upd["changed"] == ["status"]
    assert upd["actor_name"] == "Pengguna Uji" and upd["entity_id"] == v["id"]

    only_create = (
        await client.get("/api/audit?entity_type=vendors&action=create", headers=lc)
    ).json()
    assert only_create["total"] == 1
    facets = (await client.get("/api/audit/facets", headers=lc)).json()
    assert {"value": "vendors", "label": "vendors"} in facets["entity_types"]
    xlsx = await client.get("/api/audit/export?entity_type=vendors", headers=lc)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


async def test_history_tab_follows_record_access(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    po = await login(await make_user("procurement_officer"))
    v = await _vendor(client, po)
    eng = await login(await make_user("engineer"))  # may read master data
    hist = (await client.get(f"/api/audit/history/vendors/{v['id']}", headers=eng)).json()
    assert hist["total"] == 2
    rep = await login(await make_user("client_rep"))  # external, no master view
    assert (
        await client.get(f"/api/audit/history/vendors/{v['id']}", headers=rep)
    ).status_code == 404
    assert (await client.get("/api/audit/history/nope/1", headers=eng)).status_code == 404
