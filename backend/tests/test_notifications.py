import uuid
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from email.message import EmailMessage

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.auth.principal import Principal
from app.master.models import Vendor
from app.notifications import service
from app.notifications.models import Notification
from app.services import email
from app.workflow import engine

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
PrincipalOf = Callable[..., Awaitable[Principal]]


async def _notes(s: AsyncSession, user: User) -> list[Notification]:
    return list(
        (
            await s.execute(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at)
            )
        ).scalars()
    )


async def test_workflow_events_notify_the_right_people(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    eng, hoo = await make_user("engineer"), await make_user("head_of_operation")
    async with sessionmaker() as s:
        req = await engine.submit(
            s,
            await principal_of(eng, s),
            doc_type="purchase_requisition",
            doc_id=uuid.uuid4(),
            doc_number="PR-26-031",
            title="Seal kit",
            amount=12_500_000,
        )
        await s.commit()
        incoming = await _notes(s, hoo)
        assert [n.title for n in incoming] == ["Persetujuan baru: PR-26-031"]
        assert "Rp 12.500.000" in incoming[0].body and incoming[0].link == f"/persetujuan/{req.id}"
        assert incoming[0].email_status == "pending"
        assert await _notes(s, eng) == []  # the requester is not notified of own submission

        await engine.reject(s, await principal_of(hoo, s), req.id, "Lampirkan spesifikasi")
        await s.commit()
        returned = await _notes(s, eng)
        assert (
            returned[0].title == "PR-26-031 dikembalikan"
            and "Lampirkan spesifikasi" in returned[0].body
        )


async def test_expiry_alert_buckets_and_dedupe(
    make_user: MakeUser, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    po = await make_user("procurement_officer")
    today = date(2026, 10, 1)
    async with sessionmaker() as s:
        s.add(
            Vendor(
                code="V-1",
                name="PT Uji",
                category="chemicals",
                legal_docs=[
                    {"name": "SIUP", "number": "1", "expiry_date": str(today + timedelta(days=45))},
                    {"name": "NIB", "number": "2", "expiry_date": str(today - timedelta(days=1))},
                    {
                        "name": "Akta",
                        "number": "3",
                        "expiry_date": str(today + timedelta(days=200)),
                    },
                ],
            )
        )
        await s.commit()
        assert await service.run_expiry_alerts(s, today) == 2
        await s.commit()
        assert await service.run_expiry_alerts(s, today) == 0  # deduplicated
        titles = sorted(n.title for n in await _notes(s, po))
        assert titles == ["NIB V-1 sudah kedaluwarsa", "SIUP V-1 berakhir dalam 45 hari"]
        # Crossing into the 30-day bucket alerts again.
        assert await service.run_expiry_alerts(s, today + timedelta(days=16)) == 1


@pytest.mark.parametrize(
    ("days", "expected"),
    [(91, None), (90, 90), (61, 90), (60, 60), (30, 30), (1, 30), (0, 0), (-5, 0)],
)
def test_bucket(days: int, expected: int | None) -> None:
    assert service.bucket(days) == expected


async def test_email_outbox_sends_after_commit_and_retries(
    make_user: MakeUser,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user("engineer", email="budi@gek.co.id")
    sent: list[EmailMessage] = []
    fail = {"on": True}

    def fake_send(msg: EmailMessage) -> None:
        if fail["on"]:
            raise OSError("SMTP down")
        sent.append(msg)

    monkeypatch.setattr(email, "_send_sync", fake_send)
    async with sessionmaker() as s:
        await service.notify(
            s, [user.id], kind="test", title="Uji email", body="Isi", link="/persetujuan"
        )
        await s.commit()
        assert await service.deliver_email_outbox(s) == 0
        await s.commit()
        note = (await _notes(s, user))[0]
        assert (
            note.email_status == "pending"
            and note.email_attempts == 1
            and note.email_error == "SMTP down"
        )

        fail["on"] = False
        assert await service.deliver_email_outbox(s) == 1
        await s.commit()
        await s.refresh(note)
        assert note.email_status == "sent"
    msg = sent[0]
    assert msg["To"] == "Pengguna Uji <budi@gek.co.id>" and msg["Subject"] == "Uji email"
    assert "http://localhost:5173/persetujuan" in msg.get_content()


async def test_notifications_api(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    a, b = await make_user("engineer"), await make_user("engineer")
    async with sessionmaker() as s:
        await service.notify(s, [a.id], kind="test", title="Satu")
        await service.notify(s, [a.id], kind="test", title="Dua")
        await service.notify(s, [b.id], kind="test", title="Milik B")
        await s.commit()
    h = await login(a)
    page = (await client.get("/api/notifications", headers=h)).json()
    assert page["unread"] == 2 and {i["title"] for i in page["items"]} == {"Satu", "Dua"}
    first = page["items"][0]["id"]
    assert (await client.post(f"/api/notifications/{first}/read", headers=h)).status_code == 204
    assert (await client.get("/api/notifications/count", headers=h)).json() == {"unread": 1}
    # Cannot touch someone else's notification.
    hb = await login(b)
    other = (await client.get("/api/notifications", headers=hb)).json()["items"][0]["id"]
    assert (await client.post(f"/api/notifications/{other}/read", headers=h)).status_code == 404
    assert (await client.post("/api/notifications/read-all", headers=h)).status_code == 204
    assert (await client.get("/api/notifications/count", headers=h)).json() == {"unread": 0}
