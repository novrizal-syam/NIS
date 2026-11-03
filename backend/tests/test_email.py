import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import RefreshToken, User, UserInvite
from app.auth.password_reset import PasswordReset
from app.core.config import get_settings
from app.services import email, email_templates
from app.services.email_log import EmailLog
from tests.conftest import PASSWORD

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
GENERIC = "Jika email terdaftar dan aktif"


@pytest.fixture
def smtp_outbox(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(get_settings(), "email_provider", "smtp")
    monkeypatch.setattr(get_settings(), "smtp_host", "mail.test")
    monkeypatch.setattr(email, "_smtp_send", sent.append)
    return sent


def _token_from(msg: EmailMessage, path: str) -> str:
    body = msg.get_body(preferencelist=("plain",))
    assert body is not None
    text = body.get_content()
    assert f"{path}?token=" in text
    return text.split(f"{path}?token=", 1)[1].split()[0]


def test_templates_are_escaped_and_branded() -> None:
    m = email_templates.invite("<b>Budi</b>", "TOKEN123", 72)
    assert "&lt;b&gt;Budi&lt;/b&gt;" in m.html and "<b>Budi</b>" not in m.html
    assert "/activate?token=TOKEN123" in m.html and "72 jam" in m.html
    assert "Abaikan email ini" in m.html
    assert "Dikirim oleh Nustrad ERP untuk PT Global Energi KITA" in m.html
    assert "#FFBD52" in m.html and "#1A1A1A" in m.html  # gold button, ink label
    assert "nustrad-logo-primary.png" in m.html
    r = email_templates.password_reset("Budi", "T", 60)
    assert "/reset-password?token=T" in r.text and "60 menit" in r.html


async def test_not_configured_shows_link_and_logs(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    assert email.provider() is None
    h = await login(await make_user("admin"))
    res = await client.post(
        "/api/users",
        json={"email": "baru@gek.co.id", "full_name": "Baru", "roles": ["engineer"]},
        headers=h,
    )
    link = res.json()["activation_link"]
    assert link.startswith("http://localhost:5173/activate?token=")
    token = link.split("token=")[1]
    async with sessionmaker() as s:
        row = (await s.execute(select(EmailLog))).scalar_one()
        assert (row.to, row.kind, row.status, row.error) == (
            "baru@gek.co.id",
            "invite",
            "not_configured",
            None,
        )
        invite = (await s.execute(select(UserInvite))).scalar_one()
        assert invite.token_hash != token and token not in invite.token_hash  # stored hashed
    listed = (await client.get("/api/users?q=baru", headers=h)).json()["items"][0]
    assert listed["last_email"]["status"] == "not_configured"


async def test_invite_email_sent_without_token_in_log(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    smtp_outbox: list[EmailMessage],
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    h = await login(await make_user("admin"))
    res = await client.post(
        "/api/users",
        json={"email": "baru@gek.co.id", "full_name": "Baru", "roles": ["engineer"]},
        headers=h,
    )
    assert res.json()["activation_link"] is None  # configured: link only goes by email
    msg = smtp_outbox[0]
    assert msg["To"] == "baru@gek.co.id" and msg["Subject"] == "Aktifkan akun Nustrad ERP Anda"
    token = _token_from(msg, "/activate")
    ok = await client.post(
        "/api/auth/invite/accept", json={"token": token, "password": "GunungSalak-2026"}
    )
    assert ok.status_code == 200
    async with sessionmaker() as s:
        logs = (await s.execute(select(EmailLog))).scalars().all()
        assert [log.status for log in logs] == ["sent"]
        assert all(token not in (log.error or "") and token not in log.to for log in logs)


async def test_failed_send_is_logged_not_raised(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    monkeypatch.setattr(get_settings(), "email_provider", "smtp")
    monkeypatch.setattr(get_settings(), "smtp_host", "mail.test")

    def boom(_: EmailMessage) -> None:
        raise ConnectionRefusedError("koneksi ditolak")

    monkeypatch.setattr(email, "_smtp_send", boom)
    h = await login(await make_user("admin"))
    res = await client.post(
        "/api/users",
        json={"email": "baru@gek.co.id", "full_name": "Baru", "roles": ["engineer"]},
        headers=h,
    )
    assert res.status_code == 201
    async with sessionmaker() as s:
        row = (await s.execute(select(EmailLog))).scalar_one()
        assert row.status == "failed" and "koneksi ditolak" in (row.error or "")


async def test_resend_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "email_provider", "resend")
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_test")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content
        return httpx.Response(200, json={"id": "abc"})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    result = await email.send_email("a@gek.co.id", "Subjek", "<p>x</p>", "x")
    assert result.status == "sent" and seen["auth"] == "Bearer re_test"
    assert b'"to":["a@gek.co.id"]' in seen["body"]  # type: ignore[operator]


async def test_forgot_password_flow(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    smtp_outbox: list[EmailMessage],
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    user = await make_user("engineer", email="budi@gek.co.id")
    await login(user)  # an active session that the reset must end
    known = await client.post("/api/auth/forgot-password", json={"email": "BUDI@gek.co.id"})
    unknown = await client.post("/api/auth/forgot-password", json={"email": "tidak.ada@gek.co.id"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() and GENERIC in known.json()["message"]
    assert len(smtp_outbox) == 1  # only the real account gets mail

    first = _token_from(smtp_outbox[0], "/reset-password")
    await client.post("/api/auth/forgot-password", json={"email": "budi@gek.co.id"})
    second = _token_from(smtp_outbox[1], "/reset-password")
    # A newer request cancels the older link.
    old = await client.post(
        "/api/auth/reset-password", json={"token": first, "password": "GunungSalak-2026"}
    )
    assert old.status_code == 410 and old.json()["code"] == "RESET_INVALID"
    weak = await client.post(
        "/api/auth/reset-password", json={"token": second, "password": "lemah"}
    )
    assert weak.status_code == 422
    ok = await client.post(
        "/api/auth/reset-password", json={"token": second, "password": "GunungSalak-2026"}
    )
    assert ok.status_code == 204
    again = await client.post(
        "/api/auth/reset-password", json={"token": second, "password": "GunungSalak-2027"}
    )
    assert again.json()["code"] == "RESET_INVALID"  # single use

    async with sessionmaker() as s:
        assert all(
            r.revoked_at
            for r in (
                await s.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
            ).scalars()
        )
        hashes = [r.token_hash for r in (await s.execute(select(PasswordReset))).scalars()]
        assert second not in hashes and first not in hashes
    assert (
        await client.post(
            "/api/auth/login", json={"email": "budi@gek.co.id", "password": "GunungSalak-2026"}
        )
    ).status_code == 200
    assert (
        await client.post("/api/auth/login", json={"email": "budi@gek.co.id", "password": PASSWORD})
    ).status_code == 401


async def test_reset_token_expires(
    client: AsyncClient,
    make_user: MakeUser,
    smtp_outbox: list[EmailMessage],
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await make_user("engineer", email="budi@gek.co.id")
    await client.post("/api/auth/forgot-password", json={"email": "budi@gek.co.id"})
    token = _token_from(smtp_outbox[0], "/reset-password")
    async with sessionmaker() as s:
        row = (await s.execute(select(PasswordReset))).scalar_one()
        assert row.expires_at - row.created_at <= timedelta(minutes=60, seconds=5)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    res = await client.post(
        "/api/auth/reset-password", json={"token": token, "password": "GunungSalak-2026"}
    )
    assert res.json()["code"] == "RESET_EXPIRED"


async def test_forgot_password_rate_limit(client: AsyncClient, make_user: MakeUser) -> None:
    await make_user("engineer", email="budi@gek.co.id")
    for email_ in ("budi@gek.co.id", "tidak.ada@gek.co.id"):  # same limit for unknown emails
        for _ in range(3):
            assert (
                await client.post("/api/auth/forgot-password", json={"email": email_})
            ).status_code == 200
        fourth = await client.post("/api/auth/forgot-password", json={"email": email_})
        assert fourth.status_code == 429 and fourth.json()["code"] == "TOO_MANY_REQUESTS"


async def test_test_email_is_super_admin_only(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    admin = await login(await make_user("admin"))
    assert (await client.post("/api/admin/email/test", headers=admin)).status_code == 403
    sa = await login(await make_user("super_admin", email="sa@gek.co.id"))
    res = (await client.post("/api/admin/email/test", headers=sa)).json()
    assert res == {"status": "not_configured", "error": None, "to": "sa@gek.co.id"}


@pytest.mark.skipif(
    not os.environ.get("MAILPIT_URL"), reason="set MAILPIT_URL (and SMTP to Mailpit) to run"
)
async def test_send_through_mailpit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev check against a real Mailpit: SMTP_HOST/PORT from the environment."""
    monkeypatch.setattr(get_settings(), "email_provider", "smtp")
    base = os.environ["MAILPIT_URL"].rstrip("/")
    async with httpx.AsyncClient() as http:
        await http.delete(f"{base}/api/v1/messages")
        m = email_templates.password_reset("Budi", "TOKEN-MAILPIT", 60)
        assert (
            await email.send_email("budi@gek.co.id", m.subject, m.html, m.text)
        ).status == "sent"
        listed = (await http.get(f"{base}/api/v1/messages")).json()
        assert listed["total"] == 1 and listed["messages"][0]["Subject"] == m.subject
