from collections.abc import AsyncIterator, Awaitable, Callable

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.models import User
from app.core.config import get_settings
from app.core.errors import AppError
from app.master.models import Department
from app.services.audit import AuditLog
from app.setup import service as setup_service

MakeUser = Callable[..., Awaitable[User]]
TOKEN = "setup-token-uji-123"
STRONG = "Kuat!Sekali2026"


@pytest.fixture
async def fresh_install(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    """Pretend nobody has run setup yet; restore afterwards."""
    monkeypatch.setattr(get_settings(), "setup_token", TOKEN)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE system_settings SET value='false' WHERE key='setup_completed'")
        )
        await conn.execute(text("DELETE FROM system_settings WHERE key <> 'setup_completed'"))
    setup_service.reset_cache()
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE system_settings SET value='true' WHERE key='setup_completed'")
        )
        await conn.execute(text("DELETE FROM system_settings WHERE key <> 'setup_completed'"))
    setup_service.reset_cache()


H = {"X-Setup-Token": TOKEN}


async def test_token_required(
    client: AsyncClient, fresh_install: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"email": "sa@gek.co.id", "full_name": "Super Admin", "password": STRONG}
    res = await client.post("/api/setup/admin", json=body)
    assert res.status_code == 403 and res.json()["code"] == "SETUP_TOKEN_INVALID"
    res = await client.post("/api/setup/admin", json=body, headers={"X-Setup-Token": "salah"})
    assert res.status_code == 403
    monkeypatch.setattr(get_settings(), "setup_token", "")
    res = await client.post("/api/setup/admin", json=body, headers=H)
    assert res.json()["code"] == "SETUP_TOKEN_MISSING"


async def test_rest_of_api_is_closed_until_setup_finishes(
    client: AsyncClient, fresh_install: None
) -> None:
    res = await client.get("/api/master/vendors")
    assert res.status_code == 423 and res.json()["code"] == "SETUP_REQUIRED"
    assert (await client.get("/api/workflow/inbox/count")).status_code == 423
    assert (await client.get("/api/health")).status_code == 200
    status = (await client.get("/api/setup/status")).json()
    assert status == {"setup_completed": False, "token_configured": True, "steps": {}}


async def test_full_wizard(
    client: AsyncClient, fresh_install: None, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    weak = await client.post(
        "/api/setup/admin",
        json={"email": "sa@gek.co.id", "full_name": "Andi Pratama", "password": "lemah123456"},
        headers=H,
    )
    assert weak.status_code == 422 and "simbol" in weak.json()["message"]

    res = await client.post(
        "/api/setup/admin",
        json={"email": "sa@gek.co.id", "full_name": "Andi Pratama", "password": STRONG},
        headers=H,
    )
    assert res.status_code == 200, res.text
    auth = {**H, "Authorization": f"Bearer {res.json()['access_token']}"}
    again = await client.post(
        "/api/setup/admin",
        json={"email": "x@gek.co.id", "full_name": "Kedua", "password": STRONG},
        headers=H,
    )
    assert again.status_code == 409

    # Steps cannot be skipped.
    early = await client.put(
        "/api/setup/company", json={"legal_name": "PT Global Energi KITA"}, headers=auth
    )
    assert early.status_code == 409 and early.json()["code"] == "SETUP_STEP_MISSING"

    secret = (await client.post("/api/setup/totp/setup", headers=auth)).json()["secret"]
    codes = (
        await client.post(
            "/api/setup/totp/verify", json={"code": pyotp.TOTP(secret).now()}, headers=auth
        )
    ).json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 9 for c in codes)

    company = await client.put(
        "/api/setup/company",
        json={
            "legal_name": "PT Global Energi KITA",
            "npwp": "01.234.567.8-091.000",
            "address": "Jakarta",
        },
        headers=auth,
    )
    assert company.status_code == 200 and company.json()["timezone"] == "Asia/Jakarta"

    suggested = (await client.get("/api/setup/departments", headers=auth)).json()
    assert {"code": "OPS", "name": "Operasi"} in suggested
    deps = await client.put(
        "/api/setup/departments", json={"departments": suggested[:4]}, headers=auth
    )
    assert deps.json() == {"created": 4, "total": 4}

    assert (
        await client.post("/api/setup/finish", headers=auth)
    ).status_code == 409  # demo step missing
    assert (
        await client.post("/api/setup/demo", json={"load_demo": False}, headers=auth)
    ).json() == {"loaded": {}}
    assert (await client.post("/api/setup/finish", headers=auth)).json() == {
        "setup_completed": True
    }

    # Forever closed afterwards, the rest of the API opens.
    for method, path in (
        ("post", "/api/setup/admin"),
        ("put", "/api/setup/company"),
        ("post", "/api/setup/finish"),
    ):
        res = await getattr(client, method)(path, json={}, headers=auth)
        assert res.status_code == 403 and res.json()["code"] == "SETUP_DONE", path
    assert (await client.get("/api/setup/status")).json()["setup_completed"] is True
    me = await client.get("/api/auth/me", headers={"Authorization": auth["Authorization"]})
    assert me.status_code == 200 and me.json()["roles"] == [
        {"code": "super_admin", "name": "Super Admin"}
    ]

    async with sessionmaker() as s:
        steps = [
            (log.after or {}).get("step")
            for log in (
                await s.execute(
                    select(AuditLog).where(AuditLog.action == "setup_step").order_by(AuditLog.at)
                )
            ).scalars()
        ]
        assert steps == ["admin", "totp", "company", "departments", "demo"]
        assert (
            len(
                (await s.execute(select(Department).where(Department.is_demo.is_(False))))
                .scalars()
                .all()
            )
            == 4
        )


