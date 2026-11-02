from decimal import Decimal

import pytest

from app.services.money import MoneyError, format_idr, format_number, format_usd, to_idr, to_usd


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1250000, "Rp 1.250.000"),
        (0, "Rp 0"),
        (999, "Rp 999"),
        (1000, "Rp 1.000"),
        (-1250000, "-Rp 1.250.000"),
        ("25000000000", "Rp 25.000.000.000"),
        (Decimal("1250000.5"), "Rp 1.250.001"),
    ],
)
def test_format_idr(value: Decimal | int | str, expected: str) -> None:
    assert format_idr(value) == expected


def test_to_idr_rounds_half_up_away_from_zero() -> None:
    assert to_idr(Decimal("10.5")) == 11
    assert to_idr(Decimal("10.49")) == 10
    assert to_idr(Decimal("-10.5")) == -11
    assert isinstance(to_idr("7"), int)


def test_to_usd() -> None:
    assert to_usd("1.005") == Decimal("1.01")
    assert format_usd("1234.5") == "US$ 1.234,50"


def test_format_number() -> None:
    assert format_number("1234567.891", 2) == "1.234.567,89"
    assert format_number(1234567) == "1.234.567"


def test_float_rejected() -> None:
    with pytest.raises(MoneyError):
        to_idr(1.1)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity", "1" * 19])
def test_invalid_values(bad: str) -> None:
    with pytest.raises(MoneyError):
        to_idr(bad)
