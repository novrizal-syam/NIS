import uuid
from collections.abc import Awaitable, Callable

import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import Role, RolePermission, User, UserRole
from app.auth.permissions import MODULES, Action, Scope
from app.auth.principal import Principal, load_principal, require, scope_filter, strip_sensitive
from app.auth.roles_seed import SYSTEM_ROLES
from app.main import app
from app.master.models import Department

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]

# Test-only endpoints: one per (module, action) used below.
_probe = APIRouter(prefix="/api/_probe")
CASES = [
    ("procurement", "approve"),
    ("procurement", "submit"),
    ("treasury", "approve"),
    ("treasury", "post"),
    ("treasury", "submit"),
    ("finance", "view"),
    ("finance", "post"),
    ("operations", "approve"),
    ("users", "admin"),
    ("capex", "approve"),
    ("payroll", "approve"),
]
for _m, _a in CASES:

    async def _ok(_: Principal = Depends(require(_m, _a))) -> dict[str, bool]:  # noqa: B008
        return {"ok": True}

    _probe.add_api_route(f"/{_m}/{_a}", _ok, methods=["GET"])
app.include_router(_probe)


@pytest.mark.parametrize(
    ("role", "module", "action", "allowed"),
    [
        # DOA.md approval chain
        ("head_of_operation", "procurement", "approve", True),
        ("head_of_finance", "procurement", "approve", True),
        ("director", "procurement", "approve", True),
        ("engineer", "procurement", "approve", False),
        ("engineer", "procurement", "submit", True),
        ("procurement_officer", "procurement", "approve", False),
        # Payment run: AP prepares, HoF/Director approve, Cashier releases (post)
        ("ap_accountant", "treasury", "submit", True),
        ("ap_accountant", "treasury", "approve", False),
        ("cashier", "treasury", "post", True),
        ("cashier", "treasury", "approve", False),
        ("head_of_finance", "treasury", "approve", True),
        ("head_of_finance", "treasury", "post", False),
        # Admin is IT only: no business approvals or postings
        ("admin", "users", "admin", True),
        ("admin", "procurement", "approve", False),
        ("admin", "finance", "post", False),
        # DOR: superintendent approves, field engineer cannot
        ("ofs_superintendent", "operations", "approve", True),
        ("field_engineer", "operations", "approve", False),
        ("account_executive", "finance", "view", False),
        ("shareholders", "capex", "approve", True),
        ("shareholders", "procurement", "approve", False),
        ("head_of_finance", "payroll", "approve", True),
        ("hcbp_officer", "payroll", "approve", False),
        ("client_rep", "finance", "view", False),
        ("super_admin", "finance", "post", True),
    ],
)
async def test_permission_matrix(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    role: str,
    module: str,
    action: str,
    allowed: bool,
) -> None:
    user = await make_user(role)
    headers = await login(user)
    res = await client.get(f"/api/_probe/{module}/{action}", headers=headers)
    if allowed:
        assert res.status_code == 200, res.text
    else:
        assert res.status_code == 403
        assert res.json()["code"] == "PERMISSION_DENIED"
        assert res.json()["message"].startswith("Anda tidak memiliki izin")


def test_seed_matches_doa_roles() -> None:
    assert len(SYSTEM_ROLES) == 29
    by_code = {r.code: r for r in SYSTEM_ROLES}
    # Admin has no business approve/post permissions by default (DOA.md).
    assert not [g for g in by_code["admin"].grants if g[1] in {"approve", "post"}]
    # Cashier releases but never approves.
    assert not [g for g in by_code["cashier"].grants if g[1] == "approve"]
    # Sensitive fields default to HCBP, Head of Finance, Director (and Super Admin); the
    # Cashier sees bank accounts only, for the payroll bank file (07c).
    sensitive = {r.code for r in SYSTEM_ROLES if any(g[0] == "sensitive" for g in r.grants)}
    assert sensitive == {"super_admin", "director", "head_of_finance", "hcbp_officer", "cashier"}
    assert [g[1] for g in by_code["cashier"].grants if g[0] == "sensitive"] == ["bank_account"]
    assert all(m in MODULES or m == "sensitive" for r in SYSTEM_ROLES for m, _, _ in r.grants)


async def test_seeded_roles_in_database(session: AsyncSession) -> None:
    codes = set((await session.execute(select(Role.code).where(Role.is_system))).scalars())
    assert codes == {r.code for r in SYSTEM_ROLES}


