"""Phase 10c: client portal (own tickets and invoices only, sign a ticket) and vendor portal
(RFQ quote, invoice upload -> AP decision, invoice and payment status)."""

from collections.abc import Awaitable, Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.master.models import Client, Vendor
from app.procurement.models import Rfq, RfqQuote
from app.services.numbering import today_jakarta
from app.services.storage import Storage
from tests.test_billing import _png, _ticketed
from tests.test_inventory import _issued_po, _project, masters  # noqa: F401

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF"
M = 1_000_000


async def _portal_user(
    client: AsyncClient, make_user: MakeUser, login: Login, role: str, **link: str
) -> dict[str, str]:
    admin = await login(await make_user("admin"))
    u = await make_user(role)
    r = await client.put(f"/api/portal/links/{u.id}", json=link, headers=admin)
    assert r.status_code == 200, r.text
    return await login(u)


async def test_client_portal_sees_and_signs_only_own_tickets(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    _, tk, _ba = await _ticketed(client, make_user, login, sessionmaker)
    async with sessionmaker() as s:
        s.add(Client(code="C-OTHER", name="PT Lain"))
        await s.commit()
    rep = await _portal_user(client, make_user, login, "client_rep", client_code="C-1")
    other = await _portal_user(client, make_user, login, "client_rep", client_code="C-OTHER")
    assert (await client.get("/api/portal/me", headers=rep)).json()["client"]["code"] == "C-1"
    mine = (await client.get("/api/portal/client/tickets", headers=rep)).json()
    assert [t["number"] for t in mine] == [tk["number"]] and mine[0]["can_sign"]
    assert (await client.get("/api/portal/client/tickets", headers=other)).json() == []
    assert (
        await client.get(f"/api/portal/client/tickets/{tk['id']}", headers=other)
    ).status_code == 404
    detail = (await client.get(f"/api/portal/client/tickets/{tk['id']}", headers=rep)).json()
    assert len(detail["lines"]) == 3
    r = await client.post(
        f"/api/portal/client/tickets/{tk['id']}/sign",
        json={"signer_name": "Budi KKKS", "signature": _png()},
        headers=rep,
    )
    assert r.status_code == 200 and r.json()["status"] == "signed", r.text
    assert (await client.get("/api/portal/client/invoices", headers=rep)).json() == []
    # Vendor endpoints are closed to client users, and internal APIs stay closed.
    assert (await client.get("/api/portal/vendor/rfqs", headers=rep)).status_code == 403
    assert (await client.get("/api/finance/vendor-invoices", headers=rep)).status_code == 403
    assert (await client.get("/api/dashboard/process-map", headers=rep)).json()["cells"] == []


async def test_vendor_portal_quote_upload_and_status(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    ap_user = await make_user("ap_accountant")  # _issued_po needs a user to exist
    p = await _project(sessionmaker)
    po = await _issued_po(sessionmaker, p, "EQUIP-RENT", [(None, "Sewa genset (hari)", 10, 2 * M)])
    async with sessionmaker() as s:
        s.add(Vendor(code="V-B", name="PT Beta", category="rental"))
        rfq = Rfq(number="RFQ-T-1", pr_id=po.pr_id, category="rental", status="open")
        s.add(rfq)
        await s.flush()
        q = RfqQuote(rfq_id=rfq.id, vendor_code="V-A", status="invited")
        s.add(q)
        await s.commit()
        qid = str(q.id)
    va = await _portal_user(client, make_user, login, "vendor", vendor_code="V-A")
    vb = await _portal_user(client, make_user, login, "vendor", vendor_code="V-B")
    rfqs = (await client.get("/api/portal/vendor/rfqs", headers=va)).json()
    assert [(x["rfq"], x["status"]) for x in rfqs] == [("RFQ-T-1", "invited")]
    assert (await client.get("/api/portal/vendor/rfqs", headers=vb)).json() == []
    assert (await client.get(f"/api/portal/vendor/rfqs/{qid}", headers=vb)).status_code == 404
    lines = (await client.get(f"/api/portal/vendor/rfqs/{qid}", headers=va)).json()["lines"]
    r = await client.put(
        f"/api/portal/vendor/rfqs/{qid}",
        json={"unit_prices": {str(lines[0]["seq"]): "1900000"}, "delivery_days": 7},
        headers=va,
    )
    assert r.status_code == 200 and r.json()["total"] == str(19 * M), r.text

    def form(po_number: str) -> dict[str, Any]:
        return {
            "data": {
                "po_number": po_number,
                "invoice_no": "INV/A/77",
                "invoice_date": today_jakarta().isoformat(),
                "amount": "8000000",
            },
            "files": {"file": ("inv.pdf", PDF, "application/pdf")},
        }

    r = await client.post("/api/portal/vendor/invoices", headers=vb, **form(po.number))
    assert r.status_code == 422 and r.json()["code"] == "PO_INVALID"
    r = await client.post("/api/portal/vendor/invoices", headers=va, **form(po.number))
    assert r.status_code == 200, r.text
    sub_id = r.json()["id"]
    ap = await login(ap_user)
    queue = (await client.get("/api/portal/submissions", headers=ap)).json()
    assert [x["id"] for x in queue] == [sub_id]
    # AP can open the uploaded PDF; another vendor cannot.
    att = queue[0]["attachment_id"]
    assert (await client.get(f"/api/attachments/{att}/content", headers=ap)).status_code == 200
    assert (await client.get(f"/api/attachments/{att}/content", headers=vb)).status_code == 404
    r = await client.post(
        f"/api/portal/submissions/{sub_id}/decide",
        json={"reject_reason": "Faktur pajak belum dilampirkan"},
        headers=ap,
    )
    assert r.json()["status"] == "rejected"
    status = (await client.get("/api/portal/vendor/invoices", headers=va)).json()
    assert status["submissions"][0]["reject_reason"] == "Faktur pajak belum dilampirkan"
    assert (await client.get("/api/portal/vendor/invoices", headers=vb)).json()["submissions"] == []
    # Unlinked vendor accounts get nothing.
    plain = await login(await make_user("vendor"))
    assert (await client.get("/api/portal/vendor/rfqs", headers=plain)).status_code == 403
