"""Async SQLAlchemy engine, session factory and the FastAPI session dependency."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

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


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """One session per request. The caller commits; anything uncommitted is rolled back."""
    async with SessionLocal() as session:
        yield session


# Set by the app factory so background work and middleware use the same session provider
# as endpoints (tests override get_session).
_session_provider: list[Any] = []


def use_session_provider(provider: Any) -> None:
    _session_provider[:] = [provider]


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A session outside a request (background tasks, middleware)."""
    provider = _session_provider[0]() if _session_provider else get_session
    gen: AsyncGenerator[AsyncSession, None] = provider()
    session = await anext(gen)
    try:
        yield session
    finally:
        await gen.aclose()
