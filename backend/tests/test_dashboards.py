"""Phase 10a: process map (permission-filtered live counts), OKR actuals vs targets in
settings, role dashboards, monthly management pack PDF."""

import io
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.crm.models import Opportunity
from app.qhse.models import Incident
from app.services import ledger
from app.services.numbering import today_jakarta
from app.tax.models import TaxReturn

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal


async def _seed(sm: async_sessionmaker[AsyncSession], owner: User) -> None:
    today = today_jakarta()
    async with sm() as s:
        for lines in (
            [("1110", 5_000 * M, 0), ("4100", 0, 5_000 * M)],  # revenue 5 M
            [("5300", 4_000 * M, 0), ("1110", 0, 4_000 * M)],  # cost 4 M
        ):
            await ledger.post_journal(
                s,
                entry_date=today,
                description="uji",
                lines=[ledger.JLine(a, debit=D(dr), credit=D(cr)) for a, dr, cr in lines],
                source_type="test",
                source_id=uuid.uuid4().hex,
                by=None,
            )
        for n, (stage, won) in enumerate((("won", True), ("lost", False), ("lost", False))):
            s.add(
                Opportunity(
                    number=f"OPP-T-{n}",
                    company_name="PT KKKS",
                    title=f"Peluang {n}",
                    owner_id=owner.id,
                    stage=stage,
                    won_at=today if won else None,
                    lost_at=None if won else today,
                )
            )
        s.add(
            TaxReturn(
                year=today.year,
                month=1,
                tax_type="pph21",
                status="filed",
                pay_due=date(today.year, 2, 15),
                file_due=date(today.year, 2, 20),
                paid_on=date(today.year, 2, 16),  # one day late
                filed_on=date(today.year, 2, 18),
            )
        )
        s.add(
            Incident(
                number="INC-T-1",
                occurred_on=today,
                category="lost_time",
                description="Terpeleset di rig floor",
                lost_days=2,
            )
        )
        await s.commit()


async def test_okr_actuals_targets_and_role_dashboards(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    director_user = await make_user("director")
    await _seed(sessionmaker, director_user)
    director = await login(director_user)
    year = today_jakarta().year
    okr = (await client.get("/api/dashboard/okr", headers=director)).json()
    rows = {r["key"]: r for r in okr["rows"]}
    assert okr["figures"]["revenue"] == str(5_000 * M)
    assert (
        rows["win_rate_pct"]["actual"] == "33.3" and rows["win_rate_pct"]["status"] == "off_track"
    )
    assert (
        rows["net_margin_pct"]["actual"] == "20.0"
        and rows["net_margin_pct"]["status"] == "on_track"
    )
    assert rows["tax_penalties"]["actual"] == "1" and rows["tax_penalties"]["status"] == "off_track"
    assert rows["accidents"]["actual"] == "1"
    assert rows["revenue"]["year_target"] == str(25_000 * M)
    # Targets live in settings and are edited by the Director only.
    body = {
        **(await client.get(f"/api/dashboard/okr/targets/{year}", headers=director)).json(),
        "win_rate_pct": 30,
    }
    lc = await login(await make_user("lead_controller"))
    assert (
        await client.put(f"/api/dashboard/okr/targets/{year}", json=body, headers=lc)
    ).status_code == 403
    r = await client.put(f"/api/dashboard/okr/targets/{year}", json=body, headers=director)
    assert r.status_code == 200, r.text
    rows = {
        r["key"]: r
        for r in (await client.get("/api/dashboard/okr", headers=director)).json()["rows"]
    }
    assert rows["win_rate_pct"]["status"] == "on_track"
    # Role dashboards follow the user's roles.
    fin_user = await make_user("finance_officer")
    fin = await login(fin_user)
    assert (await client.get("/api/dashboard/roles", headers=fin)).json() == ["finance"]
    tiles = {
        t["key"]: t
        for t in (await client.get("/api/dashboard/roles/finance", headers=fin)).json()["tiles"]
    }
    assert tiles["cash"]["value"] == str(1_000 * M)
    assert (await client.get("/api/dashboard/roles/director", headers=fin)).status_code == 403
    assert "director" in (await client.get("/api/dashboard/roles", headers=director)).json()
    # OKR needs the reporting right.
    assert (await client.get("/api/dashboard/okr", headers=fin)).status_code == 403


async def test_process_map_counts_follow_permissions(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(sessionmaker, await make_user("director"))
    lc = await login(await make_user("lead_controller"))
    fe = await login(await make_user("field_engineer"))
    m = (await client.get("/api/dashboard/process-map", headers=lc)).json()
    assert m["lanes"] == ["revenue", "spend", "people", "finance"] and len(m["phases"]) == 6
    cells = {c["key"]: c for c in m["cells"]}
    assert cells["journals_month"]["count"] == 2 and cells["journals_month"]["link"].startswith(
        "/keuangan"
    )
    fe_keys = {
        c["key"]
        for c in (await client.get("/api/dashboard/process-map", headers=fe)).json()["cells"]
    }
    assert "dors_pending" in fe_keys and "journals_month" not in fe_keys


async def test_management_pack_pdf(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    director_user = await make_user("director")
    await _seed(sessionmaker, director_user)
    t = today_jakarta()
    r = await client.get(
        f"/api/dashboard/management-pack/{t.year}/{t.month}", headers=await login(director_user)
    )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "LAPORAN MANAJEMEN BULANAN" in text and f"OKR {t.year}" in text and "Laba rugi" in text
