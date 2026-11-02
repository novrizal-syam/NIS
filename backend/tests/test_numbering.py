import asyncio
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.services import numbering


async def test_format_and_sequence(session: AsyncSession) -> None:
    d = date(2026, 10, 7)
    assert await numbering.next(session, "LD", on=d) == "LD-26-001"
    assert await numbering.next(session, "LD", on=d) == "LD-26-002"
    assert await numbering.next(session, "PR", on=d) == "PR-26-001"
    assert await numbering.next(session, "JV", on=d) == "JV-26-0001"
    await session.commit()


async def test_sequence_resets_per_year(session: AsyncSession) -> None:
    assert await numbering.next(session, "PO", on=date(2026, 12, 31)) == "PO-26-001"
    assert await numbering.next(session, "PO", on=date(2027, 1, 1)) == "PO-27-001"


async def test_unknown_doc_type(session: AsyncSession) -> None:
    with pytest.raises(AppError) as err:
        await numbering.next(session, "XYZ")
    assert err.value.code == "UNKNOWN_DOC_TYPE"


async def test_rollback_does_not_consume_number(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    d = date(2026, 3, 1)
    async with sessionmaker() as s:
        assert await numbering.next(s, "INV", on=d) == "INV-26-001"
        await s.rollback()
    async with sessionmaker() as s:
        assert await numbering.next(s, "INV", on=d) == "INV-26-001"
        await s.commit()


async def test_letter_number(session: AsyncSession) -> None:
    d = date(2026, 10, 7)
    assert await numbering.next_letter(session, "fin", on=d) == "001/GEK-FIN/X/2026"
    assert await numbering.next_letter(session, "FIN", on=d) == "002/GEK-FIN/X/2026"
    assert await numbering.next_letter(session, "OPS", on=date(2026, 4, 2)) == "001/GEK-OPS/IV/2026"


async def test_letter_rejects_bad_dept(session: AsyncSession) -> None:
    with pytest.raises(AppError):
        await numbering.next_letter(session, "F/IN")


async def test_50_parallel_calls_give_unique_numbers(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Each call runs in its own connection and transaction, all at the same time."""
    d = date(2026, 5, 5)
    start = asyncio.Event()

    async def one() -> str:
        async with sessionmaker() as s:
            await start.wait()
            number = await numbering.next(s, "PR", on=d)
            await asyncio.sleep(0.01)  # hold the lock a moment to force contention
            await s.commit()
            return number

    tasks = [asyncio.create_task(one()) for _ in range(50)]
    await asyncio.sleep(0.05)
    start.set()
    numbers = await asyncio.gather(*tasks)

    assert len(set(numbers)) == 50
    assert sorted(numbers) == [f"PR-26-{i:03d}" for i in range(1, 51)]
