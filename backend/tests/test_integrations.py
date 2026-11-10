"""Phase 10b: integration status (manual/file until credentials exist), WhatsApp outbox
(manual wa.me and live Cloud API), Coretax e-Faktur via PJAP (file and live), OpenAPI."""

import json
from collections.abc import Awaitable, Callable, Iterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.billing.models import CustomerInvoice
from app.core.config import get_settings
from app.core.openapi_meta import TAGS
from app.integrations import pjap, whatsapp
from app.integrations.models import WhatsAppMessage
from app.main import app as main_app
from app.master.models import Client
from app.notifications import service as notifications
from app.services.numbering import today_jakarta

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


@pytest.fixture
def live_whatsapp() -> Iterator[list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.TEST1"}]})

    s = get_settings()
    old = (s.whatsapp_phone_number_id, s.whatsapp_token)
    s.whatsapp_phone_number_id, s.whatsapp_token = "1234567890", "test-token"
    whatsapp.use_transport(httpx.MockTransport(handler))
    yield sent
    s.whatsapp_phone_number_id, s.whatsapp_token = old
    whatsapp.use_transport(None)


async def test_status_lists_every_integration_in_manual_mode(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    admin = await login(await make_user("admin"))
    r = await client.get("/api/integrations", headers=admin)
    assert r.status_code == 200, r.text
    modes = {i["key"]: i["mode"] for i in r.json()["integrations"]}
    assert modes == {
        "coretax_pjap": "file",
        "bank": "file",
        "psre": "manual",
        "emeterai": "manual",
        "smtp": "manual",
        "whatsapp": "manual",
    }
    r = await client.put(
        "/api/integrations/settings",
        json={"psre_provider": "privy", "emeterai_provider": "internal"},
        headers=admin,
    )
    assert r.status_code == 422 and r.json()["code"] == "PROVIDER_UNKNOWN"
    fe = await login(await make_user("field_engineer"))
    assert (await client.get("/api/integrations", headers=fe)).status_code == 403


async def test_whatsapp_manual_outbox_from_notifications(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    admin = await login(await make_user("admin"))
    r = await client.put(
        "/api/integrations/settings",
        json={"whatsapp_notify_kinds": ["disposition"]},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["settings"]["whatsapp.notify_kinds"] == ["disposition"]
    pic = await make_user("head_of_operation")
    async with sessionmaker() as s:
        await s.execute(update(User).where(User.id == pic.id).values(phone="0812-3456-7890"))
        await notifications.notify(
            s,
            [pic.id],
            kind="disposition",
            title="Disposisi SM-26-001",
            body="Siapkan tim",
            link="/surat/masuk/x",
        )
        await notifications.notify(s, [pic.id], kind="other_kind", title="Tidak ke WA")
        await s.commit()
    box = (await client.get("/api/integrations/whatsapp/outbox", headers=admin)).json()
    assert len(box) == 1 and box[0]["to"] == "6281234567890" and box[0]["status"] == "manual"
    assert box[0]["wa_link"].startswith("https://wa.me/6281234567890?text=%2ADisposisi")
    r = await client.post(f"/api/integrations/whatsapp/{box[0]['id']}/sent", headers=admin)
    assert r.json()["status"] == "sent"


async def test_whatsapp_live_delivery(
    sessionmaker: async_sessionmaker[AsyncSession], live_whatsapp: list[httpx.Request]
) -> None:
    async with sessionmaker() as s:
        m = await whatsapp.queue(s, "+62 811 000 111", "Halo dari Nustrad ERP")
        assert m is not None and m.status == "queued"
        assert await whatsapp.deliver(s) == 1
        await s.commit()
        row = (await s.execute(select(WhatsAppMessage))).scalar_one()
        assert row.status == "sent" and row.provider_ref == "wamid.TEST1"
    req = live_whatsapp[0]
    assert req.url.path == "/v20.0/1234567890/messages"
    assert req.headers["authorization"] == "Bearer test-token"
    assert json.loads(req.content)["to"] == "62811000111"


async def _faktur_invoice(sm: async_sessionmaker[AsyncSession]) -> str:
    async with sm() as s:
        s.add(Client(code="C-PJ", name="PT KKKS", npwp="0123456789012345"))
        await s.flush()
        inv = CustomerInvoice(
            number="INV-T-PJ",
            client_code="C-PJ",
            status="faktur_issued",
            invoice_date=today_jakarta(),
            due_date=today_jakarta() + timedelta(days=30),
            subtotal=Decimal(12_000_000),
            dpp_other=Decimal(11_000_000),
            ppn=Decimal(1_320_000),
            total=Decimal(13_320_000),
            faktur_number="04002600000001",
            faktur_date=today_jakarta(),
        )
        s.add(inv)
        await s.commit()
        return str(inv.id)


async def test_efaktur_file_mode_and_live_pjap(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    inv_id = await _faktur_invoice(sessionmaker)
    tax = await login(await make_user("tax_specialist"))
    r = await client.post(
        "/api/integrations/pjap/efaktur", json={"invoice_ids": [inv_id]}, headers=tax
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert b"<RefDesc>INV-T-PJ</RefDesc>" in r.content
    uploads: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        uploads.append(request)
        return httpx.Response(200, json={"reference": "PJAP-REF-9", "status": "accepted"})

    s = get_settings()
    s.pjap_base_url, s.pjap_api_key = "https://pjap.example.test/api", "k"
    pjap.use_transport(httpx.MockTransport(handler))
    try:
        r = await client.post(
            "/api/integrations/pjap/efaktur", json={"invoice_ids": [inv_id]}, headers=tax
        )
    finally:
        s.pjap_base_url, s.pjap_api_key = "", ""
        pjap.use_transport(None)
    assert r.status_code == 200 and r.json()["reference"] == "PJAP-REF-9"
    assert uploads[0].url.path == "/api/efaktur" and b"INV-T-PJ" in uploads[0].content


def test_openapi_documents_every_operation() -> None:
    # The running app (create_app() would re-register global session/storage providers).
    spec = main_app.openapi()
    names = {n for n, _ in TAGS}
    paths = {p: v for p, v in spec["paths"].items() if not p.startswith("/api/_")}  # test-only
    ops = [(p, m, o) for p, item in paths.items() for m, o in item.items()]
    assert len(ops) > 350
    untagged = [f"{m.upper()} {p}" for p, m, o in ops if not set(o.get("tags", [])) & names]
    assert untagged == []
    assert "Bahasa Indonesia" in spec["info"]["description"]
    exported = json.loads(
        (Path(__file__).resolve().parents[2] / "docs/api/openapi.json").read_text()
    )
    assert set(exported["paths"]) == set(paths), "run: python -m scripts.export_openapi"
