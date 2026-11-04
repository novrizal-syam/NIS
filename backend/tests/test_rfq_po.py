"""Phase 04b: RFQ (CSMS exclusion, scoring, award) and PO (budget movements, revisions)."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.master.models import Vendor
from app.procurement import rfq_service
from app.procurement.models import PriceHistory, RfqQuote
from app.services import budget_control as bc
from app.services.storage import Storage
from tests.test_pr import _locked, _pr, _submit

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
CAT = "equipment_rental"


@pytest.fixture
async def vendors(session: AsyncSession) -> None:
    rows = [
        ("V-A", "PT Alfa Sewa", "qualified", "4.0"),
        ("V-B", "PT Beta Rental", "qualified", "5.0"),
        ("V-C", "PT Citra Genset", "qualified", "3.0"),
        ("V-P", "PT Pending CSMS", "csms_pending", "4.5"),
        ("V-X", "PT Daftar Hitam", "blacklisted", "4.0"),
    ]
    session.add_all(
        Vendor(code=c, name=n, category=CAT, status=st, rating=Decimal(r)) for c, n, st, r in rows
    )
    await session.commit()


def test_scoring_formula() -> None:
    def q(code: str, total: int, days: int) -> RfqQuote:
        return RfqQuote(vendor_code=code, status="quoted", total=Decimal(total), delivery_days=days)

    w = {"price": Decimal(60), "delivery": Decimal(20), "rating": Decimal(20)}
    ranked = rfq_service.score(
        [
            (q("V-A", 40 * M, 10), Decimal(4)),
            (q("V-B", 36 * M, 20), Decimal(5)),
            (q("V-C", 38 * M, 5), Decimal(3)),
            (RfqQuote(vendor_code="V-D", status="declined"), Decimal(5)),
        ],
        w,
    )
    totals = {s.vendor_code: s.total for s in ranked}
    # A: 60*36/40 + 20*5/10 + 20*4/5 = 54 + 10 + 16
    assert totals == {"V-A": Decimal("80.00"), "V-B": Decimal("85.00"), "V-C": Decimal("88.84")}
    assert ranked[0].vendor_code == "V-C"
    b = next(s for s in ranked if s.vendor_code == "V-B")
    assert (b.price, b.delivery, b.rating) == (Decimal("60.00"), Decimal("5.00"), Decimal("20.00"))


async def _approved_pr(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sm: async_sessionmaker[AsyncSession],
    amount: int = 40 * M,
    budget: int = 200 * M,
) -> tuple[Any, dict[str, Any], dict[str, str]]:
    p = await _locked(sm, budget)
    eng = await login(await make_user("engineer"))
    hoo = await login(await make_user("head_of_operation"))
    pr = await _submit(client, eng, await _pr(client, eng, p, amount))
    r = await client.post(
        f"/api/workflow/requests/{pr['request_id']}/approve", json={}, headers=hoo
    )
    assert r.status_code == 200
    proc = await login(await make_user("procurement_officer"))
    return p, pr, proc


async def _rfq(client: AsyncClient, proc: dict[str, str], pr: dict[str, Any]) -> dict[str, Any]:
    r = await client.post(
        "/api/procurement/rfqs",
        json={"pr_id": pr["id"], "category": CAT, "vendor_codes": ["V-A", "V-B", "V-C"]},
        headers=proc,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _quote(
    client: AsyncClient, proc: dict[str, str], rfq: dict[str, Any], code: str, total: int, days: int
) -> dict[str, Any]:
    q = next(x for x in rfq["quotes"] if x["vendor_code"] == code)
    r = await client.put(
        f"/api/procurement/rfqs/{rfq['id']}/quotes/{q['id']}",
        json={
            "unit_prices": {"1": str(total)},
            "delivery_days": days,
            "payment_terms": "30 hari",
            "valid_until": "2026-12-31",
        },
        headers=proc,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_csms_exclusion_and_minimum_vendors(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    vendors: None,
) -> None:
    _, pr, proc = await _approved_pr(client, make_user, login, sessionmaker)
    listing = (
        await client.get("/api/procurement/rfq-vendors", params={"category": CAT}, headers=proc)
    ).json()
    excluded = {v["code"]: v["excluded"] for v in listing}
    assert excluded["V-P"] == "CSMS belum disetujui" and excluded["V-X"] == "masuk daftar hitam"
    assert excluded["V-A"] is None

    for codes in (["V-A", "V-B", "V-P"], ["V-A", "V-B", "V-X"]):
        r = await client.post(
            "/api/procurement/rfqs",
            json={"pr_id": pr["id"], "category": CAT, "vendor_codes": codes},
            headers=proc,
        )
        assert r.status_code == 422 and r.json()["code"] == "VENDOR_NOT_SELECTABLE"
    r = await client.post(
        "/api/procurement/rfqs",
        json={"pr_id": pr["id"], "category": CAT, "vendor_codes": ["V-A", "V-B"]},
        headers=proc,
    )
    assert r.status_code == 422 and r.json()["code"] == "MIN_VENDORS"
    rfq = await _rfq(client, proc, pr)
    assert rfq["number"].startswith("RFQ-") and len(rfq["quotes"]) == 3


async def test_scoring_award_and_non_best_reason(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    vendors: None,
) -> None:
    _, pr, proc = await _approved_pr(client, make_user, login, sessionmaker)
    rfq = await _rfq(client, proc, pr)
    await _quote(client, proc, rfq, "V-A", 40 * M, 10)
    await _quote(client, proc, rfq, "V-B", 36 * M, 20)
    rfq = await _quote(client, proc, rfq, "V-C", 38 * M, 5)
    assert rfq["best_vendor_code"] == "V-C"
    assert {q["vendor_code"]: q["score"]["total"] for q in rfq["quotes"]} == {
        "V-A": "80.00",
        "V-B": "85.00",
        "V-C": "88.84",
    }

    url = f"/api/procurement/rfqs/{rfq['id']}/award"
    r = await client.post(url, json={"vendor_code": "V-B"}, headers=proc)
    assert r.status_code == 422 and r.json()["code"] == "AWARD_REASON_REQUIRED"
    r = await client.post(
        url, json={"vendor_code": "V-B", "reason": "Harga terendah, unit lebih baru"}, headers=proc
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "award_pending"
        and r.json()["approval_needed"]
    )
    req = (
        await client.get(f"/api/workflow/requests/{r.json()['request_id']}", headers=proc)
    ).json()
    assert [s["approver_role"] for s in req["steps"]] == ["head_of_finance"]
    assert (
        await client.post(f"/api/procurement/rfqs/{rfq['id']}/po", headers=proc)
    ).status_code == 409
    hof = await login(await make_user("head_of_finance"))
    assert (
        await client.post(
            f"/api/workflow/requests/{r.json()['request_id']}/approve", json={}, headers=hof
        )
    ).status_code == 200
    d = (await client.get(f"/api/procurement/rfqs/{rfq['id']}", headers=proc)).json()
    assert d["status"] == "awarded" and d["awarded_vendor_code"] == "V-B"
    history = (await session.execute(select(func.count()).select_from(PriceHistory))).scalar_one()
    assert history == 3  # one quoted line per vendor
    ph = (
        await client.get("/api/procurement/price-history", params={"q": "genset"}, headers=proc)
    ).json()
    assert {h["vendor_code"] for h in ph} == {"V-A", "V-B", "V-C"}


async def test_po_budget_movements(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    vendors: None,
    storage: Storage,
) -> None:
    p, pr, proc = await _approved_pr(client, make_user, login, sessionmaker)
    rfq = await _rfq(client, proc, pr)
    for code, total, days in (("V-A", 40 * M, 10), ("V-B", 36 * M, 20), ("V-C", 38 * M, 5)):
        rfq = await _quote(client, proc, rfq, code, total, days)
    r = await client.post(
        f"/api/procurement/rfqs/{rfq['id']}/award", json={"vendor_code": "V-C"}, headers=proc
    )
    assert (
        r.status_code == 200 and r.json()["status"] == "awarded" and not r.json()["approval_needed"]
    )
    po = (await client.post(f"/api/procurement/rfqs/{rfq['id']}/po", headers=proc)).json()
    assert po["number"].startswith("PO-") and po["status"] == "draft"
    assert (po["subtotal"], po["ppn_amount"], po["total"]) == ("38000000", "4180000", "42180000")
    assert "denda" in po["terms"]

    async with sessionmaker() as s:
        line = await bc.resolve(s, p.id, "EXEC", "EQUIP-RENT")
        before = await bc.available(s, line)
    assert (before.pre_commit, before.available) == (Decimal(40 * M), Decimal(160 * M))

    r = await client.post(f"/api/procurement/pos/{po['id']}/issue", headers=proc)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "issued" and r.json()["budget"]["commit_by_po"] == "38000000"
    async with sessionmaker() as s:
        after = await bc.available(s, line)
    # PR pre-commitment (40 M) released; PO commits 38 M (DPP, PPN is not budget); 2 M saved.
    assert (after.pre_commit, after.commit, after.available) == (
        Decimal(0),
        Decimal(38 * M),
        Decimal(162 * M),
    )
    prd = (await client.get(f"/api/procurement/prs/{pr['id']}", headers=proc)).json()
    assert prd["status"] == "ordered"
    files = (
        await client.get(
            "/api/attachments",
            params={"entity_type": "purchase_order", "entity_id": po["id"]},
            headers=proc,
        )
    ).json()
    assert [f["filename"] for f in files] == [f"{po['number']}.pdf"]
    again = await client.post(f"/api/procurement/pos/{po['id']}/issue", headers=proc)
    assert again.status_code == 409


async def test_revision_rule(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    vendors: None,
    storage: Storage,
) -> None:
    _, pr, proc = await _approved_pr(client, make_user, login, sessionmaker, budget=60 * M)
    rfq = await _rfq(client, proc, pr)
    for code, total, days in (("V-A", 40 * M, 10), ("V-B", 36 * M, 20), ("V-C", 38 * M, 5)):
        rfq = await _quote(client, proc, rfq, code, total, days)
    await client.post(
        f"/api/procurement/rfqs/{rfq['id']}/award", json={"vendor_code": "V-C"}, headers=proc
    )
    po = (await client.post(f"/api/procurement/rfqs/{rfq['id']}/po", headers=proc)).json()
    po = (await client.post(f"/api/procurement/pos/{po['id']}/issue", headers=proc)).json()
    line = po["lines"][0]

    def body(price: int) -> dict[str, Any]:
        return {
            "lines": [{**line, "unit_price": str(price)}],
            "reason": "Negosiasi ulang harga sewa",
        }

    url = f"/api/procurement/pos/{po['id']}/revise"
    # Lower: applied at once, savings released.
    r = await client.post(url, json=body(35 * M), headers=proc)
    assert r.status_code == 200 and not r.json()["approval_needed"]
    assert r.json()["revision"] == 1 and r.json()["budget"]["commit_by_po"] == "35000000"
    # Higher than available (60 - 35 = 25 M free; +30 M asked) -> blocked.
    r = await client.post(url, json=body(65 * M), headers=proc)
    assert r.status_code == 409 and r.json()["code"] == "BUDGET_EXCEEDED"
    # Higher within budget: re-approval (DOA po_revision on the new value, <= 50 jt -> HoO).
    r = await client.post(url, json=body(45 * M), headers=proc)
    assert (
        r.status_code == 200
        and r.json()["approval_needed"]
        and r.json()["status"] == "revision_pending"
    )
    assert r.json()["budget"]["commit_by_po"] == "35000000"  # nothing moves before approval
    req = (
        await client.get(f"/api/workflow/requests/{r.json()['request_id']}", headers=proc)
    ).json()
    assert [s["approver_role"] for s in req["steps"]] == ["head_of_operation"]
    hoo = await login(await make_user("head_of_operation"))
    assert (
        await client.post(
            f"/api/workflow/requests/{r.json()['request_id']}/approve", json={}, headers=hoo
        )
    ).status_code == 200
    d = (await client.get(f"/api/procurement/pos/{po['id']}", headers=proc)).json()
    assert d["status"] == "issued" and d["revision"] == 2
    assert (d["subtotal"], d["budget"]["commit_by_po"]) == ("45000000", "45000000")
    files = (
        await client.get(
            "/api/attachments",
            params={"entity_type": "purchase_order", "entity_id": po["id"]},
            headers=proc,
        )
    ).json()
    assert {f["filename"] for f in files} == {
        f"{po['number']}.pdf",
        f"{po['number']}-Rev1.pdf",
        f"{po['number']}-Rev2.pdf",
    }
