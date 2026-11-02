"""Test fixtures. Uses TEST_DATABASE_URL (a separate database) migrated with Alembic."""

import os
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import get_session, make_engine, make_sessionmaker
from app.main import app

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", get_settings().test_database_url)
TABLES = ("doc_counters", "audit_log")


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


def _upgrade(cfg: Config, connection: object) -> None:
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


@pytest.fixture
async def sessionmaker(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory for one test; tables are emptied afterwards."""
    yield make_sessionmaker(engine)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))


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
