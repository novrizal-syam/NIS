"""Money helpers. IDR is integer rupiah (NUMERIC(18,0)); USD has 2 decimals. Never float."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

IDR_QUANT = Decimal("1")
USD_QUANT = Decimal("0.01")
MAX_DIGITS = 18


class MoneyError(ValueError):
    pass


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):
        raise MoneyError("Nilai uang tidak boleh berupa float; gunakan Decimal, int atau str.")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise MoneyError(f"Nilai uang tidak valid: {value!r}.") from exc
    if not result.is_finite():
        raise MoneyError(f"Nilai uang tidak valid: {value!r}.")
    return result


def _check_size(value: Decimal, scale: int) -> None:
    if abs(value) >= Decimal(10) ** (MAX_DIGITS - scale):
        raise MoneyError("Nilai uang melebihi batas 18 digit.")


def to_idr(value: Decimal | int | str) -> int:
    """Round to whole rupiah (half up, away from zero) and return an int."""
    result = _to_decimal(value).quantize(IDR_QUANT, rounding=ROUND_HALF_UP)
    _check_size(result, 0)
    return int(result)


def to_usd(value: Decimal | int | str) -> Decimal:
    result = _to_decimal(value).quantize(USD_QUANT, rounding=ROUND_HALF_UP)
    _check_size(result, 2)
    return result


def _group(digits: str) -> str:
    """Group integer digits with '.' (id-ID thousands separator)."""
    out: list[str] = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return ".".join(out)


def format_idr(value: Decimal | int | str) -> str:
    """`1250000` -> `Rp 1.250.000`; negatives as `-Rp 1.250.000` (matches Intl id-ID)."""
    amount = to_idr(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}Rp {_group(str(abs(amount)))}"


def format_usd(value: Decimal | int | str) -> str:
    """`1234.5` -> `US$ 1.234,50` (id-ID separators)."""
    amount = to_usd(value)
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    return f"{sign}US$ {_group(whole)},{frac}"


def format_number(value: Decimal | int | str, decimals: int = 0) -> str:
    """Plain id-ID number: `1234567.891, 2` -> `1.234.567,89`."""
    quant = Decimal(1).scaleb(-decimals)
    amount = _to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    text = f"{abs(amount):.{decimals}f}"
    if decimals:
        whole, frac = text.split(".")
        return f"{sign}{_group(whole)},{frac}"
    return f"{sign}{_group(text)}"
