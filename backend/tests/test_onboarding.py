from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.services.audit import AuditLog
from app.services.storage import Storage

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.7\n%%EOF"


async def test_first_login_order(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    # Cashier: role requires 2FA, so all four steps apply.
    user = await make_user("cashier", must_change_password=True, two_factor=False, onboarded=False)
    h = await login(user)
    me = (await client.get("/api/auth/me", headers=h)).json()
    assert me["pending"] == ["change_password", "accept_privacy", "setup_totp", "complete_profile"]

    async with sessionmaker() as s:
        u = await s.get(User, user.id)
        assert u is not None
        u.must_change_password, u.totp_enabled = False, True
        await s.commit()
    blocked = await client.get("/api/auth/ping", headers=h)
    assert blocked.json()["code"] == "PRIVACY_ACCEPTANCE_REQUIRED"

    notice = (await client.get("/api/auth/privacy", headers=h)).json()
    assert "27 Tahun 2022" in notice["text"]
    stale = await client.post("/api/auth/privacy/accept", json={"version": "lama"}, headers=h)
    assert stale.status_code == 409
    assert (
        await client.post(
            "/api/auth/privacy/accept", json={"version": notice["version"]}, headers=h
        )
    ).status_code == 204

    assert (await client.get("/api/auth/ping", headers=h)).json()["code"] == "PROFILE_REQUIRED"
    bad = await client.put("/api/auth/profile", json={"phone": "abc"}, headers=h)
    assert bad.status_code == 422
    assert (
        await client.put("/api/auth/profile", json={"phone": "+62 812-1234-5678"}, headers=h)
    ).status_code == 200
    assert (await client.get("/api/auth/ping", headers=h)).status_code == 200

    me = (await client.get("/api/auth/me", headers=h)).json()
    assert me["tour_done"] is False and me["phone"] == "+62 812-1234-5678"
    assert (await client.post("/api/auth/tour/done", headers=h)).status_code == 204
    assert (await client.get("/api/auth/me", headers=h)).json()["tour_done"] is True

    async with sessionmaker() as s:
        log = (
            await s.execute(select(AuditLog).where(AuditLog.action == "privacy_accepted"))
        ).scalar_one()
        assert log.after == {"version": notice["version"]}
        u = await s.get(User, user.id)
        assert u is not None and u.privacy_accepted_at is not None


async def test_profile_photo_and_signature_must_be_own_images(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    me_user = await make_user("engineer", onboarded=False)
    other = await make_user("engineer")
    h = await login(me_user)

    async def upload(
        owner: User, data: bytes, name: str, headers: dict[str, str]
    ) -> dict[str, str]:
        res = await client.post(
            "/api/attachments",
            data={"entity_type": "user_profile", "entity_id": str(owner.id)},
            files={"file": (name, data)},
            headers=headers,
        )
        return res.json()  # type: ignore[no-any-return]

    photo = await upload(me_user, PNG, "foto.png", h)
    # While onboarding the user can preview their own upload...
    own = await client.get(f"/api/attachments/{photo['id']}/content", headers=h)
    assert own.status_code == 200 and own.content == PNG
    pdf = await upload(me_user, PDF, "ttd.pdf", h)
    # Cannot upload into someone else's profile.
    res = await client.post(
        "/api/attachments",
        data={"entity_type": "user_profile", "entity_id": str(other.id)},
        files={"file": ("x.png", PNG)},
        headers=h,
    )
    assert res.status_code == 403
    theirs = await upload(other, PNG, "theirs.png", await login(other))
    # ...but not other files until onboarding is done.
    peek = await client.get(f"/api/attachments/{theirs['id']}/content", headers=h)
    assert peek.status_code == 403 and peek.json()["code"] == "PRIVACY_ACCEPTANCE_REQUIRED"

    assert (
        await client.put(
            "/api/auth/profile",
            json={"phone": "08123456789", "signature_attachment_id": pdf["id"]},
            headers=h,
        )
    ).json()["code"] == "IMAGE_REQUIRED"
    assert (
        await client.put(
            "/api/auth/profile",
            json={"phone": "08123456789", "photo_attachment_id": theirs["id"]},
            headers=h,
        )
    ).json()["code"] == "ATTACHMENT_NOT_OWNED"
    ok = await client.put(
        "/api/auth/profile",
        json={"phone": "08123456789", "photo_attachment_id": photo["id"]},
        headers=h,
    )
    assert ok.status_code == 200
    assert (await client.get("/api/auth/me", headers=h)).json()["photo_attachment_id"] == photo[
        "id"
    ]