async def test_wizard_can_load_demo(
    client: AsyncClient, fresh_install: None, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    res = await client.post(
        "/api/setup/admin",
        json={"email": "sa@gek.co.id", "full_name": "Andi", "password": STRONG},
        headers=H,
    )
    auth = {**H, "Authorization": f"Bearer {res.json()['access_token']}"}
    secret = (await client.post("/api/setup/totp/setup", headers=auth)).json()["secret"]
    await client.post(
        "/api/setup/totp/verify", json={"code": pyotp.TOTP(secret).now()}, headers=auth
    )
    await client.put(
        "/api/setup/company", json={"legal_name": "PT Global Energi KITA"}, headers=auth
    )
    await client.put(
        "/api/setup/departments",
        json={"departments": [{"code": "OPS", "name": "Operasi"}]},
        headers=auth,
    )
    loaded = (await client.post("/api/setup/demo", json={"load_demo": True}, headers=auth)).json()[
        "loaded"
    ]
    assert loaded["vendors"] == 15 and loaded["departments"] == 9  # OPS already real
    async with sessionmaker() as s:
        ops = (await s.execute(select(Department).where(Department.code == "OPS"))).scalar_one()
        assert ops.is_demo is False


async def test_recovery_code_is_break_glass(
    client: AsyncClient, make_user: MakeUser, login: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    from tests.conftest import PASSWORD

    user = await make_user("cashier", two_factor=False)
    h = await login(user)
    secret = (await client.post("/api/auth/totp/setup", headers=h)).json()["secret"]
    codes = (
        await client.post(
            "/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now()}, headers=h
        )
    ).json()["recovery_codes"]
    assert len(codes) == 10

    bad = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": PASSWORD, "recovery_code": "AAAA-AAAA"},
    )
    assert bad.json()["code"] == "RECOVERY_INVALID"
    ok = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": PASSWORD, "recovery_code": codes[0].lower()},
    )
    assert ok.status_code == 200
    me = (
        await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}
        )
    ).json()
    assert "setup_totp" in me["pending"] and me["totp_enabled"] is False

    # Re-enrol; the old (used) code cannot be reused and old codes are replaced.
    h2 = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    secret2 = (await client.post("/api/auth/totp/setup", headers=h2)).json()["secret"]
    new_codes = (
        await client.post(
            "/api/auth/totp/verify", json={"code": pyotp.TOTP(secret2).now()}, headers=h2
        )
    ).json()["recovery_codes"]
    reuse = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": PASSWORD, "recovery_code": codes[1]},
    )
    assert reuse.json()["code"] == "RECOVERY_INVALID"
    assert set(new_codes).isdisjoint(codes)


async def test_last_super_admin_is_protected(
    make_user: MakeUser, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    only = await make_user("super_admin")
    async with sessionmaker() as s:
        with pytest.raises(AppError) as err:
            await setup_service.ensure_super_admin_remains(s, losing_user_id=only.id)
        assert err.value.code == "LAST_SUPER_ADMIN"
    await make_user("super_admin")
    async with sessionmaker() as s:
        await setup_service.ensure_super_admin_remains(s, losing_user_id=only.id)
