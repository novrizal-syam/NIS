import io
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.reporting.access_review import build

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


async def test_rows_flags_and_sensitive_access(
    make_user: MakeUser, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    now = datetime.now(UTC)
    recent = await make_user("hcbp_officer", email="hcbp@gek.co.id")
    stale = await make_user("engineer", email="lama@gek.co.id")
    never = await make_user("cashier", email="baru@gek.co.id", two_factor=False)
    async with sessionmaker() as s:
        for uid, login, created in (
            (recent.id, now - timedelta(days=3), None),
            (stale.id, now - timedelta(days=120), None),
            (never.id, None, now - timedelta(days=100)),
        ):
            u = await s.get(User, uid)
            assert u is not None
            u.last_login_at = login
            if created:
                u.created_at = created
        await s.commit()
        rows = {r.email: r for r in await build(s, now)}
    assert rows["hcbp@gek.co.id"].sensitive == ["Gaji", "NIK", "NPWP pribadi", "Rekening bank"]
    assert (
        rows["hcbp@gek.co.id"].inactive_90 is False and rows["hcbp@gek.co.id"].days_since_login == 3
    )
    assert rows["lama@gek.co.id"].inactive_90 is True and rows["lama@gek.co.id"].sensitive == []
    # Never logged in, account older than 90 days: flagged; requires 2FA but not enabled.
    assert (
        rows["baru@gek.co.id"].inactive_90 is True
        and rows["baru@gek.co.id"].days_since_login is None
    )
    assert rows["baru@gek.co.id"].requires_2fa and not rows["baru@gek.co.id"].totp_enabled


async def test_api_and_exports(client: AsyncClient, make_user: MakeUser, login: Login) -> None:
    await make_user("engineer", email="lama@gek.co.id")
    lc = await login(await make_user("lead_controller"))
    data = (await client.get("/api/reports/access-review", headers=lc)).json()
    assert data["inactive_days"] == 90 and data["summary"]["users"] == 2
    xlsx = await client.get("/api/reports/access-review.xlsx", headers=lc)
    ws = load_workbook(io.BytesIO(xlsx.content)).active
    assert ws is not None and ws["A1"].value == "Nama" and ws["E1"].value == "Akses data sensitif"
    pdf = await client.get("/api/reports/access-review.pdf", headers=lc)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-type"] == "application/pdf"
    eng = await login(await make_user("engineer"))
    assert (await client.get("/api/reports/access-review", headers=eng)).status_code == 403
