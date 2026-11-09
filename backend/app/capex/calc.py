"""CAPEX business case (08): NPV, IRR, payback, buy vs rent vs lease, priority score.

Inputs per proposal:
  amount           investment (IDR)
  day_rate         expected revenue per operating day
  utilisation_pct  share of the 365 days the asset earns
  opex_pct         yearly owning cost (maintenance, certification, insurance) as % of amount
  life_years       economic life; salvage_pct of amount at the end
  rental_annual    what renting the same capability costs per year (default: actual rental
                   spend of the last 12 months, account 5400)
  lease_monthly    lease instalment (0 = no lease offer)
Cash flow year t (1..life) = revenue - opex (+ salvage in the last year); NPV at the discount
rate (setting capex.discount_rate, default 12 %). Payback is simple (investment / yearly CF).
Buy vs rent vs lease compares the present value of what each option costs over the life.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)
HUNDRED = Decimal(100)


def _rp(v: Decimal) -> Decimal:
    return v.quantize(Decimal(1), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CaseIn:
    amount: Decimal
    day_rate: Decimal
    utilisation_pct: Decimal
    opex_pct: Decimal
    life_years: int
    salvage_pct: Decimal = ZERO
    rental_annual: Decimal = ZERO
    lease_monthly: Decimal = ZERO
    discount_rate: Decimal = Decimal(12)
    strategic_fit: int = 3  # 1-5 (RJPP)
    risk: int = 3  # 1-5, 5 = lowest risk


@dataclass(frozen=True)
class CaseOut:
    revenue_annual: Decimal
    opex_annual: Decimal
    cash_flow_annual: Decimal
    npv: Decimal
    irr: Decimal | None
    payback_years: Decimal | None
    pv_buy: Decimal
    pv_rent: Decimal
    pv_lease: Decimal | None
    best_option: str
    priority_score: Decimal

    def as_dict(self) -> dict[str, str | None]:
        return {
            k: (None if v is None else format(v, "f") if isinstance(v, Decimal) else str(v))
            for k, v in self.__dict__.items()
        }


def flows(c: CaseIn) -> list[Decimal]:
    revenue = c.day_rate * 365 * c.utilisation_pct / HUNDRED
    opex = c.amount * c.opex_pct / HUNDRED
    out = [-c.amount]
    for t in range(1, c.life_years + 1):
        cf = revenue - opex
        if t == c.life_years:
            cf += c.amount * c.salvage_pct / HUNDRED
        out.append(cf)
    return out


def npv(rate_pct: Decimal, cash: list[Decimal]) -> Decimal:
    r = rate_pct / HUNDRED
    return sum((cf / (1 + r) ** t for t, cf in enumerate(cash)), ZERO)


def irr(cash: list[Decimal]) -> Decimal | None:
    """Rate % where NPV = 0 (bisection between -99 % and 1000 %); None if no sign change."""
    lo, hi = Decimal("-99"), Decimal("1000")
    f_lo, f_hi = npv(lo, cash), npv(hi, cash)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid, cash)
        if abs(f_mid) < Decimal("0.5") or hi - lo < Decimal("0.00001"):
            break
        if (f_lo < 0) == (f_mid < 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return ((lo + hi) / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pv_annuity(amount: Decimal, rate_pct: Decimal, years: int) -> Decimal:
    r = rate_pct / HUNDRED
    return sum((amount / (1 + r) ** t for t in range(1, years + 1)), ZERO)


def evaluate(c: CaseIn) -> CaseOut:
    cash = flows(c)
    revenue = _rp(c.day_rate * 365 * c.utilisation_pct / HUNDRED)
    opex = _rp(c.amount * c.opex_pct / HUNDRED)
    cf = revenue - opex
    payback = (c.amount / cf).quantize(Decimal("0.01")) if cf > 0 else None
    r = c.discount_rate / HUNDRED
    salvage_pv = c.amount * c.salvage_pct / HUNDRED / (1 + r) ** c.life_years
    pv_buy = _rp(c.amount + _pv_annuity(opex, c.discount_rate, c.life_years) - salvage_pv)
    pv_rent = _rp(_pv_annuity(c.rental_annual, c.discount_rate, c.life_years))
    pv_lease = (
        _rp(_pv_annuity(c.lease_monthly * 12 + opex, c.discount_rate, c.life_years))
        if c.lease_monthly > 0
        else None
    )
    options = {"buy": pv_buy, "rent": pv_rent if c.rental_annual > 0 else None, "lease": pv_lease}
    best = min((k for k, v in options.items() if v is not None), key=lambda k: options[k] or ZERO)
    rate = irr(cash)
    # Priority 0-100: strategic fit 25, return 25 (IRR vs 2x hurdle), utilisation 20,
    # payback within life 20, risk 10.
    ret = ZERO if rate is None else max(min(rate / (2 * c.discount_rate), Decimal(1)), ZERO)
    pay_part = max(Decimal(1) - payback / c.life_years, ZERO) if payback is not None else ZERO
    score = (
        Decimal(25) * Decimal(c.strategic_fit) / 5
        + Decimal(25) * ret
        + Decimal(20) * min(c.utilisation_pct, HUNDRED) / HUNDRED
        + Decimal(20) * pay_part
        + Decimal(10) * Decimal(c.risk) / 5
    ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return CaseOut(
        revenue_annual=revenue,
        opex_annual=opex,
        cash_flow_annual=cf,
        npv=_rp(npv(c.discount_rate, cash)),
        irr=rate,
        payback_years=payback,
        pv_buy=pv_buy,
        pv_rent=pv_rent,
        pv_lease=pv_lease,
        best_option=best,
        priority_score=score,
    )
