"""Foreign currency (USD) rates: IDR per 1 unit from master `fx_rates` (BI middle rate)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.master.models import FxRate

BASE = "IDR"


async def rate(session: AsyncSession, currency: str, on: date) -> Decimal:
    """Latest rate on or before `on`; IDR is 1."""
    if currency == BASE:
        return Decimal(1)
    row = (
        await session.execute(
            select(FxRate.rate)
            .where(FxRate.currency == currency, FxRate.rate_date <= on)
            .order_by(FxRate.rate_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError(
            "FX_RATE_MISSING",
            f"Kurs {currency} untuk {on:%d/%m/%Y} belum ada. Isi di Data Master > Kurs.",
            status_code=422,
        )
    return Decimal(row)


def to_idr(amount: Decimal, fx_rate: Decimal) -> Decimal:
    return (amount * fx_rate).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def cents(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
