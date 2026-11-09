"""Phase 04c: ledger service, moving-average stock, goods receipt, material request, opname."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.core.errors import AppError
from app.finance.models import JournalEntry, JournalLine
from app.inventory import stock_service as stock
from app.master.models import FiscalPeriod, Item, Vendor, Warehouse
from app.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    PurchaseRequisitionLine,
)
from app.project.models import Project, ProjectBudgetLine, ProjectWbs
from app.services import budget_control as bc
from app.services import ledger
from app.services.numbering import today_jakarta
from app.services.storage import Storage

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF"


@pytest.fixture
async def masters(session: AsyncSession) -> None:
    session.add_all(
        [
            Item(
                code="ITM-1",
                name="Demulsifier",
                uom="drum",
                category="chemicals",
                reorder_point=D(6),
                last_price=D(6_400_000),
            ),
            Item(code="ITM-2", name="Gasket", uom="pcs", category="spare", reorder_point=D(0)),
            Warehouse(code="WH-CLG", name="Base Cilegon", kind="base"),
            Warehouse(code="WH-RKN", name="Site Rokan", kind="site", project_code="PRJ-26-001"),
            Vendor(code="V-A", name="PT Alfa", category="chemicals", status="qualified"),
        ]
    )
    await session.commit()


async def _project(sm: async_sessionmaker[AsyncSession], manager: User | None = None) -> Project:
    async with sm() as s:
        p = Project(
            number="PRJ-26-001",
            name="Well testing",
            company_name="PT KKKS",
            status="locked",
            revenue=D(3_000 * M),
            contingency_pct=D(5),
            manager_id=manager.id if manager else None,
        )
        s.add(p)
        await s.flush()
        w = ProjectWbs(project_id=p.id, code="EXEC", name="Execution", seq=1)
        s.add(w)
        await s.flush()
        for code, amount in (("EQUIP-RENT", 100 * M), ("CONSUMABLE", 100 * M)):
            s.add(
                ProjectBudgetLine(
                    project_id=p.id,
                    version=0,
                    wbs_id=w.id,
                    cost_element_code=code,
                    amount=D(amount),
                    source="quotation",
                )
            )
        await s.commit()
        return p


async def _issued_po(
    sm: async_sessionmaker[AsyncSession],
    p: Project,
    ce: str,
    lines: list[tuple[str | None, str, int, int]],  # item_code, description, qty, unit price
) -> PurchaseOrder:
    """An issued PO with its commitment, as 04b leaves it."""
    async with sm() as s:
        wbs = (
            await s.execute(select(ProjectWbs).where(ProjectWbs.project_id == p.id))
        ).scalar_one()
        subtotal = D(sum(q * u for _, _, q, u in lines))
        n = uuid.uuid4().hex[:4]
        pr = PurchaseRequisition(
            number=f"PR-T-{n}",
            project_id=p.id,
            wbs_id=wbs.id,
            cost_element_code=ce,
            requester_id=None,
            need_date=date(2026, 12, 1),
            delivery_location="Rokan",
            status="ordered",
            total=subtotal,
        )
        pr.requester_id = (await s.execute(select(User.id).limit(1))).scalar_one()
        s.add(pr)
        await s.flush()
        po = PurchaseOrder(
            number=f"PO-T-{n}",
            pr_id=pr.id,
            vendor_code="V-A",
            project_id=p.id,
            wbs_id=wbs.id,
            cost_element_code=ce,
            status="issued",
            subtotal=subtotal,
            ppn_amount=subtotal * D("0.11"),
            total=subtotal * D("1.11"),
            delivery_location="Rokan",
        )
        s.add(po)
        await s.flush()
        for seq, (item, desc, q, u) in enumerate(lines, start=1):
            s.add(
                PurchaseRequisitionLine(
                    pr_id=pr.id,
                    seq=seq,
                    item_code=item,
                    description=desc,
                    qty=D(q),
                    uom="lot",
                    est_price=D(u),
                    amount=D(q * u),
                )
            )
            s.add(
                PurchaseOrderLine(
                    po_id=po.id,
                    seq=seq,
                    item_code=item,
                    description=desc,
                    qty=D(q),
                    uom="lot",
                    unit_price=D(u),
                    amount=D(q * u),
                )
            )
        await bc.commit(
            s,
            bc.Line(p.id, wbs.id, ce),
            subtotal,
            doc_type="purchase_order",
            doc_id=str(po.id),
            by=None,
        )
        await s.commit()
        return po


async def _opening(
    sm: async_sessionmaker[AsyncSession], item: str, wh: str, qty: int, value: int
) -> None:
    """Opening stock with its ledger counterpart (Dr 1310 / Cr 3200)."""
    async with sm() as s:
        await stock.receive(s, item, wh, D(qty), D(value), stock.Doc("opening", "x", None, None))
        await ledger.post_journal(
            s,
            entry_date=today_jakarta(),
            description="Saldo awal persediaan",
            lines=[
                ledger.JLine("1310", debit=D(value)),
                ledger.JLine("3200", credit=D(value)),
            ],
            source_type="opening",
            source_id="x",
            by=None,
        )
        await s.commit()


async def _budget(sm: async_sessionmaker[AsyncSession], p: Project, ce: str) -> bc.Balance:
    async with sm() as s:
        return await bc.available(s, await bc.resolve(s, p.id, "EXEC", ce))


async def _journal_lines(sm: async_sessionmaker[AsyncSession], source_id: str) -> list[JournalLine]:
    async with sm() as s:
        rows = await s.execute(
            select(JournalLine)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalEntry.source_id == source_id)
            .order_by(JournalLine.seq)
        )
        return list(rows.scalars())


# ---------------------------------------------------------------- moving average


async def test_moving_average(
    sessionmaker: async_sessionmaker[AsyncSession], masters: None
) -> None:
    doc = stock.Doc("test", "1", None, None)
    async with sessionmaker() as s:
        await stock.receive(s, "ITM-1", "WH-CLG", D(10), D(1_000_000), doc)
        bal = await stock.receive(s, "ITM-1", "WH-CLG", D(5), D(650_000), doc)
        # (1.000.000 + 650.000) / 15 = 110.000
        assert (bal.qty, bal.value, stock.avg_cost(bal)) == (D(15), D(1_650_000), D(110_000))
        assert await stock.issue(s, "ITM-1", "WH-CLG", D(3), doc) == D(330_000)
        bal = await stock.receive(s, "ITM-1", "WH-CLG", D(8), D(1_040_000), doc)
        # 12 x 110.000 + 1.040.000 = 2.360.000 for 20 -> 118.000
        assert (bal.qty, stock.avg_cost(bal)) == (D(20), D(118_000))
        with pytest.raises(AppError) as exc:
            await stock.issue(s, "ITM-1", "WH-CLG", D(21), doc)
        assert exc.value.code == "STOCK_INSUFFICIENT"
        # Rounding never strands a rupiah: 100 for 3 units -> 33 + 34 (rounded) + 33 (rest).
        await stock.receive(s, "ITM-2", "WH-CLG", D(3), D(100), doc)
        out = [await stock.issue(s, "ITM-2", "WH-CLG", D(1), doc) for _ in range(3)]
        assert sum(out) == 100 and out[-1] == D(100) - out[0] - out[1]
        bal = await stock.balance(s, "ITM-2", "WH-CLG")
        assert (bal.qty, bal.value) == (D(0), D(0))
        await s.commit()


# ---------------------------------------------------------------- ledger


async def test_journal_balance_and_rules(
    sessionmaker: async_sessionmaker[AsyncSession], masters: None
) -> None:
    async with sessionmaker() as s:
        with pytest.raises(AppError) as exc:
            await ledger.post_journal(
                s,
                entry_date=today_jakarta(),
                description="x",
                lines=[ledger.JLine("1310", debit=D(100)), ledger.JLine("2120", credit=D(99))],
                source_type="t",
                source_id="1",
                by=None,
            )
        assert exc.value.code == "JOURNAL_UNBALANCED"
        for lines, code in (
            ([ledger.JLine("1310", debit=D(100))], "JOURNAL_TOO_SHORT"),
            (
                [ledger.JLine("1310", debit=D(1), credit=D(1)), ledger.JLine("2120", credit=D(0))],
                "JOURNAL_LINE_INVALID",
            ),
            (
                [ledger.JLine("9999", debit=D(5)), ledger.JLine("2120", credit=D(5))],
                "ACCOUNT_NOT_POSTABLE",
            ),
            (
                [
                    ledger.JLine("5400", debit=D(5), cost_element="CONTINGENCY"),
                    ledger.JLine("2120", credit=D(5)),
                ],
                "CONTINGENCY_NOT_POSTABLE",
            ),
        ):
            with pytest.raises(AppError) as exc:
                await ledger.post_journal(
                    s,
                    entry_date=today_jakarta(),
                    description="x",
                    lines=lines,
                    source_type="t",
                    source_id="1",
                    by=None,
                )
            assert exc.value.code == code
        s.add(FiscalPeriod(year=2026, month=9, status="closed"))
        await s.flush()
        with pytest.raises(AppError) as exc:
            await ledger.post_journal(
                s,
                entry_date=date(2026, 9, 30),
                description="x",
                lines=[ledger.JLine("1310", debit=D(5)), ledger.JLine("2120", credit=D(5))],
                source_type="t",
                source_id="1",
                by=None,
            )
        assert exc.value.code == "PERIOD_CLOSED"
        entry = await ledger.post_journal(
            s,
            entry_date=today_jakarta(),
            description="ok",
            lines=[ledger.JLine("1310", debit=D(500)), ledger.JLine("2120", credit=D(500))],
            source_type="t",
            source_id="1",
            by=None,
        )
        assert entry.number.startswith("JV-26-") and len(entry.number) == 10
        rev = await ledger.reverse(s, entry.id, on=today_jakarta(), reason="salah", by=None)
        assert rev.reversal_of == entry.id
        assert await ledger.balance(s, "1310") == 0
        await s.commit()
    # Posted journals cannot be edited or deleted (database trigger).
    async with sessionmaker() as s:
        with pytest.raises(DBAPIError):
            await s.execute(text("UPDATE journal_lines SET debit = debit + 1"))
        await s.rollback()
        with pytest.raises(DBAPIError):
            await s.execute(text("DELETE FROM journal_entries"))
        await s.rollback()


# ---------------------------------------------------------------- goods receipt


async def _upload(client: AsyncClient, h: dict[str, str], gr_id: str) -> None:
    r = await client.post(
        "/api/attachments",
        data={"entity_type": "goods_receipt", "entity_id": gr_id, "note": "BAST"},
        files={"file": ("bast.pdf", PDF, "application/pdf")},
        headers=h,
    )
    assert r.status_code == 201, r.text


async def test_partial_service_gr(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,
    storage: Storage,
) -> None:
    owner = await make_user("lead_engineer")
    p = await _project(sessionmaker, manager=owner)
    po = await _issued_po(sessionmaker, p, "EQUIP-RENT", [(None, "Sewa genset (hari)", 10, 2 * M)])
    pm = await login(owner)
    wh = await login(await make_user("warehouse_head"))
    today = today_jakarta().isoformat()

    body = {"po_id": str(po.id), "received_date": today, "lines": [{"seq": 1, "qty": "4"}]}
    # Services are received by the project owner, not the warehouse.
    assert (await client.post("/api/inventory/grs", json=body, headers=wh)).status_code == 403
    r = await client.post("/api/inventory/grs", json=body, headers=pm)
    assert r.status_code == 201, r.text
    gr1 = r.json()
    assert gr1["kind"] == "service" and gr1["amount"] == str(8 * M)
    r = await client.post(f"/api/inventory/grs/{gr1['id']}/post", headers=pm)
    assert r.status_code == 422 and r.json()["code"] == "EVIDENCE_REQUIRED"
    await _upload(client, pm, gr1["id"])
    r = await client.post(f"/api/inventory/grs/{gr1['id']}/post", headers=pm)
    assert r.status_code == 200, r.text
    posted = r.json()
    assert posted["status"] == "posted" and posted["po_status"] == "issued"
    assert [(x["account_code"], x["debit"], x["credit"]) for x in posted["journal"]["lines"]] == [
        ("5400", "8000000", "0"),
        ("2120", "0", "8000000"),
    ]
    bal = await _budget(sessionmaker, p, "EQUIP-RENT")
    assert (bal.commit, bal.actual) == (D(12 * M), D(8 * M))
    jl = await _journal_lines(sessionmaker, gr1["id"])
    assert jl[0].project_id == p.id and jl[0].cost_element_code == "EQUIP-RENT"
    assert jl[0].partner_code == "V-A" and sum(x.debit for x in jl) == sum(x.credit for x in jl)

    # Cannot receive more than is open.
    over = {**body, "lines": [{"seq": 1, "qty": "7"}]}
    r = await client.post("/api/inventory/grs", json=over, headers=pm)
    assert r.status_code == 422 and r.json()["code"] == "QTY_EXCEEDS_PO"

    r = await client.post(
        "/api/inventory/grs", json={**body, "lines": [{"seq": 1, "qty": "6"}]}, headers=pm
    )
    gr2 = r.json()
    await _upload(client, pm, gr2["id"])
    r = await client.post(f"/api/inventory/grs/{gr2['id']}/post", headers=pm)
    assert r.status_code == 200 and r.json()["po_status"] == "closed"
    bal = await _budget(sessionmaker, p, "EQUIP-RENT")
    assert (bal.commit, bal.actual) == (D(0), D(20 * M))
    po_detail = (await client.get(f"/api/procurement/pos/{po.id}", headers=pm)).json()
    assert po_detail["lines"][0]["received"] == "10" and len(po_detail["grs"]) == 2
    assert not po_detail["can_receive"]


async def test_stock_gr_into_warehouse(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,
    storage: Storage,
) -> None:
    wh = await login(await make_user("warehouse_head"))
    p = await _project(sessionmaker)
    po = await _issued_po(sessionmaker, p, "CONSUMABLE", [("ITM-1", "Demulsifier", 10, 6_000_000)])
    r = await client.post(
        "/api/inventory/grs",
        json={
            "po_id": str(po.id),
            "received_date": today_jakarta().isoformat(),
            "warehouse_code": "WH-CLG",
            "lines": [{"seq": 1, "qty": "10"}],
        },
        headers=wh,
    )
    assert r.status_code == 201, r.text
    gr = r.json()
    assert gr["kind"] == "goods" and gr["lines"][0]["to_stock"]
    await _upload(client, wh, gr["id"])
    r = await client.post(f"/api/inventory/grs/{gr['id']}/post", headers=wh)
    assert r.status_code == 200, r.text
    assert [(x["account_code"], x["debit"]) for x in r.json()["journal"]["lines"]] == [
        ("1310", "60000000"),
        ("2120", "0"),
    ]
    # Stock item: the commitment is released, the project is charged when material is issued.
    bal = await _budget(sessionmaker, p, "CONSUMABLE")
    assert (bal.commit, bal.actual) == (D(0), D(0))
    val = (await client.get("/api/inventory/valuation", headers=wh)).json()
    assert val["total"] == "60000000" and val["reconciled"]
    assert val["rows"][0]["avg_cost"] == "6000000.00"


# ---------------------------------------------------------------- material request


async def test_mr_split_into_issue_and_pr(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,
) -> None:
    owner = await make_user("lead_engineer")
    p = await _project(sessionmaker, manager=owner)
    await _opening(sessionmaker, "ITM-1", "WH-CLG", 5, 30_000_000)  # 6 jt / drum
    wh = await login(await make_user("warehouse_head"))
    r = await client.post(
        "/api/inventory/transfers",
        json={
            "from_warehouse": "WH-CLG",
            "to_warehouse": "WH-RKN",
            "lines": [{"item_code": "ITM-1", "qty": "2"}],
        },
        headers=wh,
    )
    assert r.status_code == 201 and r.json()["value"] == "12000000"

    fe_user = await make_user("field_engineer")
    fe = await login(fe_user)
    body: dict[str, Any] = {
        "project_id": str(p.id),
        "wbs_code": "EXEC",
        "cost_element_code": "CONSUMABLE",
        "site_warehouse": "WH-RKN",
        "need_date": "2026-12-01",
        "purpose": "Treatment sumur RK-12",
        "lines": [{"item_code": "ITM-1", "qty": "8"}],
    }
    # Not in the project team yet.
    r = await client.post("/api/inventory/mrs", json=body, headers=fe)
    assert r.status_code == 403 and r.json()["code"] == "NOT_PROJECT_MEMBER"
    r = await client.post(
        f"/api/projects/{p.id}/members",
        json={"user_id": str(fe_user.id)},
        headers=await login(owner),
    )
    assert r.status_code == 201, r.text
    fe = await login(fe_user)  # project scope is read at login

    r = await client.post("/api/inventory/mrs", json=body, headers=fe)
    assert r.status_code == 201, r.text
    mr = r.json()
    line = mr["lines"][0]
    # Site first (2), then base (3); the remaining 3 become a PR at the last price.
    assert (line["from_site"], line["from_base"], line["shortfall"]) == ("2", "3", "3")
    assert mr["status"] == "partial" and mr["issued_value"] == "30000000"
    assert [(x["account_code"], x["debit"], x["credit"]) for x in mr["journal"]["lines"]] == [
        ("5300", "30000000", "0"),
        ("1310", "0", "30000000"),
    ]
    assert mr["pr"]["status"] == "awaiting_approval"
    pr = (await client.get(f"/api/procurement/prs/{mr['pr']['id']}", headers=fe)).json()
    assert pr["total"] == str(3 * 6_400_000) and pr["lines"][0]["qty"] == "3"
    assert pr["requester_name"] and pr["lines"][0]["item_code"] == "ITM-1"

    bal = await _budget(sessionmaker, p, "CONSUMABLE")
    assert (bal.actual, bal.pre_commit) == (D(30 * M), D(0))
    val = (await client.get("/api/inventory/valuation", headers=wh)).json()
    assert val["total"] == "0" and val["reconciled"] and val["ledger_1310"] == "0"
    # Reorder: nothing left of a reorder-point item.
    reo = (await client.get("/api/inventory/reorder", headers=wh)).json()
    assert reo[0]["item_code"] == "ITM-1" and reo[0]["suggested_qty"] == "12"


# ---------------------------------------------------------------- stock opname


async def test_opname_variance_needs_lead_controller(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,
) -> None:
    await _opening(sessionmaker, "ITM-1", "WH-CLG", 10, 60_000_000)
    wh = await login(await make_user("warehouse_head"))
    lc = await login(await make_user("lead_controller"))
    r = await client.post(
        "/api/inventory/counts",
        json={
            "warehouse_code": "WH-CLG",
            "count_date": today_jakarta().isoformat(),
            "lines": [{"item_code": "ITM-1", "counted_qty": "8"}],
        },
        headers=wh,
    )
    assert r.status_code == 422 and r.json()["code"] == "REASON_REQUIRED"
    r = await client.post(
        "/api/inventory/counts",
        json={
            "warehouse_code": "WH-CLG",
            "count_date": today_jakarta().isoformat(),
            "lines": [{"item_code": "ITM-1", "counted_qty": "8", "reason": "Drum bocor"}],
        },
        headers=wh,
    )
    assert r.status_code == 201, r.text
    sc = r.json()
    assert sc["lines"][0]["variance_value"] == "-12000000"
    r = await client.post(f"/api/inventory/counts/{sc['id']}/submit", headers=wh)
    assert r.json()["status"] == "awaiting_approval"
    # Stock untouched until approved.
    async with sessionmaker() as s:
        assert await stock.on_hand(s, "ITM-1", "WH-CLG") == D(10)
    req = r.json()["request_id"]
    r = await client.post(f"/api/workflow/requests/{req}/approve", json={}, headers=lc)
    assert r.status_code == 200, r.text
    done = (await client.get(f"/api/inventory/counts/{sc['id']}", headers=lc)).json()
    assert done["status"] == "approved"
    assert [(x["account_code"], x["debit"], x["credit"]) for x in done["journal"]["lines"]] == [
        ("6100", "12000000", "0"),
        ("1310", "0", "12000000"),
    ]
    val = (await client.get("/api/inventory/valuation", headers=lc)).json()
    assert val["total"] == "48000000" and val["reconciled"]
