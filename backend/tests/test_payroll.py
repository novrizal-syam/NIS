"""Phase 07c: payroll - days from DOR, TER lookup, BPJS caps, overtime, December annual,
allocation to projects, journal balance, SoD, payment through a payment run, payslip access."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.finance.models import JournalEntry, JournalLine
from app.master.models import Employee
from app.operations.models import PayrollDay
from app.payroll import calc
from app.payroll import service as payroll
from app.payroll.seed import DEFAULT_RULES, TER
from app.project.models import Project, ProjectWbs
from app.services import ledger
from app.services.numbering import today_jakarta
from app.services.storage import Storage
from tests.test_dor import _dor, _setup
from tests.test_inventory import _opening, masters  # noqa: F401
from tests.test_maintenance_qhse import _approve_dor
from tests.test_treasury import _bank_id, _fund

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal


def test_ter_lookup_bpjs_caps_overtime_and_annual() -> None:
    # TER (PP 58/2023): band upper bounds are inclusive.
    assert calc.ter_rate(TER["A"], D(5_400_000)) == 0
    assert calc.ter_rate(TER["A"], D(5_400_001)) == D("0.25")
    assert calc.ter_rate(TER["A"], D(10_000_000)) == 2
    assert calc.ter_rate(TER["B"], D(9_200_000)) == 1
    assert calc.ter_rate(TER["C"], D(1_500_000_000)) == 34
    # BPJS: Kesehatan capped at 12 jt, JP at 10.547.400; JHT/JKK/JKM uncapped.
    b = calc.bpjs(D(20 * M), DEFAULT_RULES["bpjs"])  # type: ignore[arg-type]
    assert (b.kes_er, b.kes_ee) == (480_000, 120_000)
    assert (b.jp_er, b.jp_ee) == (210_948, 105_474)
    assert (b.jht_er, b.jht_ee) == (740_000, 400_000)
    assert (b.jkk_er, b.jkm_er) == (348_000, 60_000)
    small = calc.bpjs(D(5 * M), DEFAULT_RULES["bpjs"])  # type: ignore[arg-type]
    assert (small.kes_er, small.jp_ee) == (200_000, 50_000)
    # Overtime PP 35/2021: first hour x1.5, then x2, per day.
    assert calc.overtime_factor_hours([D(3), D(1), D(0)], D("1.5"), D(2)) == D("7")
    # Annual: 120 jt bruto, 3.6 jt pension, TK/0 -> PKP 56.4 jt x 5 % = 2.82 jt.
    a = calc.annual(
        gross_year=D(120 * M),
        pension_year=D(3_600_000),
        withheld_before=D(2 * M),
        months=12,
        ptkp=D(54 * M),
        rules=DEFAULT_RULES,
        has_tax_id=True,
    )
    assert (a.position_cost, a.pkp, a.tax, a.december) == (6 * M, 56_400_000, 2_820_000, 820_000)
    assert calc.progressive(D(300 * M), DEFAULT_RULES["brackets"]) == D(  # type: ignore[arg-type]
        3_000_000 + 28_500_000 + 12_500_000
    )
    assert calc.allocate(D(1000), [1, 2]) == [333, 667]


def _period_for(today: date) -> tuple[int, int]:
    """The payroll month whose cut-off (25th) period contains today."""
    if today.day > 25:
        return (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return today.year, today.month


async def _approved_dor_days(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sm: async_sessionmaker[AsyncSession],
) -> tuple[Project, Project]:
    """One approved DOR for E-1 (10 h + 3 h overtime) on project 1, plus a DOR-day on a
    second project, and an office employee."""
    fe_user = await make_user("field_engineer")
    sup_user = await make_user("ofs_superintendent")
    p, rates = await _setup(sm, [fe_user, sup_user])
    await _opening(sm, "ITM-1", "WH-RKN", 4, 24 * M)
    fe, sup = await login(fe_user), await login(sup_user)
    today = today_jakarta()
    body = _dor(
        rates,
        crew=[
            {
                "employee_code": "E-1",
                "rate_id": rates["fe"],
                "hours": "10",
                "overtime_hours": "3",
            }
        ],
    )
    dor = await _approve_dor(client, fe, sup, p, body)
    async with sm() as s:
        p2 = Project(
            number="PRJ-26-002",
            name="Pumping",
            company_name="PT KKKS",
            status="locked",
            revenue=D(500 * M),
            contingency_pct=D(5),
        )
        s.add(p2)
        await s.flush()
        s.add(ProjectWbs(project_id=p2.id, code="EXEC", name="Execution", seq=1))
        s.add(
            PayrollDay(
                employee_code="E-1",
                work_date=today - timedelta(days=1),
                project_id=p2.id,
                dor_id=uuid.UUID(dor["id"]),
                hours=D(12),
                overtime_hours=D(0),
            )
        )
        await s.execute(
            update(Employee)
            .where(Employee.code == "E-1")
            .values(
                basic_salary=D(10 * M),
                fixed_allowance=D(2 * M),
                ptkp_status="TK/0",
                npwp="0123456789012000",
            )
        )
        s.add(
            Employee(
                code="E-OFF",
                full_name="Citra Admin",
                position="Admin",
                is_field=False,
                basic_salary=D(8 * M),
                ptkp_status="K/1",
                nik="3171000000000001",
            )
        )
        await s.commit()
    return p, p2


async def test_payroll_days_allocation_journal_sod_and_payment(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    p1, p2 = await _approved_dor_days(client, make_user, login, sessionmaker)
    year, month = _period_for(today_jakarta())
    calculator = await make_user("hcbp_officer", "head_of_finance")
    ch = await login(calculator)
    r = await client.post("/api/payroll/runs", json={"year": year, "month": month}, headers=ch)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["employees"] == 2 and run["status"] == "calculated"
    detail = (await client.get(f"/api/payroll/runs/{run['id']}", headers=ch)).json()
    e1 = next(x for x in detail["payslips"] if x["employee_code"] == "E-1")
    off = next(x for x in detail["payslips"] if x["employee_code"] == "E-OFF")
    # Days and overtime from the approved DOR (+ the DOR-day on project 2).
    assert e1["site_days"] == 2 and e1["overtime_hours"] == "3.00"
    assert e1["field_allowance"] == "700000"
    assert e1["overtime_factor_hours"] == "5.50"
    assert e1["overtime_pay"] == str(round(D(10 * M) / 173 * D("5.5")))
    # BPJS on basic + fixed allowance (12 jt): Kesehatan at its cap.
    assert e1["kes_er"] == "480000" and e1["jht_ee"] == "240000"
    # Gross for TER includes employer Kesehatan, JKK and JKM.
    gross = 10 * M + 2 * M + 700_000 + int(e1["overtime_pay"])
    assert e1["gross"] == str(gross)
    taxable = gross + 480_000 + 208_800 + 36_000
    assert e1["taxable"] == str(taxable)
    assert D(e1["ter_rate"]) == calc.ter_rate(TER["A"], D(taxable))
    assert e1["pph21"] == str(int(D(taxable) * D(e1["ter_rate"]) / 100))
    assert off["ter_category"] == "B" and off["allocation"] == []
    # Field cost split by DOR days: one day each on two projects.
    alloc = {a["project_id"]: D(a["amount"]) for a in e1["allocation"]}
    assert set(alloc) == {str(p1.id), str(p2.id)}
    assert sum(alloc.values()) == D(e1["employer_cost"])
    assert abs(alloc[str(p1.id)] - alloc[str(p2.id)]) <= 1

    # HCBP edits the timesheet only with a reason.
    slip = (await client.get(f"/api/payroll/payslips/{e1['id']}", headers=ch)).json()
    days = [
        {
            "work_date": d["work_date"],
            "project_id": d["project_id"],
            "overtime_hours": d["overtime_hours"],
        }
        for d in slip["days"]
    ]
    extra = (today_jakarta() - timedelta(days=2)).isoformat()
    days.append({"work_date": extra, "project_id": str(p1.id), "overtime_hours": "0"})
    r = await client.put(
        f"/api/payroll/payslips/{e1['id']}/days", json={"days": days, "reason": "x"}, headers=ch
    )
    assert r.status_code == 422
    r = await client.put(
        f"/api/payroll/payslips/{e1['id']}/days",
        json={"days": days, "reason": "Hari mobilisasi tidak masuk DOR"},
        headers=ch,
    )
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["site_days"] == 3 and edited["field_allowance"] == "1050000"
    manual = next(d for d in edited["days"] if d["work_date"] == extra)
    assert manual["source"] == "manual" and manual["note"] == "Hari mobilisasi tidak masuk DOR"

    # Submitted by another HCBP; the calculator may not approve (SoD).
    sh = await login(await make_user("hcbp_officer"))
    sub = (await client.post(f"/api/payroll/runs/{run['id']}/submit", headers=sh)).json()
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=ch
    )
    assert r.status_code == 403 and r.json()["code"] == "SOD_PAYROLL_CALCULATOR"
    hof = await login(await make_user("head_of_finance"))
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=hof
    )
    assert r.status_code == 200, r.text
    approved = (await client.get(f"/api/payroll/runs/{run['id']}", headers=hof)).json()
    assert approved["status"] == "approved" and approved["journal_id"]

    # Journal: balanced; employer cost to 5100 per project and 6100 office.
    async with sessionmaker() as s:
        lines = await ledger.lines_of(s, uuid.UUID(approved["journal_id"]))
        debit = sum(x.debit for x in lines)
        assert debit == sum(x.credit for x in lines) == D(approved["employer_cost"])
        by_acc: dict[str, D] = {}
        for x in lines:
            by_acc[x.account_code] = by_acc.get(x.account_code, D(0)) + x.debit - x.credit
        assert {x.project_id for x in lines if x.account_code == "5100"} == {p1.id, p2.id}
        assert by_acc["2310"] == -D(approved["net"])
        assert by_acc["2220"] == -D(approved["pph21"])
        assert by_acc["2240"] == -(D(approved["employer_bpjs"]) + D(approved["employee_bpjs"]))
        assert by_acc["6100"] > 0
        assert {x.partner_code for x in lines if x.account_code == "2310"} == {"E-1", "E-OFF"}
    # Recalculation is no longer possible.
    r = await client.post(
        f"/api/payroll/runs/{run['id']}/recalculate", json={"reload": True}, headers=ch
    )
    assert r.status_code == 409 and r.json()["code"] == "RUN_LOCKED"

    # Paid through a payment run: full net, one transfer per employee.
    await _fund(sessionmaker, 200 * M)
    ap = await login(await make_user("ap_accountant"))
    due = (await client.get("/api/treasury/payment-runs/due-items", headers=ap)).json()
    assert [x["payroll_run_id"] for x in due["payrolls"]] == [run["id"]]
    bank = await _bank_id(sessionmaker)

    async def make(amount: str) -> Any:
        return await client.post(
            "/api/treasury/payment-runs",
            json={
                "pay_date": today_jakarta().isoformat(),
                "bank_account_id": bank,
                "items": [{"kind": "payroll", "payroll_run_id": run["id"], "amount": amount}],
            },
            headers=ap,
        )

    r = await make("1000")
    assert r.status_code == 409 and r.json()["code"] == "PAYROLL_AMOUNT"
    pr = (await make(approved["net"])).json()
    psub = (await client.post(f"/api/treasury/payment-runs/{pr['id']}/submit", headers=ap)).json()
    r = await client.post(
        f"/api/workflow/requests/{psub['request_id']}/approve", json={}, headers=hof
    )
    assert r.status_code == 200, r.text
    cashier = await login(await make_user("cashier"))
    r = await client.post(f"/api/treasury/payment-runs/{pr['id']}/release", headers=cashier)
    assert r.status_code == 200, r.text
    paid = (await client.get(f"/api/payroll/runs/{run['id']}", headers=hof)).json()
    assert paid["status"] == "paid" and paid["payment_run_id"] == pr["id"]
    f = await client.get(f"/api/treasury/payment-runs/{pr['id']}/bank-file", headers=cashier)
    assert b"Andi Operator" in f.content and b"Citra Admin" in f.content
    async with sessionmaker() as s:
        assert await ledger.balance(s, "2310") == 0
        total = (
            await s.execute(
                select(JournalLine.debit - JournalLine.credit).join(
                    JournalEntry, JournalEntry.id == JournalLine.entry_id
                )
            )
        ).scalars()
        assert sum(total, D(0)) == 0


async def test_payslip_access_control(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    await _approved_dor_days(client, make_user, login, sessionmaker)
    year, month = _period_for(today_jakarta())
    hcbp = await login(await make_user("hcbp_officer"))
    run = (
        await client.post("/api/payroll/runs", json={"year": year, "month": month}, headers=hcbp)
    ).json()
    sub = (await client.post(f"/api/payroll/runs/{run['id']}/submit", headers=hcbp)).json()
    hof_user = await make_user("head_of_finance")
    hof = await login(hof_user)
    r = await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=hof
    )
    assert r.status_code == 200, r.text
    detail = (await client.get(f"/api/payroll/runs/{run['id']}", headers=hcbp)).json()
    slip_id = next(x["id"] for x in detail["payslips"] if x["employee_code"] == "E-1")

    andi = await make_user("field_engineer")
    citra = await make_user("field_engineer")
    async with sessionmaker() as s:
        await s.execute(update(User).where(User.id == andi.id).values(employee_code="E-1"))
        await s.execute(update(User).where(User.id == citra.id).values(employee_code="E-OFF"))
        await s.commit()
    own = await login(andi)
    other = await login(citra)
    # The employee and HCBP see the payslip; colleagues and the approver do not.
    r = await client.get(f"/api/payroll/payslips/{slip_id}/pdf", headers=own)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert (
        await client.get(f"/api/payroll/payslips/{slip_id}/pdf", headers=hcbp)
    ).status_code == 200
    assert (
        await client.get(f"/api/payroll/payslips/{slip_id}/pdf", headers=other)
    ).status_code == 404
    assert (
        await client.get(f"/api/payroll/payslips/{slip_id}/pdf", headers=hof)
    ).status_code == 404
    assert (await client.get(f"/api/payroll/payslips/{slip_id}", headers=other)).status_code == 404
    mine = (await client.get("/api/payroll/my-payslips", headers=own)).json()
    assert [x["id"] for x in mine] == [slip_id]
    assert len((await client.get("/api/payroll/my-payslips", headers=other)).json()) == 1
    # Field engineers have no payroll rights: the run list is forbidden.
    assert (await client.get("/api/payroll/runs", headers=own)).status_code == 403
    # 1721-A1: the employee and HCBP only.
    a1 = await client.get(f"/api/payroll/a1/{year}/E-1", headers=own)
    assert a1.status_code == 200 and a1.content.startswith(b"%PDF")
    assert (await client.get(f"/api/payroll/a1/{year}/E-1", headers=other)).status_code == 404
    # Without the salary permission the export has no amounts.
    x = await client.get(f"/api/payroll/runs/{run['id']}/export", headers=hcbp)
    assert x.status_code == 200


async def test_december_runs_annual_reconciliation(
    sessionmaker: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
    masters: None,  # noqa: F811
) -> None:
    from app.auth.principal import load_principal

    user = await make_user("hcbp_officer")
    async with sessionmaker() as s:
        s.add(
            Employee(
                code="E-DEC",
                full_name="Dewi Desember",
                position="Engineer",
                basic_salary=D(15 * M),
                ptkp_status="K/0",
                npwp="0123456789012001",
            )
        )
        await s.commit()
    async with sessionmaker() as s:
        u = await s.get(User, user.id)
        assert u is not None
        actor = await load_principal(s, u)
        run = await payroll.calculate(s, actor, 2030, 12)
        slip = (await payroll.payslips_of(s, run.id))[0]
        assert slip.annual is not None and slip.ter_rate == 0
        r = await payroll.rules(s)
        expected = calc.annual(
            gross_year=slip.taxable,
            pension_year=slip.jht_ee + slip.jp_ee,
            withheld_before=D(0),
            months=1,
            ptkp=D(58_500_000),
            rules=r,
            has_tax_id=True,
        )
        assert slip.pph21 == expected.tax == D(slip.annual["tax"])
        assert slip.net == slip.gross - slip.kes_ee - slip.jht_ee - slip.jp_ee - slip.pph21
        await s.rollback()


def test_payslip_amounts_are_stripped_without_salary_permission() -> None:
    from app.payroll.models import Payslip
    from app.payroll.router import MONEY, _slip_out

    ps = Payslip(
        id=uuid.uuid4(),
        employee_code="E-1",
        employee_name="Andi",
        is_field=True,
        ptkp_status="TK/0",
        ter_category="A",
        site_days=2,
        overtime_hours=D(3),
        net=D(9 * M),
    )
    hidden = _slip_out(ps, False)
    assert not set(MONEY) & set(hidden) and "allocation" not in hidden
    assert _slip_out(ps, True)["net"] == str(9 * M)
