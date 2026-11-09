"""Phase 07d: tax workspace (PPN settlement journal, carry forward, PPh via payment run),
depreciation, period close (posting to a closed period rejected, close blocked by a submitted
DOR, warnings need a note, reopen by Head of Finance with a reason)."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.core.errors import AppError
from app.maintenance.models import AssetAllocation
from app.master.models import Asset, FiscalPeriod
from app.services import ledger
from app.services.numbering import today_jakarta
from tests.test_dor import _dor, _setup, _sync
from tests.test_inventory import _opening, _project, masters  # noqa: F401
from tests.test_treasury import _bank_id, _fund

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal


def _months_ago(n: int) -> tuple[int, int, date]:
    t = today_jakarta()
    k = t.year * 12 + t.month - 1 - n
    y, m = k // 12, k % 12 + 1
    return y, m, date(y, m, 10)


async def _post(
    sm: async_sessionmaker[AsyncSession], on: date, lines: list[tuple[str, int, int]]
) -> None:
    async with sm() as s:
        await ledger.post_journal(
            s,
            entry_date=on,
            description="uji",
            lines=[ledger.JLine(a, debit=D(dr), credit=D(cr)) for a, dr, cr in lines],
            source_type="test",
            source_id=uuid.uuid4().hex,
            by=None,
        )
        await s.commit()


async def test_ppn_settlement_journal_and_carry_forward(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    await _fund(sessionmaker, 50 * M)
    y, m, on = _months_ago(2)
    # Output PPN 11 jt (sales), input PPN 4 jt (purchases) in the period.
    await _post(sessionmaker, on, [("1210", 111 * M, 0), ("4100", 0, 100 * M), ("2210", 0, 11 * M)])
    await _post(sessionmaker, on, [("5400", 40 * M, 0), ("1420", 4 * M, 0), ("2110", 0, 44 * M)])
    tax = await login(await make_user("tax_specialist"))
    ws = (await client.get(f"/api/tax/periods/{y}/{m}", headers=tax)).json()
    ppn = next(r for r in ws["returns"] if r["tax_type"] == "ppn")
    assert (ppn["output_tax"], ppn["input_tax"], ppn["amount"]) == (
        str(11 * M),
        str(4 * M),
        str(7 * M),
    )
    # PPN: pay and file by the end of the following month.
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    assert ppn["pay_due"] == ppn["file_due"] and ppn["pay_due"].startswith(f"{ny}-{nm:02d}-")
    url = f"/api/tax/returns/{ppn['id']}"
    r = await client.post(f"{url}/billing", json={"billing_code": "12345"}, headers=tax)
    assert r.status_code == 422
    r = await client.post(
        f"{url}/file", json={"bpe_no": "BPE-0001", "filed_on": str(on)}, headers=tax
    )
    assert r.status_code == 409 and r.json()["code"] == "NOT_PAID"
    r = await client.post(f"{url}/billing", json={"billing_code": "123456789012345"}, headers=tax)
    assert r.status_code == 200 and r.json()["status"] == "billed"
    pay_on = on + timedelta(days=20)
    r = await client.post(
        f"{url}/pay",
        json={"ntpn": "ABCD1234EFGH5678", "paid_on": str(pay_on), "method": "direct"},
        headers=tax,
    )
    assert r.status_code == 200, r.text
    paid = r.json()
    async with sessionmaker() as s:
        lines = await ledger.lines_of(s, uuid.UUID(paid["journal_id"]))
        assert {(x.account_code, x.debit, x.credit) for x in lines} == {
            ("2210", D(11 * M), D(0)),
            ("1420", D(0), D(4 * M)),
            ("1110", D(0), D(7 * M)),
        }
        assert await ledger.balance(s, "2210") == 0 and await ledger.balance(s, "1420") == 0
    r = await client.post(
        f"{url}/file", json={"bpe_no": "BPE-0001", "filed_on": str(pay_on)}, headers=tax
    )
    assert r.status_code == 200 and r.json()["status"] == "filed"

    # Next month: input above output -> nothing to pay, 2 jt carried forward.
    y2, m2, on2 = _months_ago(1)
    await _post(sessionmaker, on2, [("1210", 1 * M, 0), ("2210", 0, 1 * M)])
    await _post(sessionmaker, on2, [("1420", 3 * M, 0), ("2110", 0, 3 * M)])
    ws2 = (await client.get(f"/api/tax/periods/{y2}/{m2}", headers=tax)).json()
    ppn2 = next(r for r in ws2["returns"] if r["tax_type"] == "ppn")
    assert (ppn2["amount"], ppn2["carry_forward"]) == ("0", str(2 * M))
    r = await client.post(
        f"/api/tax/returns/{ppn2['id']}/billing",
        json={"billing_code": "123456789012345"},
        headers=tax,
    )
    assert r.status_code == 409 and r.json()["code"] == "NOTHING_TO_PAY"
    r = await client.post(
        f"/api/tax/returns/{ppn2['id']}/file",
        json={"bpe_no": "BPE-0002", "filed_on": str(on2)},
        headers=tax,
    )
    assert r.status_code == 200, r.text
    async with sessionmaker() as s:
        assert await ledger.balance(s, "2210") == 0
        assert await ledger.balance(s, "1420") == 2 * M  # compensation carried on
    ws3 = (
        await client.get(
            f"/api/tax/periods/{today_jakarta().year}/{today_jakarta().month}", headers=tax
        )
    ).json()
    assert next(r for r in ws3["returns"] if r["tax_type"] == "ppn")["carried_in"] == str(2 * M)


async def test_pph23_paid_through_payment_run(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    await _fund(sessionmaker, 10 * M)
    y, m, on = _months_ago(1)
    await _post(sessionmaker, on, [("5400", 50 * M, 0), ("2110", 0, 49 * M), ("2230", 0, 1 * M)])
    tax = await login(await make_user("tax_specialist"))
    ws = (await client.get(f"/api/tax/periods/{y}/{m}", headers=tax)).json()
    pph = next(r for r in ws["returns"] if r["tax_type"] == "pph23")
    assert (
        pph["amount"] == str(1 * M)
        and pph["pay_due"] == f"{(y + 1) if m == 12 else y}-{(1 if m == 12 else m + 1):02d}-15"
    )
    ap = await login(await make_user("ap_accountant"))
    run = (
        await client.post(
            "/api/treasury/payment-runs",
            json={
                "pay_date": str(today_jakarta()),
                "bank_account_id": await _bank_id(sessionmaker),
                "items": [{"kind": "pph23", "amount": str(1 * M)}],
            },
            headers=ap,
        )
    ).json()
    sub = (await client.post(f"/api/treasury/payment-runs/{run['id']}/submit", headers=ap)).json()
    hof = await login(await make_user("head_of_finance"))
    await client.post(f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=hof)
    cashier = await login(await make_user("cashier"))
    assert (
        await client.post(f"/api/treasury/payment-runs/{run['id']}/release", headers=cashier)
    ).status_code == 200
    url = f"/api/tax/returns/{pph['id']}"
    await client.post(f"{url}/billing", json={"billing_code": "923456789012345"}, headers=tax)
    r = await client.post(
        f"{url}/pay",
        json={
            "ntpn": "ZXCV1234ASDF5678",
            "paid_on": str(today_jakarta()),
            "method": "payment_run",
            "payment_run_id": run["id"],
        },
        headers=tax,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid" and r.json()["payment_run_id"] == run["id"]
    async with sessionmaker() as s:
        assert await ledger.balance(s, "2230") == 0


async def test_depreciation_commercial_and_fiscal(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    p = await _project(sessionmaker)
    y, m, _ = _months_ago(1)
    async with sessionmaker() as s:
        s.add_all(
            [
                Asset(
                    code="AST-SEP",
                    name="Separator 3 fasa",
                    asset_class="Well testing",
                    criticality="A",
                    equipment_type_code="WT-SEP",
                    acquisition_cost=D(120 * M),
                    useful_life_months=48,
                    depreciation_start=date(y, m, 1),
                    tax_group="kelompok_2",
                ),
                Asset(
                    code="AST-LAP",
                    name="Laptop",
                    asset_class="IT",
                    criticality="C",
                    acquisition_cost=D(12 * M),
                    accumulated_depreciation=D(11_500_000),
                    useful_life_months=12,
                    depreciation_start=date(y - 1, m, 1),
                ),
            ]
        )
        await s.flush()
        s.add(AssetAllocation(asset_code="AST-SEP", project_id=p.id, start_date=date(y, m, 1)))
        await s.commit()
    lc = await login(await make_user("lead_controller"))
    r = await client.post(f"/api/close/periods/{y}/{m}/depreciation", headers=lc)
    assert r.status_code == 200, r.text
    out = r.json()
    # 120 jt / 48 = 2,5 jt to 5200 on the project; laptop only the last 0,5 jt to 6200.
    assert out["total"] == str(3 * M) and out["fiscal_total"] == "1250000"
    async with sessionmaker() as s:
        lines = await ledger.lines_of(s, uuid.UUID(out["journal_id"]))
        got = {(x.account_code, x.debit, x.credit, x.asset_code, x.project_id) for x in lines}
        assert got == {
            ("5200", D(2_500_000), D(0), "AST-SEP", p.id),
            ("1590", D(0), D(2_500_000), "AST-SEP", None),
            ("6200", D(500_000), D(0), "AST-LAP", None),
            ("1590", D(0), D(500_000), "AST-LAP", None),
        }
        lap = (await s.execute(select(Asset).where(Asset.code == "AST-LAP"))).scalar_one()
        assert lap.accumulated_depreciation == 12 * M
    r = await client.post(f"/api/close/periods/{y}/{m}/depreciation", headers=lc)
    assert r.status_code == 409 and r.json()["code"] == "DEPRECIATION_DONE"
    fr = (await client.get(f"/api/tax/fiscal-depreciation/{y}", headers=lc)).json()
    sep = next(x for x in fr["rows"] if x["asset"] == "AST-SEP")
    assert (sep["commercial"], sep["fiscal"], sep["correction"]) == (
        "2500000",
        "1250000",
        "1250000",
    )


async def test_close_reopen_and_closed_period_rejects_posting(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    y, m, on = _months_ago(1)
    await _post(sessionmaker, on, [("6100", 1 * M, 0), ("2110", 0, 1 * M)])
    lc = await login(await make_user("lead_controller"))
    hof = await login(await make_user("head_of_finance"))
    st = (await client.get(f"/api/close/periods/{y}/{m}", headers=lc)).json()
    checks = {c["key"]: c for c in st["checks"]}
    assert checks["dors"]["ok"] and checks["trial_balance"]["ok"]
    assert not checks["depreciation"]["ok"] and not checks["tax"]["ok"]  # warnings
    url = f"/api/close/periods/{y}/{m}"
    r = await client.post(f"{url}/close", json={}, headers=hof)
    assert r.status_code == 403 and r.json()["code"] == "NOT_LEAD_CONTROLLER"
    r = await client.post(f"{url}/close", json={}, headers=lc)
    assert r.status_code == 422 and r.json()["code"] == "CLOSE_NOTE_REQUIRED"
    r = await client.post(
        f"{url}/close", json={"note": "SPT dilaporkan minggu depan; aset belum ada."}, headers=lc
    )
    assert r.status_code == 200 and r.json()["status"] == "closed"
    # Posting into the closed period is rejected.
    with pytest.raises(AppError) as exc:
        await _post(sessionmaker, on, [("6100", 1, 0), ("1110", 0, 1)])
    assert exc.value.code == "PERIOD_CLOSED"
    # Data Master cannot reopen it either.
    async with sessionmaker() as s:
        pid = (
            await s.execute(
                select(FiscalPeriod.id).where(FiscalPeriod.year == y, FiscalPeriod.month == m)
            )
        ).scalar_one()
    admin = await login(await make_user("lead_controller", "super_admin"))
    r = await client.patch(f"/api/master/periods/{pid}", json={"status": "open"}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "PERIOD_CLOSED"
    # Reopen: Head of Finance only, with a reason.
    r = await client.post(
        f"{url}/reopen", json={"reason": "Koreksi accrual GR/IR bulan lalu"}, headers=lc
    )
    assert r.status_code == 403
    r = await client.post(f"{url}/reopen", json={"reason": "singkat"}, headers=hof)
    assert r.status_code == 422
    r = await client.post(
        f"{url}/reopen", json={"reason": "Koreksi accrual GR/IR bulan lalu"}, headers=hof
    )
    assert r.status_code == 200 and r.json()["status"] == "open"
    await _post(sessionmaker, on, [("6100", 1, 0), ("1110", 0, 1)])
    hist = (await client.get(url, headers=lc)).json()["history"]
    assert [h["action"] for h in hist] == ["close", "reopen"]


async def test_close_blocked_by_submitted_dor(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
) -> None:
    fe_user = await make_user("field_engineer")
    p, rates = await _setup(sessionmaker, [fe_user])
    await _opening(sessionmaker, "ITM-1", "WH-RKN", 4, 24 * M)
    fe = await login(fe_user)
    dor: dict[str, Any] = (await _sync(client, fe, p, _dor(rates))).json()
    r = await client.post(f"/api/operations/dors/{dor['id']}/submit", headers=fe)
    assert r.status_code == 200, r.text
    t = today_jakarta()
    lc = await login(await make_user("lead_controller"))
    r = await client.post(
        f"/api/close/periods/{t.year}/{t.month}/close",
        json={"note": "Tutup dengan catatan lengkap"},
        headers=lc,
    )
    assert r.status_code == 409 and r.json()["code"] == "CLOSE_BLOCKED"
    dors = next(c for c in r.json()["details"]["checks"] if c["key"] == "dors")
    assert not dors["ok"] and dors["blocking"] and dors["detail"].startswith("1 DOR")
