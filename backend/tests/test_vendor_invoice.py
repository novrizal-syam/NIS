"""Phase 04d: vendor invoice, 3-way match, taxes, journal, payables gate, aging, statement."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.core.errors import AppError
from app.finance import ap_service as ap
from app.finance.models import VendorInvoice
from app.master.models import Vendor
from app.procurement.models import PurchaseOrder
from app.services.numbering import today_jakarta
from app.services.storage import Storage
from app.setup import service as settings_store
from tests.test_inventory import _issued_po, _project, _upload, masters  # noqa: F401

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF"


async def _received_po(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sm: async_sessionmaker[AsyncSession],
    received: int = 4,
) -> tuple[PurchaseOrder, dict[str, str]]:
    """Service PO 10 days x Rp 2 jt, `received` days received (GR posted)."""
    owner = await make_user("lead_engineer")
    p = await _project(sm, manager=owner)
    po = await _issued_po(sm, p, "EQUIP-RENT", [(None, "Sewa genset (hari)", 10, 2 * M)])
    pm = await login(owner)
    r = await client.post(
        "/api/inventory/grs",
        json={
            "po_id": str(po.id),
            "received_date": today_jakarta().isoformat(),
            "lines": [{"seq": 1, "qty": str(received)}],
        },
        headers=pm,
    )
    gr = r.json()
    await _upload(client, pm, gr["id"])
    assert (await client.post(f"/api/inventory/grs/{gr['id']}/post", headers=pm)).status_code == 200
    return po, await login(await make_user("ap_accountant"))


def _body(po: PurchaseOrder, qty: str, price: int, dpp: int, **kw: Any) -> dict[str, Any]:
    return {
        "po_id": str(po.id),
        "invoice_no": kw.pop("invoice_no", "INV/ALFA/0012"),
        "tax_invoice_no": "010.000-26.00000012",
        "invoice_date": today_jakarta().isoformat(),
        "kind": "service",
        "dpp": str(dpp),
        "lines": [{"seq": 1, "qty": qty, "unit_price": str(price)}],
        **kw,
    }


async def _attach(client: AsyncClient, h: dict[str, str], vid: str) -> None:
    r = await client.post(
        "/api/attachments",
        data={"entity_type": "vendor_invoice", "entity_id": vid, "note": "Invoice + faktur"},
        files={"file": ("invoice.pdf", PDF, "application/pdf")},
        headers=h,
    )
    assert r.status_code == 201, r.text


async def test_tax_amounts(session: AsyncSession, masters: None) -> None:  # noqa: F811
    v = Vendor(code="V-N", name="PT Ber-NPWP", category="x", npwp="01.234.567.8-901.000")
    nonpwp = Vendor(code="V-0", name="CV Tanpa NPWP", category="x")
    # PPN 12% x 11/12 = 11% of DPP; PPh 23 2% on services, doubled without NPWP; none on goods.
    assert await ap.taxes(session, v, "service", D(10 * M), None) == (
        D(1_100_000),
        D(2),
        D(200_000),
    )
    assert await ap.taxes(session, nonpwp, "service", D(10 * M), None) == (
        D(1_100_000),
        D(4),
        D(400_000),
    )
    assert await ap.taxes(session, v, "goods", D(10 * M), None) == (D(1_100_000), D(0), D(0))
    # As stated on the faktur.
    assert (await ap.taxes(session, v, "goods", D(10 * M), D(1_200_000)))[0] == D(1_200_000)


async def test_match_posts_balanced_journal_and_is_payable(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    async with sessionmaker() as s:
        await s.execute(
            update(Vendor).where(Vendor.code == "V-A").values(npwp="01.234.567.8-901.000")
        )
        await s.commit()
    po, apa = await _received_po(client, make_user, login, sessionmaker)
    pre = (await client.get(f"/api/finance/vendor-invoices/prefill/{po.id}", headers=apa)).json()
    assert pre["lines"][0]["open"] == "4" and pre["kind"] == "service"

    r = await client.post(
        "/api/finance/vendor-invoices", json=_body(po, "4", 2 * M, 8 * M), headers=apa
    )
    assert r.status_code == 201, r.text
    vi = r.json()
    assert (vi["ppn"], vi["pph23_pct"], vi["pph23"], vi["payable"]) == (
        "880000",
        "2",
        "160000",
        "8720000",
    )
    dup = await client.post(
        "/api/finance/vendor-invoices", json=_body(po, "4", 2 * M, 8 * M), headers=apa
    )
    assert dup.status_code == 409 and dup.json()["code"] == "DUPLICATE_INVOICE"

    r = await client.post(f"/api/finance/vendor-invoices/{vi['id']}/match", headers=apa)
    assert r.status_code == 422 and r.json()["code"] == "ATTACHMENT_REQUIRED"
    await _attach(client, apa, vi["id"])
    r = await client.post(f"/api/finance/vendor-invoices/{vi['id']}/match", headers=apa)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "approved"
    assert done["due_date"] == (today_jakarta() + timedelta(days=30)).isoformat()
    lines = [(x["account_code"], x["debit"], x["credit"]) for x in done["journal"]["lines"]]
    assert lines == [
        ("2120", "8000000", "0"),
        ("1420", "880000", "0"),
        ("2110", "0", "8720000"),
        ("2230", "0", "160000"),
    ]
    assert sum(D(x[1]) for x in lines) == sum(D(x[2]) for x in lines)

    payables = (await client.get("/api/finance/payables", headers=apa)).json()
    assert [p["number"] for p in payables] == [done["number"]]
    aging = (await client.get("/api/finance/ap-aging", headers=apa)).json()
    assert aging["totals"]["not_due"] == "8720000"
    st = (
        await client.get(
            "/api/finance/vendor-statement",
            params={
                "vendor": "V-A",
                "date_from": today_jakarta().replace(day=1).isoformat(),
                "date_to": today_jakarta().isoformat(),
            },
            headers=apa,
        )
    ).json()
    assert st["opening"] == "0" and st["closing"] == "8720000"
    assert st["rows"][0]["document"] == done["number"]

    # The 4 received days are now fully invoiced: a second invoice is an exception.
    r = await client.post(
        "/api/finance/vendor-invoices",
        json=_body(po, "1", 2 * M, 2 * M, invoice_no="INV/ALFA/0013"),
        headers=apa,
    )
    second = r.json()
    await _attach(client, apa, second["id"])
    r = await client.post(f"/api/finance/vendor-invoices/{second['id']}/match", headers=apa)
    assert r.json()["status"] == "exception"


async def test_exception_is_not_payable_and_credit_note_resolves(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    po, apa = await _received_po(client, make_user, login, sessionmaker)
    # 6 days billed (4 received) at a higher price than the PO.
    r = await client.post(
        "/api/finance/vendor-invoices",
        json=_body(po, "6", 2_100_000, 12_600_000),
        headers=apa,
    )
    vi = r.json()
    await _attach(client, apa, vi["id"])
    r = await client.post(f"/api/finance/vendor-invoices/{vi['id']}/match", headers=apa)
    ex = r.json()
    assert ex["status"] == "exception" and ex["journal"] is None
    assert "diterima belum ditagih 4" in ex["exception_reason"]
    assert "harga PO" in ex["exception_reason"]
    row = ex["match_result"][0]
    assert (row["qty_ok"], row["price_ok"]) == (False, False)

    # Not payable: never listed for a payment run and refused by the gate.
    assert (await client.get("/api/finance/payables", headers=apa)).json() == []
    async with sessionmaker() as s:
        model = await s.get(VendorInvoice, ex["id"])
        assert model is not None
        with pytest.raises(AppError) as exc:
            ap.ensure_payable(model)
        assert exc.value.code == "NOT_PAYABLE"

    # Vendor credit note: DPP 12,6 jt -> 8 jt, PPN 1.386.000 -> 880.000; lines corrected.
    r = await client.post(
        f"/api/finance/vendor-invoices/{vi['id']}/credit-note",
        json={
            "credit_note_no": "CN/ALFA/0001",
            "note_date": today_jakarta().isoformat(),
            "dpp": "4600000",
            "ppn": "506000",
            "reason": "Kelebihan tagih 2 hari dan selisih harga",
            "lines": [{"seq": 1, "qty": "4", "unit_price": str(2 * M)}],
        },
        headers=apa,
    )
    assert r.status_code == 200, r.text
    fixed = r.json()
    assert (fixed["status"], fixed["dpp"], fixed["ppn"]) == ("draft", "8000000", "880000")
    assert fixed["credit_notes"][0]["credit_note_no"] == "CN/ALFA/0001"
    r = await client.post(f"/api/finance/vendor-invoices/{vi['id']}/match", headers=apa)
    assert r.json()["status"] == "approved"
    assert len((await client.get("/api/finance/payables", headers=apa)).json()) == 1


async def test_price_within_tolerance_posts_variance(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    async with sessionmaker() as s:
        await settings_store.put(s, ap.TOLERANCE_KEY, 5, None)
        await s.commit()
    po, apa = await _received_po(client, make_user, login, sessionmaker)
    r = await client.post(
        "/api/finance/vendor-invoices",
        json=_body(po, "4", 2_050_000, 8_200_000, ppn="902000"),
        headers=apa,
    )
    vi = r.json()
    await _attach(client, apa, vi["id"])
    done = (await client.post(f"/api/finance/vendor-invoices/{vi['id']}/match", headers=apa)).json()
    assert done["status"] == "approved"
    lines = [(x["account_code"], x["debit"], x["credit"]) for x in done["journal"]["lines"]]
    # GR/IR cleared at the GR value; the 200.000 price difference goes to the rental expense.
    assert lines[:3] == [
        ("2120", "8000000", "0"),
        ("5400", "200000", "0"),
        ("1420", "902000", "0"),
    ]
    assert sum(D(x[1]) for x in lines) == sum(D(x[2]) for x in lines)
