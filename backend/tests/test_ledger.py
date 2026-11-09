"""Phase 07a: posting rules, closed periods, manual journals, opening balance, realised FX,
financial reports; trial balance zero after the full scenario."""

import io
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.billing import receipt_service
from app.billing.models import CustomerInvoice
from app.core.errors import AppError
from app.finance.models import JournalEntry, JournalLine
from app.master.models import Asset, Client, FiscalPeriod, FxRate
from app.services import ledger, posting_rules
from app.services.numbering import today_jakarta
from app.services.storage import Storage
from tests.test_billing import _png, _ticketed
from tests.test_inventory import masters  # noqa: F401

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal


@pytest.mark.parametrize("event", sorted(posting_rules.RULES))
async def test_every_posting_rule_is_balanced(
    sessionmaker: async_sessionmaker[AsyncSession], event: str
) -> None:
    rule = posting_rules.RULES[event]
    async with sessionmaker() as s:
        entry = await ledger.post_event(
            s,
            event,
            rule.example,
            entry_date=today_jakarta(),
            description=f"uji {event}",
            source_type="test",
            source_id=event,
            by=None,
            dims=ledger.Dims(cost_element="CONSUMABLE", partner_type="client", partner_code="X"),
        )
        lines = await ledger.lines_of(s, entry.id)
        assert entry.event == event
        assert sum(x.debit for x in lines) == sum(x.credit for x in lines) > 0
        await s.rollback()


async def test_closed_period_rejects_postings(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as s:
        s.add(FiscalPeriod(year=2026, month=8, status="closed"))
        await s.flush()
        with pytest.raises(AppError) as exc:
            await ledger.post_event(
                s,
                "material_issue",
                {"issued": D(100)},
                entry_date=date(2026, 8, 15),
                description="x",
                source_type="t",
                source_id="1",
                by=None,
                dims=ledger.Dims(cost_element="CONSUMABLE"),
            )
        assert exc.value.code == "PERIOD_CLOSED"


async def test_manual_journal_needs_lead_controller(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    creator_user = await make_user("finance_officer", "lead_controller")
    creator = await login(creator_user)
    lc = await login(await make_user("lead_controller"))
    body: dict[str, Any] = {
        "entry_date": today_jakarta().isoformat(),
        "description": "Koreksi biaya administrasi bank",
        "lines": [
            {"account": "6100", "debit": "250000"},
            {"account": "1110", "credit": "200000"},
        ],
    }
    r = await client.post("/api/ledger/manual-journals", json=body, headers=creator)
    assert r.status_code == 422 and r.json()["code"] == "JOURNAL_UNBALANCED"
    body["lines"][1]["credit"] = "250000"
    mj = (await client.post("/api/ledger/manual-journals", json=body, headers=creator)).json()
    assert mj["status"] == "draft"
    sub = (
        await client.post(f"/api/ledger/manual-journals/{mj['id']}/submit", headers=creator)
    ).json()
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=creator
    )
    assert r.status_code == 403 and r.json()["code"] == "SOD_SELF_APPROVAL"
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=lc
    )
    assert r.status_code == 200, r.text
    posted = next(
        m
        for m in (await client.get("/api/ledger/manual-journals", headers=lc)).json()
        if m["id"] == mj["id"]
    )
    assert posted["status"] == "posted" and posted["journal_id"]
    # Reversal by the Lead Controller nets it out.
    r = await client.post(
        f"/api/ledger/journals/{posted['journal_id']}/reverse",
        json={"reason": "Salah akun beban"},
        headers=lc,
    )
    assert r.status_code == 200
    tb = (await client.get("/api/ledger/reports/trial-balance", headers=lc)).json()
    assert tb["summary"]["difference"] == "0"
    gl = (
        await client.get(
            "/api/ledger/reports/general-ledger",
            params={"account": "6100", "date_from": today_jakarta().replace(day=1).isoformat()},
            headers=lc,
        )
    ).json()
    assert gl["summary"]["closing"] == "0" and len(gl["rows"]) == 2


