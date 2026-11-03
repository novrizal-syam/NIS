import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import Role, User
from app.auth.roles_seed import SYSTEM_ROLES
from app.core.errors import AppError
from app.demo import data as d
from app.demo import seed
from app.master.models import Department, Employee, FiscalPeriod, PriceItem, Vendor
from app.services.audit import AuditLog
from app.workflow import engine

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


async def _count(s: AsyncSession, model: Any, *where: Any) -> int:
    stmt = select(func.count()).select_from(model).where(*where)
    return int((await s.execute(stmt)).scalar_one())


async def test_load_demo_matches_the_prompt(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as s:
        summary = await seed.load(s, password=d.DEMO_PASSWORD_DEFAULT)
        await s.commit()
        assert summary.counts["users"] == len(SYSTEM_ROLES)  # one user per role
        assert summary.counts["clients"] == 5
        assert summary.counts["vendors"] == 15
        assert summary.counts["items"] == 10 and summary.counts["assets"] == 6
        assert summary.counts["price_items"] == 8
        assert summary.counts["crm_leads"] == 8 and summary.counts["crm_opportunities"] == 5

        per_cat = dict(
            (await s.execute(select(Vendor.category, func.count()).group_by(Vendor.category)))
            .tuples()
            .all()
        )
        assert set(per_cat.values()) == {3} and len(per_cat) == 5
        assert await _count(s, Vendor, Vendor.status == "csms_pending") == 1
        assert await _count(s, Employee, Employee.is_field.is_(True)) == 8
        periods = dict(
            (await s.execute(select(FiscalPeriod.month, FiscalPeriod.status))).tuples().all()
        )
        assert [periods[m] for m in range(1, 13)] == ["closed"] * 9 + ["open"] + ["future"] * 2
        # Everything loaded is flagged as demo.
        for model in (User, Department, Vendor, Employee, PriceItem, FiscalPeriod):
            assert await _count(s, model, model.is_demo.is_(False)) == 0
        # Every role has exactly one demo user who can log in.
        role_users = await s.execute(
            select(Role.code, func.count(User.id))
            .join(User.roles)
            .where(User.is_demo.is_(True))
            .group_by(Role.code)
        )
        assert dict(role_users.tuples().all()) == {r.code: 1 for r in SYSTEM_ROLES}

        with pytest.raises(AppError) as err:
            await seed.load(s, password="x")
        assert err.value.code == "DEMO_EXISTS"


async def test_demo_user_can_sign_in(
    client: AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with sessionmaker() as s:
        await seed.load(s, password=d.DEMO_PASSWORD_DEFAULT)
        await s.commit()
    res = await client.post(
        "/api/auth/login",
        json={"email": f"engineer@{d.EMAIL_DOMAIN}", "password": d.DEMO_PASSWORD_DEFAULT},
    )
    assert res.status_code == 200


async def test_remove_demo_is_super_admin_only_and_complete(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as s:
        await seed.load(s, password=d.DEMO_PASSWORD_DEFAULT)
        await s.commit()
        # A demo user raised a request: removal cleans that up too.
        eng = (
            await s.execute(select(User).where(User.email == f"engineer@{d.EMAIL_DOMAIN}"))
        ).scalar_one()
        from app.auth.principal import load_principal

        await engine.submit(
            s,
            await load_principal(s, eng),
            doc_type="purchase_requisition",
            doc_id=uuid.uuid4(),
            doc_number="PR-DEMO-1",
            title="demo",
            amount=1_000_000,
        )
        await s.commit()

    admin = await login(await make_user("admin"))
    assert (await client.get("/api/admin/demo", headers=admin)).status_code == 403
    assert (await client.post("/api/admin/demo/remove", headers=admin)).status_code == 403

    sa_user = await make_user("super_admin")
    sa = await login(sa_user)
    status = (await client.get("/api/admin/demo", headers=sa)).json()
    assert status["present"] is True and status["counts"]["vendors"] == 15
    res = await client.post("/api/admin/demo/remove", headers=sa)
    assert res.status_code == 200, res.text
    assert res.json()["removed"]["users"] == len(SYSTEM_ROLES)
    assert res.json()["removed"]["crm_leads"] == 8
    assert (await client.get("/api/admin/demo", headers=sa)).json()["present"] is False

    async with sessionmaker() as s:
        # Real data and configuration stay.
        assert await _count(s, User) == 2
        assert await _count(s, Role) == len(SYSTEM_ROLES)
        log = (
            await s.execute(select(AuditLog).where(AuditLog.action == "demo_removed"))
        ).scalar_one()
        assert log.actor_id == sa_user.id


async def test_remove_refuses_when_real_data_depends_on_demo(
    make_user: MakeUser, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with sessionmaker() as s:
        await seed.load(s, password=d.DEMO_PASSWORD_DEFAULT)
        await s.commit()
        dept = (await s.execute(select(Department).where(Department.code == "OPS"))).scalar_one()
    await make_user("engineer", department_id=dept.id)  # a real user in a demo department
    async with sessionmaker() as s:
        with pytest.raises(AppError) as err:
            await seed.remove(s, actor_id=None)
        assert err.value.code == "DEMO_IN_USE"
        await s.rollback()
        assert await _count(s, Vendor) == 15  # nothing was removed
