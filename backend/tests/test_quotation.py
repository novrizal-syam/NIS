"""Phase 02b: quotation totals and margin, DOA routing at 25 %, revisions, sending."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.errors import AppError
from app.crm import quotation_service as svc
from app.crm import service as crm
from app.letters.models import OutgoingLetter
from app.master.models import PriceItem
from app.services import email
from app.services.email_log import EmailLog
from app.services.storage import Storage

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


def line(qty: str, cost: int, price: int, code: str | None = None) -> svc.LineIn:
    return svc.LineIn(code, "Jasa", "hari", Decimal(qty), Decimal(cost), Decimal(price))


# ---------------------------------------------------------------- margin calculation


def test_margin_with_discount() -> None:
    t = svc.compute(
        [line("10", 9_500_000, 14_000_000), line("2.5", 1_800_000, 3_000_000)],
        Decimal("10"),
    )
    assert [x.line_price for x in t.lines] == [Decimal(140_000_000), Decimal(7_500_000)]
    assert t.subtotal == Decimal(147_500_000)
    assert t.discount_amount == Decimal(14_750_000)
    assert t.total_price == Decimal(132_750_000)
    assert t.total_cost == Decimal(95_000_000 + 4_500_000)
    assert t.margin == Decimal(33_250_000)
    # 33,250,000 / 132,750,000 = 25.047 % -> 25.05
    assert t.margin_pct == Decimal("25.05")


def test_rounding_and_edge_cases() -> None:
    # Half-rupiah rounds up on each line; discount rounds to whole rupiah.
    t = svc.compute([line("0.5", 1, 3)], Decimal("33.33"))
    assert t.lines[0].line_price == Decimal(2) and t.lines[0].line_cost == Decimal(1)
    assert t.discount_amount == Decimal(1) and t.total_price == Decimal(1)
    empty = svc.compute([], Decimal(0))
    assert empty.total_price == 0 and empty.margin_pct == Decimal("0.00")
    loss = svc.compute([line("1", 120, 100)], Decimal(0))
    assert loss.margin == Decimal(-20) and loss.margin_pct == Decimal("-20.00")
    with pytest.raises(AppError):
        svc.compute([line("1", 1, 1)], Decimal("101"))


# ---------------------------------------------------------------- API helpers


@pytest.fixture
async def prices(session: AsyncSession) -> None:
    session.add_all(
        [
            PriceItem(
                code="SRV-PUMP",
                name="Pump unit (operating)",
                unit="hari",
                unit_cost=Decimal(9_500_000),
                unit_price=Decimal(14_000_000),
                cost_element_code="EQUIP-OWN",
            ),
            PriceItem(
                code="SRV-FE",
                name="Field engineer",
                unit="hari",
                unit_cost=Decimal(1_800_000),
                unit_price=Decimal(3_000_000),
                cost_element_code="MANPOWER",
            ),
        ]
    )
    await session.commit()


async def _opportunity_in_quotation(
    client: AsyncClient, ae: dict[str, str], director: dict[str, str]
) -> dict[str, Any]:
    lead = (
        await client.post(
            "/api/crm/leads",
            json={
                "company_name": "PT Migas Hulu Contoh",
                "contact_name": "Bapak Andi",
                "contact_email": "andi@klien.co.id",
                "source": "invitation",
                "need": "Well testing 3 sumur",
            },
            headers=ae,
        )
    ).json()
    url = f"/api/crm/leads/{lead['id']}"
    await client.patch(
        url,
        json={"qualification": dict.fromkeys(crm.QUALIFICATION, True)},
        headers=ae,
    )
    await client.post(f"{url}/status", json={"to": "contacted"}, headers=ae)
    await client.post(f"{url}/status", json={"to": "qualified"}, headers=ae)
    opp = (
        await client.post(f"{url}/convert", json={"title": "Well testing Blok X"}, headers=ae)
    ).json()
    rid = (
        await client.post(
            f"/api/crm/opportunities/{opp['id']}/bid-decision",
            json={"scores": dict.fromkeys(crm.SCORES, 5), "proposal": "bid"},
            headers=ae,
        )
    ).json()["request_id"]
    r = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=director)
    assert r.status_code == 200
    return opp


def _lines(pump_price: int = 14_000_000) -> list[dict[str, Any]]:
    return [
        {
            "price_item_code": "SRV-PUMP",
            "description": "Pump unit (operating)",
            "unit": "hari",
            "qty": "10",
            "unit_cost": "9500000",
            "unit_price": str(pump_price),
        },
        {
            "price_item_code": "SRV-FE",
            "description": "Field engineer",
            "unit": "hari",
            "qty": "2.5",
            "unit_cost": "1800000",
            "unit_price": "3000000",
        },
    ]


async def _draft(
    client: AsyncClient, ae: dict[str, str], opp: dict[str, Any], discount: str, **kw: Any
) -> dict[str, Any]:
    q = (
        await client.post("/api/quotations", json={"opportunity_id": opp["id"]}, headers=ae)
    ).json()
    r = await client.put(
        f"/api/quotations/{q['id']}",
        json={"discount_pct": discount, "lines": _lines(**kw), "valid_until": "2026-12-31"},
        headers=ae,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- API


async def test_quotation_needs_approved_bid(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    lead = (
        await client.post(
            "/api/crm/leads",
            json={"company_name": "PT A", "source": "visit", "need": "Pumping unit"},
            headers=ae,
        )
    ).json()
    url = f"/api/crm/leads/{lead['id']}"
    await client.patch(
        url, json={"qualification": dict.fromkeys(crm.QUALIFICATION, True)}, headers=ae
    )
    await client.post(f"{url}/status", json={"to": "contacted"}, headers=ae)
    await client.post(f"{url}/status", json={"to": "qualified"}, headers=ae)
    opp = (await client.post(f"{url}/convert", json={"title": "Pumping"}, headers=ae)).json()
    r = await client.post("/api/quotations", json={"opportunity_id": opp["id"]}, headers=ae)
    assert r.status_code == 409 and r.json()["code"] == "OPPORTUNITY_NOT_IN_QUOTATION"


async def test_totals_computed_in_backend_and_low_margin_warning(
    client: AsyncClient, make_user: MakeUser, login: Login, prices: None
) -> None:
    ae = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))
    opp = await _opportunity_in_quotation(client, ae, director)
    q = await _draft(client, ae, opp, "10")
    assert q["number"].startswith("QT-") and q["revision"] == 0 and q["label"].endswith("Rev.0")
    assert q["subtotal"] == "147500000" and q["discount_amount"] == "14750000"
    assert q["total_price"] == "132750000" and q["total_cost"] == "99500000"
    assert q["margin_pct"] == "25.05" and q["margin_warning"] is False
    assert [x["line_price"] for x in q["lines"]] == ["140000000", "7500000"]

    # Discount 25 % -> margin below 20 % -> warning.
    r = await client.put(
        f"/api/quotations/{q['id']}", json={"discount_pct": "25", "lines": _lines()}, headers=ae
    )
    assert r.json()["margin_pct"] == "10.06" and r.json()["margin_warning"] is True

    bad = await client.put(
        f"/api/quotations/{q['id']}",
        json={"lines": [{**_lines()[0], "price_item_code": "NOPE"}]},
        headers=ae,
    )
    assert bad.status_code == 422 and bad.json()["code"] == "PRICE_ITEM_INVALID"
    assert (await client.get("/api/quotations/price-items", headers=ae)).json()[0][
        "code"
    ] == "SRV-FE"


@pytest.mark.parametrize(
    ("discount", "margin", "approver", "other"),
    [
        # 25.05 % -> Head of Sales
        ("10", "25.05", "head_of_sales", "director"),
        # margin rounds to exactly 25.00 %: still Head of Sales (>= 25)
        ("10.06", "25.00", "head_of_sales", "director"),
        # 24.99 % -> Director
        ("10.07", "24.99", "director", "head_of_sales"),
    ],
)
async def test_doa_routing_at_25_percent(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    prices: None,
    discount: str,
    margin: str,
    approver: str,
    other: str,
) -> None:
    ae = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))
    hos = await login(await make_user("head_of_sales"))
    users = {"director": director, "head_of_sales": hos}
    opp = await _opportunity_in_quotation(client, ae, director)
    q = await _draft(client, ae, opp, discount)
    assert q["margin_pct"] == margin
    r = await client.post(f"/api/quotations/{q['id']}/submit", headers=ae)
    assert r.status_code == 200, r.text
    assert r.json()["approver"] == approver and r.json()["status"] == "submitted"
    rid = r.json()["request_id"]

    # Locked while submitted.
    locked = await client.put(f"/api/quotations/{q['id']}", json={"lines": _lines()}, headers=ae)
    assert locked.status_code == 409 and locked.json()["code"] == "QUOTATION_LOCKED"

    wrong = await client.post(
        f"/api/workflow/requests/{rid}/approve", json={}, headers=users[other]
    )
    assert wrong.status_code == 403
    own = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=ae)
    assert own.status_code == 403
    ok = await client.post(
        f"/api/workflow/requests/{rid}/approve", json={}, headers=users[approver]
    )
    assert ok.status_code == 200
    assert (await client.get(f"/api/quotations/{q['id']}", headers=ae)).json()[
        "status"
    ] == "approved"


async def test_revision_history(
    client: AsyncClient, make_user: MakeUser, login: Login, prices: None
) -> None:
    ae = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))
    hos = await login(await make_user("head_of_sales"))
    opp = await _opportunity_in_quotation(client, ae, director)
    q0 = await _draft(client, ae, opp, "0")
    # A second quotation for the same opportunity is a revision, not a new number.
    dup = await client.post("/api/quotations", json={"opportunity_id": opp["id"]}, headers=ae)
    assert dup.status_code == 409 and dup.json()["code"] == "QUOTATION_EXISTS"
    # Drafts are edited directly, not revised.
    r = await client.post(f"/api/quotations/{q0['id']}/revise", json={"reason": "ubah"}, headers=ae)
    assert r.status_code == 409

    rid = (await client.post(f"/api/quotations/{q0['id']}/submit", headers=ae)).json()["request_id"]
    await client.post(
        f"/api/workflow/requests/{rid}/reject",
        json={"comment": "Harga pump terlalu tinggi"},
        headers=hos,
    )
    rejected = (await client.get(f"/api/quotations/{q0['id']}", headers=ae)).json()
    assert (
        rejected["status"] == "rejected"
        and rejected["decision_comment"] == "Harga pump terlalu tinggi"
    )

    short = await client.post(
        f"/api/quotations/{q0['id']}/revise", json={"reason": "x"}, headers=ae
    )
    assert short.status_code == 422
    r1 = await client.post(
        f"/api/quotations/{q0['id']}/revise", json={"reason": "Turunkan harga pump"}, headers=ae
    )
    assert r1.status_code == 201
    q1 = r1.json()
    assert q1["number"] == q0["number"] and q1["revision"] == 1 and q1["status"] == "draft"
    assert len(q1["lines"]) == 2 and q1["total_price"] == q0["total_price"]
    r = await client.put(
        f"/api/quotations/{q1['id']}", json={"lines": _lines(pump_price=13_000_000)}, headers=ae
    )
    assert r.json()["total_price"] == "137500000"

    # Rev.0 is history: unchanged and read-only.
    old = (await client.get(f"/api/quotations/{q0['id']}", headers=ae)).json()
    assert old["status"] == "superseded" and old["total_price"] == "147500000"
    assert old["is_latest"] is False and old["can_revise"] is False
    assert [x["revision"] for x in old["revisions"]] == [1, 0]
    assert old["revisions"][0]["reason"] == "Turunkan harga pump"
    edit_old = await client.put(f"/api/quotations/{q0['id']}", json={"lines": []}, headers=ae)
    assert edit_old.status_code == 409

    listing = (await client.get("/api/quotations", headers=ae)).json()
    assert [i["label"] for i in listing["items"]] == [f"{q0['number']} Rev.1"]
    history = (await client.get(f"/api/audit/history/quotation/{q0['id']}", headers=ae)).json()
    assert "status_change" in [e["action"] for e in history["items"]]


async def test_send_to_client(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    prices: None,
    storage: Storage,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []
    monkeypatch.setattr(email, "provider", lambda: "smtp")
    monkeypatch.setattr(email, "_smtp_send", sent.append)
    ae = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))
    hos = await login(await make_user("head_of_sales"))
    opp = await _opportunity_in_quotation(client, ae, director)
    q = await _draft(client, ae, opp, "0")

    early = await client.post(f"/api/quotations/{q['id']}/send", json={}, headers=ae)
    assert early.status_code == 409 and early.json()["code"] == "NOT_APPROVED"
    preview = await client.get(f"/api/quotations/{q['id']}/pdf", headers=ae)
    assert preview.status_code == 200 and preview.content.startswith(b"%PDF")

    rid = (await client.post(f"/api/quotations/{q['id']}/submit", headers=ae)).json()["request_id"]
    await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=hos)
    r = await client.post(
        f"/api/quotations/{q['id']}/send",
        json={"send_email": True, "message": "Terlampir penawaran kami."},
        headers=ae,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "sent" and body["email_status"] == "queued"
    assert body["letter_number"].startswith("001/GEK-SLS/") and body["letter"]["file_id"]
    assert body["opportunity_stage"] == "submitted"
    assert body["sent_to_email"] == "andi@klien.co.id"

    letter = (await session.execute(select(OutgoingLetter))).scalar_one()
    assert letter.entity_type == "quotation" and letter.subject.startswith("Penawaran Harga")
    files = await client.get(
        "/api/attachments",
        params={"entity_type": "quotation", "entity_id": q["id"]},
        headers=ae,
    )
    assert [f["filename"] for f in files.json()] == [f"Penawaran-{q['number']}-Rev0.pdf"]
    stored = await client.get(f"/api/quotations/{q['id']}/pdf", headers=ae)
    assert stored.content.startswith(b"%PDF")

    # Email with the PDF attached, logged without content.
    assert len(sent) == 1
    msg = sent[0]
    assert msg["To"] == "andi@klien.co.id"
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == [f"Penawaran-{q['number']}-Rev0.pdf"]
    log = (await session.execute(select(EmailLog))).scalar_one()
    assert log.kind == "quotation" and log.status == "sent"

    detail = (await client.get(f"/api/crm/opportunities/{opp['id']}", headers=ae)).json()
    assert detail["stage"] == "submitted" and detail["value"] == q["total_price"]

    again = await client.post(f"/api/quotations/{q['id']}/send", json={}, headers=ae)
    assert again.status_code == 409


async def test_quotation_scope(
    client: AsyncClient, make_user: MakeUser, login: Login, prices: None
) -> None:
    ae = await login(await make_user("account_executive"))
    other = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))
    tender = await login(await make_user("tender_specialist"))
    opp = await _opportunity_in_quotation(client, ae, director)
    q = await _draft(client, ae, opp, "0")
    assert (await client.get(f"/api/quotations/{q['id']}", headers=other)).status_code == 404
    assert (await client.get("/api/quotations", headers=other)).json()["total"] == 0
    # Tender specialist reads all quotations but cannot change them.
    assert (await client.get(f"/api/quotations/{q['id']}", headers=tender)).status_code == 200
    r = await client.put(f"/api/quotations/{q['id']}", json={"lines": []}, headers=tender)
    assert r.status_code == 403
    export = await client.get("/api/quotations/export", headers=director)
    assert export.status_code == 200 and export.content[:2] == b"PK"
