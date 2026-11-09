"""Test fixtures. Uses TEST_DATABASE_URL (a separate database) migrated with Alembic."""

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import boto3
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from sqlalchemy import Connection, insert, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth import service as auth_service
from app.auth.models import User
from app.auth.principal import PRIVACY_VERSION, Principal, load_principal
from app.core.config import get_settings
from app.core.db import get_session, make_engine, make_sessionmaker
from app.main import app
from app.master.config_seed import ACCOUNTS, COST_ELEMENTS, CURRENCIES, EQUIPMENT_TYPES
from app.services.storage import Storage, get_storage
from app.treasury.seed import BANK_ACCOUNTS

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", get_settings().test_database_url)
# Seeded configuration (system roles and their permissions) survives between tests.
TABLES = (
    "cash_advance_lines",
    "cash_advances",
    "payment_run_items",
    "payment_runs",
    "manual_journals",
    "bank_lines",
    "receipt_allocations",
    "customer_receipts",
    "invoice_tickets",
    "customer_invoices",
    "ticket_lines",
    "ticket_dors",
    "service_tickets",
    "qhse_capas",
    "qhse_incidents",
    "qhse_observations",
    "qhse_inspections",
    "qhse_permits",
    "qhse_risk_assessments",
    "work_order_parts",
    "downtime_log",
    "work_orders",
    "asset_allocations",
    "pm_schedules",
    "pm_tasks",
    "payroll_days",
    "hse_daily",
    "asset_usage",
    "dor_consumables",
    "dor_crew",
    "dor_equipment",
    "dors",
    "vendor_credit_notes",
    "vendor_invoice_lines",
    "vendor_invoices",
    "material_request_lines",
    "material_requests",
    "goods_receipt_lines",
    "goods_receipts",
    "stock_count_lines",
    "stock_counts",
    "stock_transfer_lines",
    "stock_transfers",
    "stock_moves",
    "stock_balances",
    "journal_lines",
    "journal_entries",
    "project_members",
    "tender_clarifications",
    "tender_documents",
    "tenders",
    "price_history",
    "purchase_order_lines",
    "purchase_orders",
    "rfq_quote_lines",
    "rfq_quotes",
    "rfqs",
    "purchase_requisition_lines",
    "purchase_requisitions",
    "budget_ledger",
    "budget_version_lines",
    "budget_versions",
    "budget_change_requests",
    "project_budget_lines",
    "project_wbs",
    "projects",
    "contract_rates",
    "contracts",
    "outgoing_letters",
    "crm_quotation_lines",
    "crm_quotations",
    "crm_bid_decisions",
    "crm_opportunities",
    "crm_leads",
    "notifications",
    "password_reset_requests",
    "email_log",
    "attachments",
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
        # A fresh database starts the first-run wizard; tests outside test_setup run as an
        # installation that is already set up.
        await conn.execute(
            text("UPDATE system_settings SET value = 'true' WHERE key = 'setup_completed'")
        )
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
            text("DELETE FROM equipment_types WHERE NOT code = ANY(:c)"),
            {"c": [c for c, *_ in EQUIPMENT_TYPES]},
        )
        await conn.execute(
            text("DELETE FROM bank_accounts WHERE NOT code = ANY(:c)"),
            {"c": [c for c, *_ in BANK_ACCOUNTS]},
        )
        await conn.execute(
            text(
                "UPDATE bank_accounts SET is_active = true, is_default = (code = :d),"
                " adapter = 'csv'"
            ),
            {"d": BANK_ACCOUNTS[0][0]},
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
    app.dependency_overrides.pop(get_session, None)


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
        onboarded: bool = True,
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
            if onboarded:  # privacy notice accepted and profile filled
                user.privacy_version = PRIVACY_VERSION
                user.privacy_accepted_at = user.created_at
                user.profile_completed_at = user.created_at
                user.phone = "0812000000"
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


@pytest.fixture
def storage() -> Iterator[Storage]:
    """In-memory S3 (moto) wired into the API for the duration of a test."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        store = Storage(s3, "test-bucket")
        s3.create_bucket(Bucket="test-bucket")
        app.dependency_overrides[get_storage] = lambda: store
        yield store
        app.dependency_overrides.pop(get_storage, None)
