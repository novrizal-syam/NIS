"""Shared Pydantic types."""

from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer


def _plain(value: Decimal, places: int) -> str:
    # asyncpg can return NUMERIC with trailing zeros as Decimal('1.250E+7');
    # always send plain digits so clients never see exponent notation.
    return format(value.quantize(Decimal(1).scaleb(-places)), "f")


# Money in integer rupiah, serialized as a string of digits ("12500000").
IDR = Annotated[Decimal, PlainSerializer(lambda v: _plain(v, 0), return_type=str)]
# USD with 2 decimals ("1234.50").
USD = Annotated[Decimal, PlainSerializer(lambda v: _plain(v, 2), return_type=str)]
