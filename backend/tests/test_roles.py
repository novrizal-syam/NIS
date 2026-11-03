from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import Role, User, UserRole
from app.auth.roles_router import expire_temporary_roles
from app.services.audit import AuditLog

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


async def _role_id(client: AsyncClient, h: dict[str, str], code: str) -> str:
    roles: list[dict[str, str]] = (await client.get("/api/roles", headers=h)).json()
    return next(r["id"] for r in roles if r["code"] == code)


async def test_custom_role_clone_and_immediate_permission_change(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    h = await login(await make_user("admin"))
    eng_id = await _role_id(client, h, "engineer")
    res = await client.post(
        "/api/roles",
        json={"code": "site_clerk", "name": "Site Clerk", "clone_from": eng_id},
        headers=h,
    )
    assert res.status_code == 201
    role = (await client.get(f"/api/roles/{res.json()['id']}", headers=h)).json()
    engineer = (await client.get(f"/api/roles/{eng_id}", headers=h)).json()
    assert role["grants"] == engineer["grants"] and role["is_system"] is False

    async with sessionmaker() as s:
        rid = (await s.execute(select(Role.id).where(Role.code == "site_clerk"))).scalar_one()
    clerk = await make_user("site_clerk")
    ch = await login(clerk)
    assert (await client.get("/api/master/vendors", headers=ch)).status_code == 200

    # Drop master.view: the same session loses access on the next request.
    grants = [g for g in role["grants"] if g["module"] != "master"]
    assert (
        await client.put(f"/api/roles/{rid}/permissions", json={"grants": grants}, headers=h)
    ).status_code == 200
    assert (await client.get("/api/master/vendors", headers=ch)).status_code == 403

    # Custom roles can be deactivated; their holders lose those permissions.
    assert (
        await client.patch(f"/api/roles/{rid}", json={"is_active": False}, headers=h)
    ).status_code == 200
    me = (await client.get("/api/auth/me", headers=ch)).json()
    assert me["roles"] == [] and me["permissions"] == {}

    async with sessionmaker() as s:
        log = (
            await s.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "role", AuditLog.note == "Izin peran diubah"
                )
            )
        ).scalar_one()
        assert log.before == {"master.view": "all"} and log.after == {}


async def test_system_roles_rules(client: AsyncClient, make_user: MakeUser, login: Login) -> None:
    h = await login(await make_user("admin"))
    eng_id = await _role_id(client, h, "engineer")
    sa_id = await _role_id(client, h, "super_admin")
    res = await client.patch(f"/api/roles/{eng_id}", json={"is_active": False}, headers=h)
    assert res.status_code == 403 and res.json()["code"] == "SYSTEM_ROLE"
    # System role permissions are editable (but validated); Super Admin is locked.
    ok = await client.put(
        f"/api/roles/{eng_id}/permissions",
        json={
            "grants": [
                {"module": "project", "action": "view", "scope": "project"},
                {"module": "sensitive", "action": "salary", "scope": "all"},
            ]
        },
        headers=h,
    )
    assert ok.status_code == 200
    bad = await client.put(
        f"/api/roles/{eng_id}/permissions",
        json={"grants": [{"module": "nope", "action": "view", "scope": "all"}]},
        headers=h,
    )
    assert bad.status_code == 422
    locked = await client.put(f"/api/roles/{sa_id}/permissions", json={"grants": []}, headers=h)
    assert locked.json()["code"] == "ROLE_LOCKED"
    dup = await client.post("/api/roles", json={"code": "engineer", "name": "Lagi"}, headers=h)
    assert dup.status_code == 409
    assert (
        await client.post("/api/roles", json={"code": "Bad Code", "name": "x x x"}, headers=h)
    ).status_code == 422


async def test_view_as_role_is_read_only_and_audited(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    h = await login(await make_user("admin"))
    hcbp = await _role_id(client, h, "hcbp_officer")
    preview = (await client.get(f"/api/roles/{hcbp}/preview", headers=h)).json()
    assert preview["permissions"]["payroll"]["submit"] == "all"
    assert preview["sensitive"] == ["bank_account", "nik", "salary", "tax_id"]
    async with sessionmaker() as s:
        assert (await s.execute(select(AuditLog).where(AuditLog.action == "view_as"))).scalar_one()
    eng = await login(await make_user("engineer"))
    assert (await client.get(f"/api/roles/{hcbp}/preview", headers=eng)).status_code == 403


async def test_temporary_role_window_and_expiry_job(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    h = await login(await make_user("admin"))
    user = await make_user("engineer")
    uh = await login(user)
    now = datetime.now(UTC)
    future = await client.post(
        f"/api/users/{user.id}/roles/temporary",
        json={
            "role": "procurement_officer",
            "valid_from": (now + timedelta(days=1)).isoformat(),
            "valid_until": (now + timedelta(days=3)).isoformat(),
            "reason": "Pengganti cuti",
        },
        headers=h,
    )
    assert future.status_code == 201
    me = (await client.get("/api/auth/me", headers=uh)).json()
    assert [r["code"] for r in me["roles"]] == ["engineer"]  # not yet in force

    async with sessionmaker() as s:
        ur = (
            await s.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id, UserRole.valid_until.is_not(None)
                )
            )
        ).scalar_one()
        ur.valid_from = now - timedelta(hours=1)
        await s.commit()
    me = (await client.get("/api/auth/me", headers=uh)).json()
    assert {r["code"] for r in me["roles"]} == {"engineer", "procurement_officer"}
    detail = (await client.get(f"/api/users/{user.id}", headers=h)).json()
    temp = next(a for a in detail["assignments"] if a["code"] == "procurement_officer")
    assert temp["reason"] == "Pengganti cuti" and temp["valid_until"]

    # Permanent role edits keep the temporary assignment.
    await client.patch(
        f"/api/users/{user.id}", json={"roles": ["engineer", "warehouse_head"]}, headers=h
    )
    me = (await client.get("/api/auth/me", headers=uh)).json()
    assert {r["code"] for r in me["roles"]} == {"engineer", "warehouse_head", "procurement_officer"}

    async with sessionmaker() as s:
        ur = (
            await s.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id, UserRole.valid_until.is_not(None)
                )
            )
        ).scalar_one()
        ur.valid_until = now - timedelta(minutes=1)
        await s.commit()
        # Expired assignments stop counting immediately, and the job removes them.
        me = (await client.get("/api/auth/me", headers=uh)).json()
        assert "procurement_officer" not in {r["code"] for r in me["roles"]}
        assert await expire_temporary_roles(s) == 1
        await s.commit()
        assert (
            await s.execute(select(AuditLog).where(AuditLog.action == "role_expired"))
        ).scalar_one()

    bad = await client.post(
        f"/api/users/{user.id}/roles/temporary",
        json={
            "role": "cashier",
            "valid_until": (now - timedelta(days=1)).isoformat(),
            "reason": "salah tanggal",
        },
        headers=h,
    )
    assert bad.json()["code"] == "INVALID_PERIOD"
