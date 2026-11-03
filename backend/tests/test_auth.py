from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import RefreshToken, User
from app.auth.security import create_access_token
from app.services.audit import AuditLog
from tests.conftest import PASSWORD

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
COOKIE = "nustrad_refresh"


async def _login(
    client: AsyncClient, email: str, password: str = PASSWORD, **extra: str
) -> Response:
    return await client.post(
        "/api/auth/login", json={"email": email, "password": password, **extra}
    )


async def test_login_success_sets_httponly_refresh_cookie(
    client: AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user("engineer")
    res = await _login(client, user.email.upper())  # email is case-insensitive
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    cookie = res.headers["set-cookie"]
    assert COOKIE in cookie and "HttpOnly" in cookie and "Path=/api/auth" in cookie


async def test_wrong_password_and_unknown_email_look_the_same(
    client: AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user("engineer")
    a = await _login(client, user.email, "salah-total-1")
    b = await _login(client, "tidak.ada@gek.co.id", "salah-total-1")
    assert a.status_code == b.status_code == 401
    assert (
        a.json()
        == b.json()
        == {
            "code": "INVALID_CREDENTIALS",
            "message": "Email atau kata sandi salah.",
        }
    )


async def test_account_locks_after_five_failures(
    client: AsyncClient, make_user: MakeUser, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    user = await make_user("engineer")
    for _ in range(4):
        assert (await _login(client, user.email, "salah-total-1")).status_code == 401
    fifth = await _login(client, user.email, "salah-total-1")
    assert fifth.status_code == 423
    assert fifth.json()["code"] == "ACCOUNT_LOCKED"
    # Even the right password is refused while locked.
    locked = await _login(client, user.email)
    assert locked.status_code == 423

    async with sessionmaker() as s:
        failures = (
            (await s.execute(select(AuditLog).where(AuditLog.action == "login_failed")))
            .scalars()
            .all()
        )
        assert len(failures) == 5
        # After the lock expires the right password works and resets the counter.
        db_user = await s.get(User, user.id)
        assert db_user is not None
        db_user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    assert (await _login(client, user.email)).status_code == 200
    async with sessionmaker() as s:
        db_user = await s.get(User, user.id)
        assert db_user is not None and db_user.failed_login_count == 0


async def test_success_resets_failure_counter(client: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user("engineer")
    for _ in range(4):
        await _login(client, user.email, "salah-total-1")
    assert (await _login(client, user.email)).status_code == 200
    for _ in range(4):
        assert (await _login(client, user.email, "salah-total-1")).status_code == 401


async def test_inactive_user_cannot_login(
    client: AsyncClient, make_user: MakeUser, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    user = await make_user("engineer")
    async with sessionmaker() as s:
        u = await s.get(User, user.id)
        assert u is not None
        u.is_active = False
        await s.commit()
    res = await _login(client, user.email)
    assert res.status_code == 403
    assert res.json()["code"] == "ACCOUNT_INACTIVE"


async def test_refresh_rotates_and_detects_reuse(client: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user("engineer")
    await _login(client, user.email)
    first = client.cookies.get(COOKIE)
    assert first

    res = await client.post("/api/auth/refresh")
    assert res.status_code == 200
    second = client.cookies.get(COOKIE)
    assert second and second != first

    # Presenting the rotated (old) token again revokes the whole family.
    client.cookies.set(COOKIE, first, path="/api/auth")
    reuse = await client.post("/api/auth/refresh")
    assert reuse.status_code == 401
    assert reuse.json()["code"] == "REFRESH_INVALID"
    client.cookies.set(COOKIE, second, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_refresh_without_cookie(client: AsyncClient) -> None:
    res = await client.post("/api/auth/refresh")
    assert res.status_code == 401


async def test_logout_revokes_refresh_token(
    client: AsyncClient, make_user: MakeUser, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    user = await make_user("engineer")
    await _login(client, user.email)
    token = client.cookies.get(COOKIE)
    assert (await client.post("/api/auth/logout")).status_code == 204
    client.cookies.set(COOKIE, token or "", path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401
    async with sessionmaker() as s:
        rows = (await s.execute(select(RefreshToken))).scalars().all()
        assert rows and all(r.revoked_at is not None for r in rows)


async def test_expired_and_missing_access_token(client: AsyncClient, make_user: MakeUser) -> None:
    assert (await client.get("/api/auth/ping")).json()["code"] == "UNAUTHENTICATED"
    user = await make_user("engineer")
    token, _ = create_access_token(user.id, now=datetime.now(UTC) - timedelta(minutes=16))
    res = await client.get("/api/auth/ping", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert res.json()["code"] == "TOKEN_EXPIRED"
    bad = await client.get("/api/auth/ping", headers={"Authorization": "Bearer abc.def.ghi"})
    assert bad.json()["code"] == "INVALID_TOKEN"


async def test_forced_password_change_on_first_login(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    user = await make_user("engineer", must_change_password=True)
    headers = await login(user)

    blocked = await client.get("/api/auth/ping", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    me = await client.get("/api/auth/me", headers=headers)
    assert me.json()["pending"] == ["change_password"]

    weak = await client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "pendek"},
    )
    assert weak.status_code == 422
    assert weak.json()["code"] == "WEAK_PASSWORD"
    wrong = await client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": "keliru", "new_password": "KataSandiBaru-2026"},
    )
    assert wrong.json()["code"] == "INVALID_CURRENT_PASSWORD"

    ok = await client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "KataSandiBaru-2026"},
    )
    assert ok.status_code == 200
    new_headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert (await client.get("/api/auth/ping", headers=new_headers)).status_code == 200


async def test_totp_required_by_role(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    user = await make_user("cashier", two_factor=False)  # role requires 2FA
    headers = await login(user)
    blocked = await client.get("/api/auth/ping", headers=headers)
    assert blocked.json()["code"] == "TOTP_SETUP_REQUIRED"

    setup = await client.post("/api/auth/totp/setup", headers=headers)
    assert setup.status_code == 200
    body = setup.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["qr_svg"].startswith("<svg")
    totp = pyotp.TOTP(body["secret"])

    bad = await client.post("/api/auth/totp/verify", headers=headers, json={"code": "000000"})
    assert bad.status_code == 422
    good = await client.post("/api/auth/totp/verify", headers=headers, json={"code": totp.now()})
    assert good.status_code == 200 and len(good.json()["recovery_codes"]) == 10
    assert (await client.get("/api/auth/ping", headers=headers)).status_code == 200

    # From now on login needs a code, and a used code cannot be replayed.
    no_code = await _login(client, user.email)
    assert no_code.json()["code"] == "TOTP_REQUIRED"
    replay = await _login(client, user.email, totp_code=totp.now())
    assert replay.json()["code"] == "TOTP_INVALID"
    nxt = totp.at(datetime.now(UTC) + timedelta(seconds=30))
    assert (await _login(client, user.email, totp_code=nxt)).status_code == 200


async def test_totp_secret_is_encrypted_at_rest(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    user = await make_user("cashier", two_factor=False)
    headers = await login(user)
    secret = (await client.post("/api/auth/totp/setup", headers=headers)).json()["secret"]
    async with sessionmaker() as s:
        stored = (await s.get(User, user.id)).totp_secret_enc  # type: ignore[union-attr]
    assert stored and secret not in stored


@pytest.mark.parametrize("email", ["bukan-email", ""])
async def test_login_validation_in_indonesian(client: AsyncClient, email: str) -> None:
    res = await _login(client, email)
    assert res.status_code == 422
    assert res.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("Pendek1", "Kata sandi minimal 10 karakter."),
        ("hanyahurufsaja", "Kata sandi harus berisi huruf dan angka."),
        ("Budi-Santoso-2026", "Kata sandi tidak boleh memuat nama email Anda."),
    ],
)
def test_password_policy_messages(password: str, message: str) -> None:
    from app.auth.security import validate_password_policy
    from app.core.errors import AppError

    with pytest.raises(AppError) as err:
        validate_password_policy(password, email="budi@gek.co.id")
    assert message in err.value.message
    validate_password_policy("KataSandiAman-2026", email="budi@gek.co.id")
