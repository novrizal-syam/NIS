"""Phase 07b: payment runs (three-person SoD, balance check, journal, bank file, bukti potong),
bank reconciliation, cash forecast, cash advances (settlement journal and budget actuals)."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.finance.models import JournalEntry, JournalLine, VendorInvoice
from app.project.models import ProjectMember, ProjectWbs
from app.services import budget_control as bc
from app.services import ledger
from app.services.numbering import today_jakarta
from app.services.storage import Storage
from app.treasury import advance_service
from app.treasury.models import BankAccount, CashAdvance
from tests.test_inventory import _project, masters  # noqa: F401

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def _fund(sm: async_sessionmaker[AsyncSession], amount: int, account: str = "1110") -> None:
    async with sm() as s:
        await ledger.post_journal(
            s,
            entry_date=today_jakarta(),
            description="Setoran modal",
            lines=[
                ledger.JLine(account, debit=D(amount)),
                ledger.JLine("3100", credit=D(amount)),
            ],
            source_type="test",
            source_id=uuid.uuid4().hex,
            by=None,
        )
        await s.commit()


async def _vi(
    sm: async_sessionmaker[AsyncSession], payable: int, *, pph23: int = 0, due_in: int = 0
) -> VendorInvoice:
    """An approved vendor invoice with its AP journal (Dr 5400 / Cr 2110 / Cr 2230)."""
    async with sm() as s:
        n = uuid.uuid4().hex[:6]
        dpp = payable + pph23
        vi = VendorInvoice(
            number=f"VI-T-{n}",
            vendor_code="V-A",
            invoice_no=f"INV/{n}",
            invoice_date=today_jakarta(),
            kind="service",
            term_days=30,
            due_date=today_jakarta() + timedelta(days=due_in),
            dpp=D(dpp),
            ppn=D(0),
            pph23_pct=D(2) if pph23 else D(0),
            pph23=D(pph23),
            payable=D(payable),
            status="approved",
        )
        s.add(vi)
        await s.flush()
        lines = [
            ledger.JLine("5400", debit=D(dpp)),
            ledger.JLine("2110", credit=D(payable), partner_type="vendor", partner_code="V-A"),
        ]
        if pph23:
            lines.append(ledger.JLine("2230", credit=D(pph23)))
        await ledger.post_journal(
            s,
            entry_date=today_jakarta(),
            description="AP",
            lines=lines,
            source_type="vendor_invoice",
            source_id=vi.id,
            source_number=vi.number,
            by=None,
        )
        await s.commit()
        return vi


async def _bank_id(sm: async_sessionmaker[AsyncSession]) -> str:
    async with sm() as s:
        return str(
            (
                await s.execute(select(BankAccount.id).where(BankAccount.code == "BA-MDR-IDR"))
            ).scalar_one()
        )


async def _approved_run(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sm: async_sessionmaker[AsyncSession],
    vi: VendorInvoice,
    amount: int,
    *,
    preparer: User | None = None,
    approver: User | None = None,
) -> tuple[dict[str, object], User, User]:
    preparer = preparer or await make_user("ap_accountant")
    approver = approver or await make_user("head_of_finance")
    ph = await login(preparer)
    r = await client.post(
        "/api/treasury/payment-runs",
        json={
            "pay_date": today_jakarta().isoformat(),
            "bank_account_id": await _bank_id(sm),
            "items": [
                {"kind": "vendor_invoice", "vendor_invoice_id": str(vi.id), "amount": amount}
            ],
        },
        headers=ph,
    )
    assert r.status_code == 200, r.text
    run = r.json()
    sub = (await client.post(f"/api/treasury/payment-runs/{run['id']}/submit", headers=ph)).json()
    # SoD 1: the preparer cannot approve.
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=ph
    )
    assert r.status_code == 403 and r.json()["code"] == "SOD_SELF_APPROVAL"
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve",
        json={},
        headers=await login(approver),
    )
    assert r.status_code == 200, r.text
    return run, preparer, approver


async def test_payment_run_three_person_sod_and_release(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    await _fund(sessionmaker, 100 * M)
    vi = await _vi(sessionmaker, 49 * M, pph23=1 * M)
    preparer = await make_user("ap_accountant", "cashier")
    approver = await make_user("head_of_finance", "cashier")
    run, _, _ = await _approved_run(
        client, make_user, login, sessionmaker, vi, 49 * M, preparer=preparer, approver=approver
    )
    url = f"/api/treasury/payment-runs/{run['id']}"
    # SoD 2: preparer may not release; SoD 3: approver may not release.
    r = await client.post(f"{url}/release", headers=await login(preparer))
    assert r.status_code == 403 and r.json()["code"] == "SOD_PREPARER_RELEASER"
    r = await client.post(f"{url}/release", headers=await login(approver))
    assert r.status_code == 403 and r.json()["code"] == "SOD_APPROVER_RELEASER"
    cashier = await login(await make_user("cashier"))
    r = await client.post(f"{url}/release", headers=cashier)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "released" and out["bukti_potong_vendors"] == ["V-A"]
    async with sessionmaker() as s:
        lines = await ledger.lines_of(s, uuid.UUID(out["journal_id"]))
        assert sum(x.debit for x in lines) == sum(x.credit for x in lines) == 49 * M
        assert {(x.account_code, x.debit, x.credit, x.partner_code) for x in lines} == {
            ("2110", D(49 * M), D(0), "V-A"),
            ("1110", D(0), D(49 * M), None),
        }
        paid = await s.get(VendorInvoice, vi.id)
        assert paid is not None and paid.status == "paid" and paid.paid_amount == 49 * M
        assert await ledger.balance(s, "1110") == 51 * M
    f = await client.get(f"{url}/bank-file", headers=cashier)
    assert f.status_code == 200 and b"49000000" in f.content and b"IDR" in f.content
    bp = await client.get(f"{url}/bukti-potong/V-A", headers=cashier)
    assert bp.status_code == 200 and bp.content.startswith(b"%PDF")
    # A paid invoice is no longer a due item.
    due = (await client.get("/api/treasury/payment-runs/due-items", headers=cashier)).json()
    assert all(i["vendor_invoice_id"] != str(vi.id) for i in due["invoices"])


async def test_insufficient_balance_blocks_release(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    await _fund(sessionmaker, 1 * M)
    vi = await _vi(sessionmaker, 5 * M)
    run, _, _ = await _approved_run(client, make_user, login, sessionmaker, vi, 5 * M)
    cashier = await login(await make_user("cashier"))
    r = await client.post(f"/api/treasury/payment-runs/{run['id']}/release", headers=cashier)
    assert r.status_code == 409 and r.json()["code"] == "INSUFFICIENT_BALANCE"
    run_now = (await client.get(f"/api/treasury/payment-runs/{run['id']}", headers=cashier)).json()
    assert run_now["status"] == "approved" and run_now["journal_id"] is None
    async with sessionmaker() as s:
        still = await s.get(VendorInvoice, vi.id)
        assert still is not None and still.paid_amount == 0


async def test_run_cannot_pay_more_than_open(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    vi = await _vi(sessionmaker, 5 * M)
    ap = await login(await make_user("ap_accountant"))
    bank = await _bank_id(sessionmaker)

    async def make(items: list[dict[str, object]]) -> object:
        return await client.post(
            "/api/treasury/payment-runs",
            json={"pay_date": today_jakarta().isoformat(), "bank_account_id": bank, "items": items},
            headers=ap,
        )

    first = await make(
        [{"kind": "vendor_invoice", "vendor_invoice_id": str(vi.id), "amount": 3 * M}]
    )
    assert first.status_code == 200  # type: ignore[attr-defined]
    # The rest is 2 jt because the first (open) run holds 3 jt.
    r = await make([{"kind": "vendor_invoice", "vendor_invoice_id": str(vi.id), "amount": 3 * M}])
    assert r.status_code == 409 and r.json()["code"] == "AMOUNT_EXCEEDS_OPEN"  # type: ignore[attr-defined]
    # Liabilities are paid only up to their GL balance (2310 is empty here).
    r = await make([{"kind": "salaries", "amount": 1 * M}])
    assert r.status_code == 409 and r.json()["code"] == "AMOUNT_EXCEEDS_OPEN"  # type: ignore[attr-defined]


async def test_bank_reconciliation_auto_match_and_unmatched(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    await _fund(sessionmaker, 100 * M)
    vi = await _vi(sessionmaker, 7 * M)
    run, _, _ = await _approved_run(client, make_user, login, sessionmaker, vi, 7 * M)
    cashier_user = await make_user("cashier", "ap_accountant")
    released = (
        await client.post(
            f"/api/treasury/payment-runs/{run['id']}/release", headers=await login(cashier_user)
        )
    ).json()
    ap = await login(await make_user("ap_accountant"))
    bank = await _bank_id(sessionmaker)
    d = today_jakarta().strftime("%d/%m/%Y")
    csv_text = (
        "tanggal;keterangan;jumlah;referensi\n"
        f"{d};SETORAN MODAL;100.000.000,00;\n"
        f"{d};TRF {released['number']} PT VENDOR A;-7.000.000,00;\n"
        f"{d};BIAYA ADMIN;-6.500,00;\n"
    )
    r = await client.post(
        f"/api/treasury/bank-accounts/{bank}/statements",
        files={"file": ("mutasi.csv", csv_text.encode(), "text/csv")},
        headers=ap,
    )
    assert r.status_code == 200, r.text
    assert r.json()["lines"] == 1 and r.json()["debits"] == 2
    assert r.json()["reconciled"] == 2
    rec = (
        await client.get(f"/api/treasury/bank-accounts/{bank}/reconciliation", headers=ap)
    ).json()
    assert rec["reconciled"] == 2 and rec["book_balance"] == str(93 * M)
    assert [x["amount"] for x in rec["unmatched_statement"]] == ["-6500"]
    assert rec["unmatched_book"] == []
    # The bank charge is booked with a manual journal, then matched by hand.
    async with sessionmaker() as s:
        e = await ledger.post_journal(
            s,
            entry_date=today_jakarta(),
            description="Biaya admin bank",
            lines=[ledger.JLine("6100", debit=D(6500)), ledger.JLine("1110", credit=D(6500))],
            source_type="test",
            source_id="adm",
            by=None,
        )
        gl_line = next(x for x in await ledger.lines_of(s, e.id) if x.account_code == "1110")
        await s.commit()
    line_id = rec["unmatched_statement"][0]["id"]
    r = await client.post(
        f"/api/treasury/bank-lines/{line_id}/match",
        json={"journal_line_id": str(gl_line.id)},
        headers=ap,
    )
    assert r.status_code == 200, r.text
    rec = (
        await client.get(f"/api/treasury/bank-accounts/{bank}/reconciliation", headers=ap)
    ).json()
    assert rec["unmatched_statement"] == [] and rec["unmatched_book"] == []
    # Accounts list shows the GL balance.
    accounts = (await client.get("/api/treasury/bank-accounts", headers=ap)).json()
    main = next(a for a in accounts if a["code"] == "BA-MDR-IDR")
    assert main["balance"] == str(93 * M - 6500) and main["unreconciled_statement_lines"] == 0


async def test_cash_forecast_13_weeks(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    await _fund(sessionmaker, 50 * M)
    await _vi(sessionmaker, 8 * M, due_in=8)
    async with sessionmaker() as s:  # 2310 owes 12 jt net salaries
        await ledger.post_journal(
            s,
            entry_date=today_jakarta(),
            description="Gaji",
            lines=[ledger.JLine("5100", debit=D(12 * M)), ledger.JLine("2310", credit=D(12 * M))],
            source_type="test",
            source_id="pay",
            by=None,
        )
        await s.commit()
    hof = await login(await make_user("head_of_finance"))
    r = await client.put(
        "/api/treasury/forecast/settings",
        json={"payroll_monthly": "10000000", "capex": [{"date": "2099-01-01", "amount": 1}]},
        headers=hof,
    )
    assert r.status_code == 200
    fc = (await client.get("/api/treasury/forecast", headers=hof)).json()
    assert len(fc["weeks"]) == 13 and fc["opening"] == str(50 * M)
    assert sum(D(w["ap"]) for w in fc["weeks"]) == 8 * M
    payroll = [D(w["payroll"]) for w in fc["weeks"] if D(w["payroll"]) > 0]
    assert payroll[0] == 12 * M and all(p == 10 * M for p in payroll[1:])
    assert D(fc["closing"]) == 50 * M - sum(D(w["outflow"]) for w in fc["weeks"])


async def test_cash_advance_settlement_journal_and_budget_actuals(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    await _fund(sessionmaker, 20 * M)
    p = await _project(sessionmaker)
    fe_user = await make_user("field_engineer")
    fe = await login(fe_user)
    body = {
        "purpose": "Biaya lapangan sumur RKN-12",
        "amount": "1000000",
        "needed_date": today_jakarta().isoformat(),
        "project_id": str(p.id),
    }
    r = await client.post("/api/treasury/advances", json=body, headers=fe)
    assert r.status_code == 403 and r.json()["code"] == "PROJECT_NOT_MEMBER"
    async with sessionmaker() as s:
        s.add(ProjectMember(project_id=p.id, user_id=fe_user.id))
        await s.commit()
    opts = (await client.get("/api/treasury/advance-options", headers=fe)).json()
    assert [x["wbs"] for x in opts["projects"]] == [["EXEC"]]
    assert "CONSUMABLE" in {c["code"] for c in opts["cost_elements"]}
    r = await client.post(
        "/api/treasury/advances",
        json={
            "purpose": "Biaya lapangan sumur RKN-12",
            "amount": "1000000",
            "needed_date": today_jakarta().isoformat(),
            "project_id": str(p.id),
        },
        headers=fe,
    )
    assert r.status_code == 200, r.text
    ca = r.json()
    url = f"/api/treasury/advances/{ca['id']}"
    sub = (await client.post(f"{url}/submit", headers=fe)).json()
    hoo = await login(await make_user("head_of_operation"))
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=hoo
    )
    assert r.status_code == 200, r.text
    cashier = await login(await make_user("cashier"))
    r = await client.post(f"{url}/disburse", json={}, headers=cashier)
    assert r.status_code == 200 and r.json()["status"] == "disbursed", r.text
    # Receipts are required per line.
    lines = [
        {
            "spent_on": today_jakarta().isoformat(),
            "cost_element": "CONSUMABLE",
            "wbs_code": "EXEC",
            "description": "Solar genset",
            "amount": "600000",
        },
        {
            "spent_on": today_jakarta().isoformat(),
            "cost_element": "EQUIP-RENT",
            "wbs_code": "EXEC",
            "description": "Sewa pompa harian",
            "amount": "300000",
        },
    ]
    r = await client.post(f"{url}/settlement", json={"lines": lines}, headers=fe)
    assert r.status_code == 422 and r.json()["code"] == "RECEIPT_REQUIRED"
    for x in lines:
        up = await client.post(
            "/api/attachments",
            data={"entity_type": "cash_advance", "entity_id": ca["id"], "note": "Nota"},
            files={"file": ("nota.png", PNG + uuid.uuid4().bytes, "image/png")},
            headers=fe,
        )
        assert up.status_code == 201, up.text
        x["attachment_id"] = up.json()["id"]
    r = await client.post(f"{url}/settlement", json={"lines": lines}, headers=fe)
    assert r.status_code == 200 and r.json()["status"] == "settlement_submitted", r.text
    # The requester cannot settle their own advance (and lacks the right anyway).
    r = await client.post(f"{url}/settle", json={}, headers=fe)
    assert r.status_code == 403
    r = await client.post(f"{url}/settle", json={}, headers=cashier)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "settled" and done["difference"] == "-100000"
    async with sessionmaker() as s:
        jl = await ledger.lines_of(s, uuid.UUID(done["settlement_journal_id"]))
        assert sum(x.debit for x in jl) == sum(x.credit for x in jl) == 1 * M
        got = {(x.account_code, x.debit, x.credit) for x in jl}
        assert got == {
            ("5300", D(600_000), D(0)),
            ("5400", D(300_000), D(0)),
            ("1110", D(100_000), D(0)),
            ("1120", D(0), D(1 * M)),
        }
        assert all(x.project_id == p.id for x in jl if x.account_code.startswith("5"))
        assert await ledger.balance(s, "1120") == 0
        wbs = (
            await s.execute(select(ProjectWbs.id).where(ProjectWbs.project_id == p.id))
        ).scalar_one()
        consumable = await bc.available(s, bc.Line(p.id, wbs, "CONSUMABLE"))
        rental = await bc.available(s, bc.Line(p.id, wbs, "EQUIP-RENT"))
        assert consumable.actual == 600_000 and rental.actual == 300_000


async def test_cash_advance_reimbursement_and_overdue_alert(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    await _fund(sessionmaker, 5 * M)
    requester = await make_user("field_engineer")
    rh = await login(requester)
    ca = (
        await client.post(
            "/api/treasury/advances",
            json={
                "purpose": "Perjalanan dinas Duri",
                "amount": "500000",
                "needed_date": today_jakarta().isoformat(),
            },
            headers=rh,
        )
    ).json()
    url = f"/api/treasury/advances/{ca['id']}"
    sub = (await client.post(f"{url}/submit", headers=rh)).json()
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve",
        json={},
        headers=await login(await make_user("head_of_operation")),
    )
    assert r.status_code == 200
    cashier = await login(await make_user("cashier"))
    on = (today_jakarta() - timedelta(days=15)).isoformat()
    assert (
        await client.post(f"{url}/disburse", json={"on": on}, headers=cashier)
    ).status_code == 200
    async with sessionmaker() as s:
        assert await advance_service.overdue_alerts(s) >= 1
        await s.commit()
        assert await advance_service.overdue_alerts(s) == 0  # once only
        row = await s.get(CashAdvance, uuid.UUID(ca["id"]))
        assert row is not None and row.overdue_notified_at is not None
    up = await client.post(
        "/api/attachments",
        data={"entity_type": "cash_advance", "entity_id": ca["id"]},
        files={"file": ("nota.png", PNG + uuid.uuid4().bytes, "image/png")},
        headers=rh,
    )
    r = await client.post(
        f"{url}/settlement",
        json={
            "lines": [
                {
                    "spent_on": today_jakarta().isoformat(),
                    "cost_element": "CONSUMABLE",
                    "description": "Tiket dan hotel",
                    "amount": "700000",
                    "attachment_id": up.json()["id"],
                }
            ]
        },
        headers=rh,
    )
    assert r.status_code == 200, r.text
    done = (await client.post(f"{url}/settle", json={}, headers=cashier)).json()
    assert done["status"] == "settled" and done["difference"] == "200000"
    async with sessionmaker() as s:
        jl = await ledger.lines_of(s, uuid.UUID(done["settlement_journal_id"]))
        assert ("1110", D(0), D(200_000)) in {(x.account_code, x.debit, x.credit) for x in jl}
        # Trial balance still zero after everything.
        total = (
            await s.execute(
                select(JournalLine.debit - JournalLine.credit).join(
                    JournalEntry, JournalEntry.id == JournalLine.entry_id
                )
            )
        ).scalars()
        assert sum(total, D(0)) == 0
        await s.execute(update(CashAdvance).values(is_demo=False))
