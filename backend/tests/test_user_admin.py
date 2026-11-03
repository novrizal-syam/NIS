import io
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User, UserInvite
from app.master.models import Employee

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


def _token(link: str | None) -> str:
    # Email is not configured in tests, so the API hands the activation link to the admin.
    assert link and "/activate?token=" in link
    return link.split("token=", 1)[1]


async def test_invite_flow(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    h = await login(await make_user("admin"))
    res = await client.post(
        "/api/users",
        json={"email": "baru@gek.co.id", "full_name": "Pegawai Baru", "roles": ["engineer"]},
        headers=h,
    )
    assert res.status_code == 201 and res.json()["temporary_password"] is None
    token = _token(res.json()["activation_link"])
    listed = (await client.get("/api/users?status=invited", headers=h)).json()
    assert [u["email"] for u in listed["items"]] == ["baru@gek.co.id"]

    weak = await client.post("/api/auth/invite/accept", json={"token": token, "password": "pendek"})
    assert weak.status_code == 422
    ok = await client.post(
        "/api/auth/invite/accept", json={"token": token, "password": "GunungSalak-2026"}
    )
    assert ok.status_code == 200
    again = await client.post(
        "/api/auth/invite/accept", json={"token": token, "password": "GunungSalak-2026"}
    )
    assert again.status_code == 410 and again.json()["code"] == "INVITE_INVALID"
    assert (await client.get("/api/users?status=active", headers=h)).json()["counts"][
        "invited"
    ] == 0


async def test_invite_expires_and_resend_revokes_old(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    h = await login(await make_user("admin"))
    created = await client.post(
        "/api/users",
        json={"email": "x@gek.co.id", "full_name": "Uji Undangan", "roles": ["engineer"]},
        headers=h,
    )
    uid, first = created.json()["id"], _token(created.json()["activation_link"])
    resend = await client.post(f"/api/users/{uid}/invite", headers=h)
    assert resend.status_code == 200
    second = _token(resend.json()["activation_link"])
    assert first != second
    old = await client.post(
        "/api/auth/invite/accept", json={"token": first, "password": "GunungSalak-2026"}
    )
    assert old.json()["code"] == "INVITE_INVALID"
    async with sessionmaker() as s:
        for inv in (await s.execute(select(UserInvite))).scalars():
            inv.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await s.commit()
    expired = await client.post(
        "/api/auth/invite/accept", json={"token": second, "password": "GunungSalak-2026"}
    )
    assert expired.json()["code"] == "INVITE_EXPIRED"


async def test_temporary_password_shown_once_and_must_change(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    h = await login(await make_user("admin"))
    res = await client.post(
        "/api/users",
        json={
            "email": "tmp@gek.co.id",
            "full_name": "Sandi Sementara",
            "roles": ["engineer"],
            "mode": "password",
        },
        headers=h,
    )
    temp = res.json()["temporary_password"]
    assert temp and len(temp) >= 10
    signed = await client.post("/api/auth/login", json={"email": "tmp@gek.co.id", "password": temp})
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {signed.json()['access_token']}"}
    )
    assert me.json()["pending"] == ["change_password", "accept_privacy", "complete_profile"]
    detail = (await client.get(f"/api/users/{res.json()['id']}", headers=h)).json()
    assert "temporary_password" not in detail and detail["status"] == "active"


async def test_account_actions(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    h = await login(await make_user("admin"))
    target = await make_user("engineer")
    th = await login(target)
    detail = (await client.get(f"/api/users/{target.id}", headers=h)).json()
    assert len(detail["sessions"]) == 1

    assert (await client.post(f"/api/users/{target.id}/force-logout", headers=h)).status_code == 204
    assert (
        await client.post("/api/auth/refresh")
    ).status_code == 401  # client cookie belongs to target? (latest login)
    assert (await client.get(f"/api/users/{target.id}", headers=h)).json()["sessions"] == []

    async with sessionmaker() as s:
        u = await s.get(User, target.id)
        assert u is not None
        u.locked_until = datetime.now(UTC) + timedelta(minutes=10)
        await s.commit()
    assert (await client.get(f"/api/users/{target.id}", headers=h)).json()["status"] == "locked"
    assert (await client.post(f"/api/users/{target.id}/unlock", headers=h)).status_code == 204
    assert (await client.get(f"/api/users/{target.id}", headers=h)).json()["status"] == "active"

    assert (await client.post(f"/api/users/{target.id}/deactivate", headers=h)).status_code == 204
    assert (
        await client.get("/api/auth/ping", headers=th)
    ).status_code == 401  # token stops working
    assert (await client.get(f"/api/users/{target.id}", headers=h)).json()["status"] == "inactive"
    assert (await client.post(f"/api/users/{target.id}/activate", headers=h)).status_code == 204

    temp = (await client.post(f"/api/users/{target.id}/reset-password", headers=h)).json()[
        "temporary_password"
    ]
    assert (
        await client.post("/api/auth/login", json={"email": target.email, "password": temp})
    ).status_code == 200


async def test_last_super_admin_cannot_be_deactivated_or_demoted(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    sa = await make_user("super_admin")
    h = await login(sa)
    other = await make_user("engineer")
    listed = (await client.get("/api/users", headers=h)).json()
    assert listed["active_super_admins"] == 1  # UI warns
    # Own account cannot be deactivated; demotion of the last Super Admin is refused.
    assert (await client.post(f"/api/users/{sa.id}/deactivate", headers=h)).json()[
        "code"
    ] == "SELF_DEACTIVATE"
    demote = await client.patch(f"/api/users/{sa.id}", json={"roles": ["admin"]}, headers=h)
    assert demote.status_code == 409 and demote.json()["code"] == "LAST_SUPER_ADMIN"
    # With a second Super Admin it is allowed.
    assert (
        await client.patch(f"/api/users/{other.id}", json={"roles": ["super_admin"]}, headers=h)
    ).status_code == 200
    assert (
        await client.patch(f"/api/users/{sa.id}", json={"roles": ["admin"]}, headers=h)
    ).status_code == 200


async def test_admin_cannot_touch_super_admins(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    sa = await make_user("super_admin")
    eng = await make_user("engineer")
    h = await login(await make_user("admin"))
    grant = await client.patch(f"/api/users/{eng.id}", json={"roles": ["super_admin"]}, headers=h)
    assert grant.json()["code"] == "SUPER_ADMIN_ONLY"
    for path in ("deactivate", "reset-password", "reset-2fa"):
        res = await client.post(f"/api/users/{sa.id}/{path}", headers=h)
        assert res.status_code == 403, path


async def test_super_admin_2fa_reset_is_break_glass_only(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    sa1, sa2 = await make_user("super_admin"), await make_user("super_admin")
    res = await client.post(f"/api/users/{sa2.id}/reset-2fa", headers=await login(sa1))
    assert res.status_code == 403 and res.json()["code"] == "SUPER_ADMIN_2FA"
    eng = await make_user("engineer")
    assert (
        await client.post(f"/api/users/{eng.id}/reset-2fa", headers=await login(sa1))
    ).status_code == 204


async def test_link_employee(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as s:
        s.add(Employee(code="EMP-001", full_name="Agus", position="Operator"))
        await s.commit()
    h = await login(await make_user("admin"))
    a, b = await make_user("engineer"), await make_user("engineer")
    assert (
        await client.patch(f"/api/users/{a.id}", json={"employee_code": "EMP-001"}, headers=h)
    ).json()["employee_code"] == "EMP-001"
    dup = await client.patch(f"/api/users/{b.id}", json={"employee_code": "EMP-001"}, headers=h)
    assert dup.json()["code"] == "EMPLOYEE_LINKED"
    assert (
        await client.patch(f"/api/users/{a.id}", json={"employee_code": "NOPE"}, headers=h)
    ).status_code == 422


async def test_import_csv_and_excel(client: AsyncClient, make_user: MakeUser, login: Login) -> None:
    h = await login(await make_user("admin"))
    bad = (
        b"email;full_name;roles\nok@gek.co.id;Oke;engineer\n"
        b"bukan-email;X;engineer\nz@gek.co.id;Z;ghost\n"
    )
    res = (await client.post("/api/users/import", files={"file": ("u.csv", bad)}, headers=h)).json()
    assert res["ok"] is False and {e["row"] for e in res["errors"]} == {3, 4}
    assert (await client.get("/api/users?q=ok@gek", headers=h)).json()[
        "total"
    ] == 0  # nothing saved

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["email", "full_name", "roles"])
    ws.append(["a@gek.co.id", "Ani", "engineer|procurement_officer"])
    ws.append(["b@gek.co.id", "Budi", "cashier"])
    buf = io.BytesIO()
    wb.save(buf)
    res = (
        await client.post(
            "/api/users/import", files={"file": ("u.xlsx", buf.getvalue())}, headers=h
        )
    ).json()
    assert res["ok"] is True and res["created"] == 2 and res["errors"] == []
    assert [x["email"] for x in res["activation_links"]] == ["a@gek.co.id", "b@gek.co.id"]
    ani = (await client.get("/api/users?q=ani", headers=h)).json()["items"][0]
    assert ani["roles"] == ["engineer", "procurement_officer"] and ani["status"] == "invited"


async def test_user_admin_permissions(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    eng = await login(await make_user("engineer"))
    assert (await client.get("/api/users", headers=eng)).status_code == 403
    xlsx = await client.get("/api/users/export", headers=await login(await make_user("admin")))
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
