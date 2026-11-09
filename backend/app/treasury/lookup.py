"""Master records are keyed by UUID; treasury refers to them by business code."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def by_code[T](session: AsyncSession, model: type[T], code: Any) -> T | None:
    column = model.code  # type: ignore[attr-defined]
    return (await session.execute(select(model).where(column == code))).scalar_one_or_none()
