from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import Role, User, UserRole

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


async def _codes(client: AsyncClient, h: dict[str, str], uid: object) -> list[str]:
    return sorted((await client.get(f"/api/users/{uid}", headers=h)).json()["roles"])


async def test_conflict_needs_reason_and_director_approval(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    admin = await login(await make_user("admin"))
    director = await login(await make_user("director"))
    target = await make_user("ap_accountant")

    refused = await client.patch(
        f"/api/users/{target.id}", json={"roles": ["ap_accountant", "cashier"]}, headers=admin
    )
    assert refused.status_code == 409 and refused.json()["code"] == "SOD_CONFLICT"
    assert "AP Accountant + Cashier" in refused.json()["message"]
    assert refused.json()["details"]["pairs"] == [["ap_accountant", "cashier"]]

    short = await client.patch(
        f"/api/users/{target.id}",
        json={"roles": ["ap_accountant", "cashier"], "sod_reason": "cuti"},
        headers=admin,
    )
    assert short.status_code == 409

    pending = await client.patch(
        f"/api/users/{target.id}",
        json={
            "roles": ["ap_accountant", "cashier"],
            "sod_reason": "Kasir cuti melahirkan 3 bulan, tidak ada pengganti",
        },
        headers=admin,
    )
    assert pending.status_code == 202 and pending.json()["pending_approval"].startswith("SOD-")
    assert await _codes(client, admin, target.id) == ["ap_accountant"]  # not applied yet

    # The admin who asked cannot approve it; the Director can.
    rid = pending.json()["request_id"]
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=admin)
    ).status_code == 403
    ok = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=director)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert await _codes(client, admin, target.id) == ["ap_accountant", "cashier"]

    register = (await client.get("/api/sod/register", headers=admin)).json()
    exc = register["exceptions"][0]
    assert exc["status"] == "approved" and exc["pairs"] == [["ap_accountant", "cashier"]]
    assert register["violations"] == []  # covered by the approved exception

    # Already-approved pair: later edits keep it without asking again.
    again = await client.patch(
        f"/api/users/{target.id}",
        json={"roles": ["ap_accountant", "cashier", "engineer"]},
        headers=admin,
    )
    assert again.status_code == 200


async def test_rejected_exception_changes_nothing(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    admin = await login(await make_user("admin"))
    director = await login(await make_user("director"))
    target = await make_user("finance_officer")
    res = await client.patch(
        f"/api/users/{target.id}",
        json={
            "roles": ["finance_officer", "lead_controller"],
            "sod_reason": "Tim keuangan hanya dua orang saat ini",
        },
        headers=admin,
    )
    rid = res.json()["request_id"]
    await client.post(
        f"/api/workflow/requests/{rid}/reject",
        json={"comment": "Rekrut pengganti dulu"},
        headers=director,
    )
    assert await _codes(client, admin, target.id) == ["finance_officer"]
    assert (await client.get("/api/sod/register", headers=admin)).json()["exceptions"][0][
        "status"
    ] == "rejected"


async def test_temporary_conflicting_role(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    admin = await login(await make_user("admin"))
    director = await login(await make_user("director"))
    target = await make_user("field_engineer")
    until = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    body = {
        "role": "ofs_superintendent",
        "valid_until": until,
        "reason": "Pengganti superintendent cuti",
    }
    assert (
        await client.post(f"/api/users/{target.id}/roles/temporary", json=body, headers=admin)
    ).status_code == 409
    res = await client.post(
        f"/api/users/{target.id}/roles/temporary",
        json={**body, "sod_reason": "Tidak ada superintendent lain di site Rokan"},
        headers=admin,
    )
    assert res.status_code == 202
    await client.post(
        f"/api/workflow/requests/{res.json()['request_id']}/approve", json={}, headers=director
    )
    detail = (await client.get(f"/api/users/{target.id}", headers=admin)).json()
    temp = next(a for a in detail["assignments"] if a["code"] == "ofs_superintendent")
    assert temp["valid_until"] is not None


async def test_register_review_revoke_and_violations(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    admin = await login(await make_user("admin"))
    director = await login(await make_user("director"))
    controller = await login(await make_user("lead_controller"))
    target = await make_user("hcbp_officer")
    res = await client.patch(
        f"/api/users/{target.id}",
        json={
            "roles": ["hcbp_officer", "head_of_finance"],
            "sod_reason": "Struktur organisasi sementara Q4",
        },
        headers=admin,
    )
    await client.post(
        f"/api/workflow/requests/{res.json()['request_id']}/approve", json={}, headers=director
    )
    exc_id = (await client.get("/api/sod/register", headers=controller)).json()["exceptions"][0][
        "id"
    ]

    assert (
        await client.post(f"/api/sod/exceptions/{exc_id}/review", json={"note": "x"}, headers=admin)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/sod/exceptions/{exc_id}/review",
            json={"note": "Masih diperlukan"},
            headers=controller,
        )
    ).status_code == 204
    reviewed = (await client.get("/api/sod/register", headers=controller)).json()["exceptions"][0]
    assert reviewed["last_reviewed_at"] and reviewed["review_note"] == "Masih diperlukan"

    assert (
        await client.post(f"/api/sod/exceptions/{exc_id}/revoke", headers=admin)
    ).status_code == 204
    violations = (await client.get("/api/sod/register", headers=admin)).json()["violations"]
    assert [(v["email"], v["pair"]) for v in violations] == [
        (target.email, ["hcbp_officer", "head_of_finance"])
    ]

    # A conflict created outside the screen (e.g. imported) also shows up.
    other = await make_user("cashier")
    async with sessionmaker() as s:
        from sqlalchemy import select

        rid = (
            await s.execute(select(Role.id).where(Role.code == "procurement_officer"))
        ).scalar_one()
        s.add(UserRole(user_id=other.id, role_id=rid))
        await s.commit()
    pairs = {
        tuple(v["pair"])
        for v in (await client.get("/api/sod/register", headers=admin)).json()["violations"]
    }
    assert ("cashier", "procurement_officer") in pairs


async def test_rules_admin(client: AsyncClient, make_user: MakeUser, login: Login) -> None:
    admin = await login(await make_user("admin"))
    rules = (await client.get("/api/sod/rules", headers=admin)).json()
    assert len(rules) == 13 and rules[0]["role_a"] < rules[0]["role_b"]
    res = await client.post(
        "/api/sod/rules",
        json={
            "role_a": "tender_specialist",
            "role_b": "head_of_sales",
            "description": "Uji pasangan",
        },
        headers=admin,
    )
    assert res.status_code == 201
    dup = await client.post(
        "/api/sod/rules",
        json={"role_a": "head_of_sales", "role_b": "tender_specialist", "description": "Lagi lagi"},
        headers=admin,
    )
    assert dup.status_code == 409
    target = await make_user("tender_specialist")
    blocked = await client.patch(
        f"/api/users/{target.id}",
        json={"roles": ["tender_specialist", "head_of_sales"]},
        headers=admin,
    )
    assert blocked.status_code == 409
    await client.patch(
        f"/api/sod/rules/{res.json()['id']}", json={"is_active": False}, headers=admin
    )
    ok = await client.patch(
        f"/api/users/{target.id}",
        json={"roles": ["tender_specialist", "head_of_sales"]},
        headers=admin,
    )
    assert ok.status_code == 200
    eng = await login(await make_user("engineer"))
    assert (await client.get("/api/sod/rules", headers=eng)).status_code == 403
