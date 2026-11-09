"""Payroll arithmetic (pure functions; reference data passed in).

Rupiah amounts are whole numbers: components round half up, tax is truncated to the rupiah.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

ZERO = Decimal(0)
HUNDRED = Decimal(100)


def rp(v: Decimal) -> Decimal:
    return Decimal(v).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def tax_rp(v: Decimal) -> Decimal:
    return Decimal(v).quantize(Decimal(1), rounding=ROUND_DOWN)


def d(v: Any) -> Decimal:
    return Decimal(str(v)) if v is not None and v != "" else ZERO


def ter_rate(bands: Sequence[tuple[Decimal | None, Decimal]], gross: Decimal) -> Decimal:
    """Rate % of the first band whose upper bound is >= gross (bands sorted ascending)."""
    for upper, rate in bands:
        if upper is None or gross <= upper:
            return Decimal(rate)
    return Decimal(bands[-1][1]) if bands else ZERO


def overtime_factor_hours(daily_hours: Sequence[Decimal], first: Decimal, nxt: Decimal) -> Decimal:
    """PP 35/2021 workday overtime: first hour x first, following hours x nxt, per day."""
    total = ZERO
    for h in daily_hours:
        h = Decimal(h)
        if h <= 0:
            continue
        total += min(h, Decimal(1)) * first + max(h - 1, ZERO) * nxt
    return total


@dataclass(frozen=True)
class Bpjs:
    kes_er: Decimal
    kes_ee: Decimal
    jht_er: Decimal
    jht_ee: Decimal
    jp_er: Decimal
    jp_ee: Decimal
    jkk_er: Decimal
    jkm_er: Decimal

    @property
    def employer(self) -> Decimal:
        return self.kes_er + self.jht_er + self.jp_er + self.jkk_er + self.jkm_er

    @property
    def employee(self) -> Decimal:
        return self.kes_ee + self.jht_ee + self.jp_ee


def bpjs(wage: Decimal, cfg: dict[str, Any]) -> Bpjs:
    """Contributions on the monthly wage (basic + fixed allowances), each program with its
    own wage cap (None = uncapped)."""

    def part(program: str, side: str) -> Decimal:
        p = cfg.get(program) or {}
        base = Decimal(wage)
        if p.get("cap") not in (None, ""):
            base = min(base, d(p["cap"]))
        return rp(base * d(p.get(side)) / HUNDRED)

    return Bpjs(
        kes_er=part("kesehatan", "employer"),
        kes_ee=part("kesehatan", "employee"),
        jht_er=part("jht", "employer"),
        jht_ee=part("jht", "employee"),
        jp_er=part("jp", "employer"),
        jp_ee=part("jp", "employee"),
        jkk_er=part("jkk", "employer"),
        jkm_er=part("jkm", "employer"),
    )


def progressive(pkp: Decimal, brackets: Sequence[Sequence[Any]]) -> Decimal:
    """UU HPP art. 17 on annual PKP."""
    tax, lower = ZERO, ZERO
    for upper_raw, rate_raw in brackets:
        upper = None if upper_raw in (None, "") else d(upper_raw)
        top = pkp if upper is None else min(pkp, upper)
        if top > lower:
            tax += (top - lower) * d(rate_raw) / HUNDRED
        if upper is None or pkp <= upper:
            break
        lower = upper
    return tax_rp(tax)


@dataclass
class Annual:
    """December annual reconciliation (PPh 21 setahun, basis for 1721-A1)."""

    gross: Decimal
    position_cost: Decimal
    pension: Decimal
    net: Decimal
    ptkp: Decimal
    pkp: Decimal
    tax: Decimal
    withheld: Decimal
    december: Decimal
    months: int
    extra: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            k: (format(v, "f") if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()
        }


def annual(
    *,
    gross_year: Decimal,
    pension_year: Decimal,
    withheld_before: Decimal,
    months: int,
    ptkp: Decimal,
    rules: dict[str, Any],
    has_tax_id: bool,
) -> Annual:
    pct = d(rules.get("position_cost_pct", "5"))
    cap_year = d(rules.get("position_cost_max_year", "6000000"))
    cap = rp(cap_year * months / 12) if months < 12 else cap_year
    position = min(rp(gross_year * pct / HUNDRED), cap)
    net = gross_year - position - pension_year
    pkp = max(net - ptkp, ZERO)
    pkp = (pkp / 1000).quantize(Decimal(1), rounding=ROUND_DOWN) * 1000
    tax = progressive(pkp, rules.get("brackets") or [])
    if not has_tax_id:
        tax = tax_rp(tax * (HUNDRED + d(rules.get("no_npwp_surcharge_pct", "20"))) / HUNDRED)
    return Annual(
        gross=gross_year,
        position_cost=position,
        pension=pension_year,
        net=net,
        ptkp=ptkp,
        pkp=pkp,
        tax=tax,
        withheld=withheld_before,
        december=tax - withheld_before,
        months=months,
    )


def allocate(total: Decimal, weights: Sequence[int]) -> list[Decimal]:
    """Split a whole-rupiah total by weights; the remainder goes to the largest shares."""
    s = sum(weights)
    if s <= 0:
        return [ZERO for _ in weights]
    raw = [Decimal(total) * w / s for w in weights]
    out = [r.quantize(Decimal(1), rounding=ROUND_DOWN) for r in raw]
    left = int(Decimal(total) - sum(out))
    order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)
    for i in order[:left]:
        out[i] += 1
    return out