async def test_multi_role_union_and_active_role(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    user = await make_user("engineer", "procurement_officer")
    headers = await login(user)
    me = (await client.get("/api/auth/me", headers=headers)).json()
    assert {r["code"] for r in me["roles"]} == {"engineer", "procurement_officer"}
    # Widest scope wins: engineer has procurement.submit=own, procurement officer =all.
    assert me["permissions"]["procurement"]["submit"] == "all"

    as_engineer = {**headers, "X-Active-Role": "engineer"}
    me2 = (await client.get("/api/auth/me", headers=as_engineer)).json()
    assert me2["active_role"] == "engineer"
    assert me2["permissions"]["procurement"]["submit"] == "own"
    assert len(me2["roles"]) == 2  # switcher still lists both

    bad = await client.get("/api/auth/me", headers={**headers, "X-Active-Role": "director"})
    assert bad.status_code == 403
    assert bad.json()["code"] == "ROLE_NOT_ASSIGNED"


async def test_revoked_permission_applies_immediately(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as s:
        role = Role(code="uji_custom", name="Uji")
        s.add(role)
        await s.flush()
        s.add(RolePermission(role_id=role.id, module="finance", action="view", scope="all"))
        await s.commit()
    user = await make_user("uji_custom")
    headers = await login(user)
    assert (await client.get("/api/_probe/finance/view", headers=headers)).status_code == 200
    async with sessionmaker() as s:
        await s.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        await s.commit()
    # Same access token, permission already gone.
    assert (await client.get("/api/_probe/finance/view", headers=headers)).status_code == 403


async def test_deactivated_user_token_stops_working(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    user = await make_user("engineer")
    headers = await login(user)
    async with sessionmaker() as s:
        u = await s.get(User, user.id)
        assert u is not None
        u.is_active = False
        await s.commit()
    assert (await client.get("/api/auth/ping", headers=headers)).status_code == 401


async def _principal_with(
    session: AsyncSession,
    user: User,
    grants: dict[tuple[str, str], Scope],
    project_ids: frozenset[uuid.UUID] = frozenset(),
) -> Principal:
    p = await load_principal(session, user)
    p.grants = grants
    p.project_ids = project_ids
    return p


async def test_scope_filter(
    make_user: MakeUser, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with sessionmaker() as s:
        ops, fin = Department(code="OPS", name="Operasi"), Department(code="FIN", name="Keuangan")
        s.add_all([ops, fin])
        await s.commit()
    me = await make_user("engineer", department_id=ops.id)
    mine = await make_user("engineer", department_id=fin.id)  # created by "me"
    colleague = await make_user("engineer", department_id=ops.id)
    stranger = await make_user("engineer", department_id=fin.id)

    async with sessionmaker() as s:
        for u in (mine,):
            row = await s.get(User, u.id)
            assert row is not None
            row.created_by = me.id
        for u in (colleague,):
            row = await s.get(User, u.id)
            assert row is not None
            row.created_by = colleague.id
        await s.commit()

        me_row = await s.get(User, me.id)
        assert me_row is not None
        key = ("master", "view")

        async def visible(scope: Scope | None, **kw: frozenset[uuid.UUID]) -> set[uuid.UUID]:
            p = await _principal_with(s, me_row, {key: scope} if scope else {}, **kw)
            cond = scope_filter(
                p,
                "master",
                Action.VIEW,
                owner_col=User.created_by,
                department_col=User.department_id,
                project_col=User.id,
            )
            return set((await s.execute(select(User.id).where(cond))).scalars())

        assert await visible(None) == set()
        assert await visible(Scope.OWN) == {mine.id}
        assert await visible(Scope.DEPARTMENT) == {mine.id, me.id, colleague.id}
        # project_col=User.id stands in for "row belongs to one of my projects"
        assert await visible(Scope.PROJECT, project_ids=frozenset({stranger.id})) == {
            mine.id,
            stranger.id,
        }
        assert await visible(Scope.ALL) == {me.id, mine.id, colleague.id, stranger.id}


async def test_sensitive_fields_stripped(
    make_user: MakeUser, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    hcbp = await make_user("hcbp_officer")
    eng = await make_user("engineer")
    row = {"name": "Budi", "basic_salary": 15_000_000, "nik": "3172xxxx", "bank_account": "123"}
    fields = {"basic_salary": "salary", "nik": "nik", "bank_account": "bank_account"}
    async with sessionmaker() as s:
        p_hcbp = await load_principal(s, (await s.get(User, hcbp.id)))  # type: ignore[arg-type]
        p_eng = await load_principal(s, (await s.get(User, eng.id)))  # type: ignore[arg-type]
    assert strip_sensitive(p_hcbp, row, fields) == row
    assert strip_sensitive(p_eng, row, fields) == {"name": "Budi"}


async def test_require_rejects_unknown_module() -> None:
    with pytest.raises(ValueError, match="unknown module"):
        require("nope", "view")


async def test_user_roles_cleanup(session: AsyncSession) -> None:
    # Sanity: fixtures leave no users behind between tests.
    assert (await session.execute(select(UserRole))).first() is None