def _opening_book() -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "GL"
    ws.append(["account", "debit", "credit", "memo"])
    ws.append(["1110", 100 * M, None, "Saldo bank"])
    ws.append(["3200", None, 340 * M, "Laba ditahan"])
    ar = wb.create_sheet("AR")
    ar.append(["client", "invoice_no", "invoice_date", "due_date", "amount"])
    ar.append(["C-OB", "OB-INV-0001", "2026-09-15", "2026-10-15", 50 * M])
    ap = wb.create_sheet("AP")
    ap.append(["vendor", "invoice_no", "invoice_date", "due_date", "amount"])
    ap.append(["V-A", "OB-VI-77", "2026-09-20", "2026-10-20", 20 * M])
    st = wb.create_sheet("Stock")
    st.append(["warehouse", "item", "qty", "value"])
    st.append(["WH-CLG", "ITM-1", 10, 60 * M])
    asg = wb.create_sheet("Assets")
    asg.append(["asset", "cost", "accumulated_depreciation"])
    asg.append(["AST-OB", 200 * M, 50 * M])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_opening_balance_import(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    async with sessionmaker() as s:
        s.add(Client(code="C-OB", name="PT Lama"))
        s.add(Asset(code="AST-OB", name="Separator lama", asset_class="Separator", criticality="A"))
        await s.commit()
    lc = await login(await make_user("lead_controller"))
    go_live = "2026-09-30"
    r = await client.post(
        "/api/ledger/opening",
        data={"as_of": go_live},
        files={"file": ("saldo-awal.xlsx", _opening_book(), "application/octet-stream")},
        headers=lc,
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert (res["ar_items"], res["ap_items"], res["stock_rows"], res["assets"]) == (1, 1, 1, 1)
    assert res["total"] == str(410 * M)
    tb = (
        await client.get("/api/ledger/reports/trial-balance", params={"as_of": go_live}, headers=lc)
    ).json()
    bal = {row["account"]: (row["balance_debit"], row["balance_credit"]) for row in tb["rows"]}
    assert bal["1210"] == (str(50 * M), "0") and bal["2110"] == ("0", str(20 * M))
    assert bal["1310"] == (str(60 * M), "0") and bal["1590"] == ("0", str(50 * M))
    assert tb["summary"]["difference"] == "0"
    bs = (
        await client.get("/api/ledger/reports/balance-sheet", params={"as_of": go_live}, headers=lc)
    ).json()
    assert bs["summary"]["difference"] == "0"
    async with sessionmaker() as s:
        inv = (
            await s.execute(select(CustomerInvoice).where(CustomerInvoice.is_opening))
        ).scalar_one()
        assert (inv.number, inv.total, inv.status) == ("OB-INV-0001", D(50 * M), "sent")
        a = (await s.execute(select(Asset).where(Asset.code == "AST-OB"))).scalar_one()
        assert (a.acquisition_cost, a.accumulated_depreciation) == (D(200 * M), D(50 * M))
    # Only once.
    r = await client.post(
        "/api/ledger/opening",
        data={"as_of": go_live},
        files={"file": ("saldo-awal.xlsx", _opening_book(), "application/octet-stream")},
        headers=lc,
    )
    assert r.status_code == 409 and r.json()["code"] == "OPENING_DONE"


async def test_usd_receipt_posts_realised_fx(
    sessionmaker: async_sessionmaker[AsyncSession],
    principal_of: Callable[..., Awaitable[Any]],
    make_user: MakeUser,
) -> None:
    today = today_jakarta()
    async with sessionmaker() as s:
        s.add(Client(code="C-USD", name="KKKS Asing"))
        s.add(FxRate(currency="USD", rate_date=today - timedelta(days=30), rate=D(15000)))
        s.add(FxRate(currency="USD", rate_date=today, rate=D(15500)))
        await s.flush()
        inv = CustomerInvoice(
            number="INV-USD-1",
            client_code="C-USD",
            status="sent",
            invoice_date=today - timedelta(days=30),
            due_date=today,
            currency="USD",
            fx_rate=D(15000),
            total_foreign=D("1000.00"),
            subtotal=D(15_000_000),
            total=D(15_000_000),
            net_cash=D(15_000_000),
        )
        s.add(inv)
        await s.commit()
        inv_id = inv.id
    async with sessionmaker() as s:
        actor = await principal_of(await make_user("billing_admin"), s)
        r = await receipt_service.record(
            s,
            actor,
            receipt_date=today,
            allocations=[receipt_service.AllocationIn(inv_id, D(0), cash_foreign=D("1000.00"))],
            bank_ref="USD",
        )
        await s.commit()
        rows = (
            (
                await s.execute(
                    select(JournalLine.account_code, JournalLine.debit, JournalLine.credit)
                    .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                    .where(JournalEntry.source_id == str(r.id))
                    .order_by(JournalLine.seq)
                )
            )
            .tuples()
            .all()
        )
        # 1.000 USD received at 15.500 against AR booked at 15.000: FX gain 500.000 (Cr 7100).
        assert [(a, int(d), int(c)) for a, d, c in rows] == [
            ("1110", 15_500_000, 0),
            ("7100", 0, 500_000),
            ("1210", 0, 15_000_000),
        ]
        paid = await s.get(CustomerInvoice, inv_id)
        assert paid is not None and paid.status == "paid" and paid.paid_foreign == D("1000.00")


async def test_full_scenario_trial_balance_zero_and_reports(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    p, tk, ba = await _ticketed(client, make_user, login, sessionmaker)
    await client.post(
        f"/api/billing/tickets/{tk['id']}/sign",
        json={"signer_name": "Pak Rep", "signature": _png(), "acceptance_no": "SES-1"},
        headers=ba,
    )
    today = today_jakarta().isoformat()
    inv = (
        await client.post(
            "/api/billing/invoices",
            json={"ticket_ids": [tk["id"]], "invoice_date": today},
            headers=ba,
        )
    ).json()
    await client.post(
        f"/api/billing/invoices/{inv['id']}/faktur",
        json={"faktur_number": "04002600000000999", "faktur_date": today},
        headers=ba,
    )
    full = (await client.get(f"/api/billing/invoices/{inv['id']}", headers=ba)).json()
    r = await client.post(
        "/api/billing/receipts",
        json={
            "receipt_date": today,
            "allocations": [
                {"invoice_id": inv["id"], "cash": full["net_cash"], "pph23": full["pph23_expected"]}
            ],
        },
        headers=ba,
    )
    assert r.status_code == 201, r.text
    lc = await login(await make_user("lead_controller"))
    tb = (await client.get("/api/ledger/reports/trial-balance", headers=lc)).json()
    assert tb["summary"]["difference"] == "0"
    assert tb["summary"]["debit"] == tb["summary"]["credit"]
    bs = (await client.get("/api/ledger/reports/balance-sheet", headers=lc)).json()
    assert bs["summary"]["difference"] == "0"
    pl = (await client.get("/api/ledger/reports/profit-loss", headers=lc)).json()
    # DOR revenue 29.033.333 accrued; COGS 12 jt consumables (stock issued at the site).
    assert (
        pl["summary"]["revenue_month"] == "29033333"
        and pl["summary"]["expense_month"] == "12000000"
    )
    cf = (await client.get("/api/ledger/reports/cash-flow", headers=lc)).json()
    assert cf["rows"][0]["category"] == "Penerimaan dari pelanggan"
    assert cf["summary"]["net"] == full["net_cash"]
    proj = (await client.get("/api/ledger/reports/project-pnl", headers=lc)).json()
    row = next(x for x in proj["rows"] if x["project"] == "PRJ-26-001")
    assert row["dor_revenue"] == "29033333" and row["actual_cost"] == "23300000"
    dims = (
        await client.get(
            "/api/ledger/reports/dimensions", params={"dimension": "project"}, headers=lc
        )
    ).json()
    assert any(x["dimension"] == "PRJ-26-001" for x in dims["rows"])
    for name in (
        "trial-balance",
        "profit-loss",
        "balance-sheet",
        "cash-flow",
        "project-pnl",
        "profit-loss-projects",
    ):
        x = await client.get(f"/api/ledger/reports/{name}", params={"format": "xlsx"}, headers=lc)
        assert x.status_code == 200 and x.content[:2] == b"PK", name
        pdf = await client.get(f"/api/ledger/reports/{name}", params={"format": "pdf"}, headers=lc)
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF", name
    rules = (await client.get("/api/ledger/posting-rules", headers=lc)).json()
    assert {r["event"] for r in rules} == set(posting_rules.RULES)
    _ = p
