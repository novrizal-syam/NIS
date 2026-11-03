from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.contract.models import RATE_KINDS, Contract, ContractRate
from app.core.errors import AppError
from app.crm.models import Opportunity, Quotation, QuotationLine
from app.services import audit, numbering
from app.services.audit import AuditAction

KIND_BY_ELEMENT = {
    "EQUIP-OWN": "equipment",
    "EQUIP-RENT": "equipment",
    "MANPOWER": "personnel",
    "CONSUMABLE": "consumable",
}


def _rp(v: Decimal) -> Decimal:
    return v.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def rate_after_discount(unit_price: Decimal, discount_pct: Decimal) -> Decimal:
    """The contract rate is the quoted unit price less the quotation discount."""
    return _rp(unit_price * (100 - discount_pct) / 100)


def rates_from_quotation(q: Quotation, lines: list[QuotationLine]) -> list[ContractRate]:
    out = []
    for x in lines:
        kind = KIND_BY_ELEMENT.get(x.cost_element_code or "", "service")
        rate = rate_after_discount(x.unit_price, q.discount_pct)
        markup = None
        if kind == "consumable" and x.unit_cost > 0:
            markup = ((rate - x.unit_cost) / x.unit_cost * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        out.append(
            ContractRate(
                seq=x.seq,
                kind=kind,
                price_item_code=x.price_item_code,
                cost_element_code=x.cost_element_code,
                description=x.description,
                unit=x.unit,
                rate=rate,
                # Standby is agreed per contract (filled manually); breakdown pays nothing.
                standby_rate=None,
                breakdown_rate=Decimal(0) if kind == "equipment" else None,
                unit_cost=x.unit_cost if kind == "consumable" else None,
                markup_pct=markup,
                quoted_qty=x.qty,
            )
        )
    return out


def consumable_rate(unit_cost: Decimal, markup_pct: Decimal) -> Decimal:
    return _rp(unit_cost * (100 + markup_pct) / 100)


async def create_from_quotation(
    session: AsyncSession,
    actor: Principal,
    opp: Opportunity,
    q: Quotation,
    lines: list[QuotationLine],
    *,
    po_number: str | None,
    start_date: Any,
    end_date: Any,
    payment_term_days: int,
) -> Contract:
    contract = Contract(
        number=await numbering.next(session, "CTR"),
        opportunity_id=opp.id,
        quotation_id=q.id,
        client_code=opp.client_code,
        company_name=opp.company_name,
        title=opp.title,
        owner_id=opp.owner_id,
        value=q.total_price,
        po_number=po_number,
        start_date=start_date,
        end_date=end_date,
        payment_term_days=payment_term_days,
        status="active",
        created_by=actor.id,
        is_demo=opp.is_demo,
    )
    session.add(contract)
    await session.flush()
    rates = rates_from_quotation(q, lines)
    for r in rates:
        r.contract_id = contract.id
        session.add(r)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="contract",
        entity_id=contract.id,
        actor_id=actor.id,
        after={
            "number": contract.number,
            "opportunity": opp.number,
            "quotation": f"{q.number} Rev.{q.revision}",
            "value": contract.value,
            "rates": len(rates),
        },
    )
    return contract


async def rates_of(session: AsyncSession, contract_id: Any) -> list[ContractRate]:
    rows = await session.execute(
        select(ContractRate)
        .where(ContractRate.contract_id == contract_id)
        .order_by(ContractRate.seq)
    )
    return list(rows.scalars())


async def replace_rates(
    session: AsyncSession, actor: Principal, contract: Contract, rows: list[dict[str, Any]]
) -> list[ContractRate]:
    """Manual edit of the rate schedule (equipment status rates, personnel/day, consumables
    cost + markup, mob/demob lump sum)."""
    before = [_rate_dict(r) for r in await rates_of(session, contract.id)]
    await session.execute(delete(ContractRate).where(ContractRate.contract_id == contract.id))
    new = []
    for seq, r in enumerate(rows, start=1):
        if r["kind"] not in RATE_KINDS:
            raise AppError("RATE_KIND_INVALID", "Jenis tarif tidak dikenal.", status_code=422)
        rate = r["rate"]
        markup = r.get("markup_pct")
        unit_cost = r.get("unit_cost")
        if r["kind"] == "consumable":
            if unit_cost is None or markup is None:
                raise AppError(
                    "CONSUMABLE_COST_REQUIRED",
                    "Tarif bahan habis pakai butuh biaya satuan dan markup %.",
                    status_code=422,
                )
            rate = consumable_rate(unit_cost, markup)
        if rate is None or rate < 0:
            raise AppError("RATE_INVALID", "Tarif wajib diisi dan tidak negatif.", status_code=422)
        row = ContractRate(
            contract_id=contract.id,
            seq=seq,
            kind=r["kind"],
            price_item_code=r.get("price_item_code"),
            cost_element_code=r.get("cost_element_code"),
            description=r["description"],
            unit=r["unit"],
            rate=rate,
            standby_rate=r.get("standby_rate") if r["kind"] == "equipment" else None,
            breakdown_rate=(r.get("breakdown_rate") or Decimal(0))
            if r["kind"] == "equipment"
            else None,
            unit_cost=unit_cost if r["kind"] == "consumable" else None,
            markup_pct=markup if r["kind"] == "consumable" else None,
            quoted_qty=r.get("quoted_qty"),
        )
        session.add(row)
        new.append(row)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="contract",
        entity_id=contract.id,
        actor_id=actor.id,
        before={"rates": before},
        after={"rates": [_rate_dict(r) for r in new]},
    )
    return new


def _rate_dict(r: ContractRate) -> dict[str, Any]:
    return {
        "kind": r.kind,
        "description": r.description,
        "unit": r.unit,
        "rate": r.rate,
        "standby_rate": r.standby_rate,
        "breakdown_rate": r.breakdown_rate,
        "unit_cost": r.unit_cost,
        "markup_pct": r.markup_pct,
    }
