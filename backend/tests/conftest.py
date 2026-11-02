"""Test fixtures. Uses TEST_DATABASE_URL (a separate database) migrated with Alembic."""

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, insert, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth import service as auth_service
from app.auth.models import User
from app.auth.principal import Principal, load_principal
from app.core.config import get_settings
from app.core.db import get_session, make_engine, make_sessionmaker
from app.main import app
from app.master.config_seed import ACCOUNTS, COST_ELEMENTS, CURRENCIES

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", get_settings().test_database_url)
# Seeded configuration (system roles and their permissions) survives between tests.
TABLES = (
    "doc_counters",
    "audit_log",
    "refresh_tokens",
    "user_roles",
    "approval_steps",
    "approval_requests",
    "doa_delegations",
    "doa_rule_changes",
    "price_items",
    "fx_rates",
    "employees",
    "cost_centers",
    "clients",
    "vendors",
    "items",
    "warehouses",
    "assets",
    "fiscal_periods",
    "users",
    "departments",
)


def _alembic_config() -> Config:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option(
        "script_location", os.path.join(os.path.dirname(__file__), "..", "migrations")
    )
    cfg.attributes["db_url"] = TEST_DB_URL
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = make_engine(TEST_DB_URL, pool_size=10, max_overflow=60)
    async with eng.begin() as conn:
        # Fresh schema every run, built by the real migrations.
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    cfg = _alembic_config()
    async with eng.begin() as conn:
        await conn.run_sync(lambda sync_conn: _upgrade(cfg, sync_conn))
    yield eng
    await eng.dispose()


def _seed_rules(connection: Connection) -> None:
    from app.workflow.models import DoaRule, DoaRuleStep
    from app.workflow.rules_seed import RULES

    for r in RULES:
        rule_id = uuid.uuid4()
        connection.execute(
            insert(DoaRule).values(
                id=rule_id,
                doc_type=r.doc_type,
                name=r.name,
                priority=r.priority,
                condition=r.condition or {},
                escalation_hours=r.escalation_hours,
                escalate_to_role=r.escalate_to_role,
            )
        )
        connection.execute(
            insert(DoaRuleStep),
            [
                {
                    "rule_id": rule_id,
                    "seq": st.seq,
                    "approver_role": st.role,
                    "label": st.label,
                    "approver_scope": st.scope,
                }
                for st in r.steps
            ],
        )


def _upgrade(cfg: Config, connection: object) -> None:
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


@pytest.fixture
async def sessionmaker(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory for one test; tables are emptied afterwards."""
    yield make_sessionmaker(engine)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        await conn.execute(text("DELETE FROM roles WHERE NOT is_system"))
        # Keep the configuration seed (COA, cost elements, currencies); drop test additions.
        await conn.execute(
            text("DELETE FROM cost_elements WHERE NOT code = ANY(:c)"),
            {"c": [c for c, _, _ in COST_ELEMENTS]},
        )
        await conn.execute(
            text("DELETE FROM accounts WHERE NOT code = ANY(:c)"), {"c": [c for c, *_ in ACCOUNTS]}
        )
        await conn.execute(
            text("DELETE FROM currencies WHERE NOT code = ANY(:c)"),
            {"c": [c for c, *_ in CURRENCIES]},
        )
        # Tests may change DOA rules; restore the seed.
        await conn.execute(text("DELETE FROM doa_rules"))
        await conn.run_sync(lambda c: _seed_rules(c))


@pytest.fixture
async def session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as s:
        yield s


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


PASSWORD = "Rahasia-Kuat-2026"


@pytest.fixture
def make_user(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[User]]:
    """Create an active user that can log in with PASSWORD (no pending steps by default)."""

    async def _make(
        *roles: str,
        email: str | None = None,
        must_change_password: bool = False,
        department_id: uuid.UUID | None = None,
        two_factor: bool = True,
    ) -> User:
        async with sessionmaker() as s:
            user, _ = await auth_service.create_user(
                s,
                email=email or f"{'-'.join(roles) or 'user'}-{uuid.uuid4().hex[:6]}@gek.co.id",
                full_name="Pengguna Uji",
                role_codes=list(roles),
                actor_id=None,
                password=PASSWORD,
                department_id=department_id,
            )
            user.must_change_password = must_change_password
            # Marked enrolled without a secret: login asks no code. Tests of the 2FA flow
            # itself pass two_factor=False.
            user.totp_enabled = two_factor
            await s.commit()
            return user

    return _make


@pytest.fixture
def login(client: AsyncClient) -> Callable[..., Awaitable[dict[str, str]]]:
    """Log in and return Authorization headers."""

    async def _login(user: User, *, totp_code: str | None = None) -> dict[str, str]:
        res = await client.post(
            "/api/auth/login",
            json={"email": user.email, "password": PASSWORD, "totp_code": totp_code},
        )
        assert res.status_code == 200, res.text
        return {"Authorization": f"Bearer {res.json()['access_token']}"}

    return _login


@pytest.fixture
def principal_of(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[Principal]]:
    """Principal bound to a long-lived session (for calling services directly)."""
    sessions: list[AsyncSession] = []

    async def _p(user: User, session: AsyncSession, active_role: str | None = None) -> Principal:
        db_user = await session.get(User, user.id)
        assert db_user is not None
        return await load_principal(session, db_user, active_role)

    _p.sessions = sessions  # type: ignore[attr-defined]
    return _p
