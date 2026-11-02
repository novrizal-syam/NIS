"""Async SQLAlchemy engine, session factory and the FastAPI session dependency."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def make_engine(url: str, *, pool_size: int = 10, max_overflow: int = 20) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        # Every connection works in Jakarta time; timestamps are stored as timestamptz.
        connect_args={"server_settings": {"timezone": "Asia/Jakarta"}},
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


_settings = get_settings()
engine: AsyncEngine = make_engine(
    _settings.database_url,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
)
SessionLocal: async_sessionmaker[AsyncSession] = make_sessionmaker(engine)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request. The caller commits; anything uncommitted is rolled back."""
    async with SessionLocal() as session:
        yield session
