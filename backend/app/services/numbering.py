"""Atomic document numbering.

One row per (doc_type, year) in `doc_counters`. `next()` locks that row with
`SELECT ... FOR UPDATE`, so concurrent callers queue on the lock and never get
the same number. The number is consumed inside the caller's transaction: if the
document insert rolls back, the counter rolls back too (no gaps from failures).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, String, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.errors import AppError
from app.core.models import Base

JAKARTA = ZoneInfo("Asia/Jakarta")

# Document prefixes from CLAUDE.md rule 5. Value = zero-padding width.
DOC_TYPES: dict[str, int] = {
    "LD": 3, "OPP": 3, "QT": 3, "CTR": 3, "PRJ": 3, "BCR": 3, "MR": 3, "PR": 3, "RFQ": 3,
    "PO": 3, "GR": 3, "VI": 3, "DOR": 3, "TK": 3, "INV": 3, "PAY": 3, "CA": 3,
    "CPX": 3, "WO": 3, "JV": 4, "TRF": 3, "SOP": 3,
    "HRA": 3, "PTW": 3, "INS": 3, "OBS": 3, "INC": 3, "CAPA": 3, "RCP": 3,
}  # fmt: skip

LETTER_PREFIX = "LTR"
ROMAN_MONTHS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")


class DocCounter(Base):
    __tablename__ = "doc_counters"

    doc_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def today_jakarta() -> date:
    return datetime.now(JAKARTA).date()


async def _increment(session: AsyncSession, key: str, year: int) -> int:
    # Make sure the row exists without racing on the insert, then lock it.
    await session.execute(
        insert(DocCounter)
        .values(doc_type=key, year=year, last_value=0)
        .on_conflict_do_nothing(index_elements=["doc_type", "year"])
    )
    counter = (
        await session.execute(
            select(DocCounter)
            .where(DocCounter.doc_type == key, DocCounter.year == year)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    counter.last_value += 1
    await session.flush()
    return counter.last_value


async def next(session: AsyncSession, doc_type: str, *, on: date | None = None) -> str:
    """Return the next number for `doc_type`, e.g. `PR-26-031` or `JV-26-0001`.

    Must be called inside the transaction that inserts the document.
    """
    width = DOC_TYPES.get(doc_type)
    if width is None:
        raise AppError("UNKNOWN_DOC_TYPE", f"Jenis dokumen '{doc_type}' tidak dikenal.")
    year = (on or today_jakarta()).year
    value = await _increment(session, doc_type, year)
    return f"{doc_type}-{year % 100:02d}-{value:0{width}d}"


async def next_letter(session: AsyncSession, dept: str, *, on: date | None = None) -> str:
    """Outgoing letter number `001/GEK-{DEPT}/{roman month}/{year}`; sequence per dept per year."""
    dept = dept.strip().upper()
    if not dept.isalnum() or len(dept) > 10:
        raise AppError("INVALID_DEPT", "Kode departemen hanya huruf/angka, maksimal 10 karakter.")
    day = on or today_jakarta()
    value = await _increment(session, f"{LETTER_PREFIX}-{dept}", day.year)
    return f"{value:03d}/GEK-{dept}/{ROMAN_MONTHS[day.month - 1]}/{day.year}"
