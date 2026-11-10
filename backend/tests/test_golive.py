"""Phase 10f: go-live checklist, opening-balance template and dry run."""

import io
from collections.abc import Awaitable, Callable

from httpx import AsyncClient, Response
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.finance.models import JournalEntry
from app.master.models import Asset, Client
from tests.test_inventory import masters  # noqa: F401
from tests.test_ledger import _opening_book

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


async def test_checklist_reports_what_is_missing(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    fe = await login(await make_user("field_engineer"))
    r = await client.get("/api/go-live/checklist", headers=fe)
    assert r.status_code == 403 and r.json()["code"] == "GO_LIVE_FORBIDDEN"
    admin = await login(await make_user("super_admin"))
    got = (await client.get("/api/go-live/checklist", headers=admin)).json()
    items = {i["key"]: i for i in got["items"]}
    auto = [i for i in got["items"] if i["ok"] is not None]
    assert not got["ready"] and got["total"] == len(auto)
    assert items["demo"]["ok"] is True
    assert items["opening"]["ok"] is False and items["environment"]["ok"] is False
    assert items["backup"]["ok"] is None  # manual check outside the application
    assert "Direktur" in items["roles"]["detail"]  # no director yet
    await make_user("director", "head_of_finance", "lead_controller", "ap_accountant")
    await make_user("cashier")
    got = (await client.get("/api/go-live/checklist", headers=admin)).json()
    assert next(i for i in got["items"] if i["key"] == "roles")["ok"] is True


async def test_opening_template_and_dry_run_then_post(
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
    r = await client.get("/api/ledger/opening/template", headers=lc)
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Petunjuk", "GL", "AR", "AP", "Stock", "Assets", "Referensi"]
    assert [c.value for c in wb["AR"][1]] == [
        "client",
        "invoice_no",
        "invoice_date",
        "due_date",
        "amount",
    ]
    refs = {(row[0], row[1]) for row in wb["Referensi"].iter_rows(min_row=2, values_only=True)}
    assert ("klien", "C-OB") in refs and ("aset", "AST-OB") in refs
    assert ("akun", "1210") not in refs  # control accounts come from their own sheets

    async def post(dry: bool) -> Response:
        return await client.post(
            "/api/ledger/opening",
            data={"as_of": "2026-09-30", "dry_run": str(dry).lower()},
            files={"file": ("saldo-awal.xlsx", _opening_book(), "application/octet-stream")},
            headers=lc,
        )

    r = await post(True)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["dry_run"] and preview["journal"] is None and preview["ar_items"] == 1
    async with sessionmaker() as s:
        assert (await s.execute(select(func.count()).select_from(JournalEntry))).scalar_one() == 0
    assert (await client.get("/api/ledger/opening", headers=lc)).json()["opening_date"] is None
    r = await post(False)
    assert r.status_code == 200 and r.json()["journal"] and not r.json()["dry_run"]
    assert preview["total"] == r.json()["total"]
