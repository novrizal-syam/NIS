"""Phase 06: service tickets, disputes, invoices (tax, faktur, Coretax XML), receipts."""

import base64
import struct
import zlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree as ET

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.billing import receipt_service
from app.billing.models import ServiceTicket
from app.contract.models import Contract
from app.finance.models import JournalEntry, JournalLine
from app.master.models import Client
from app.project.models import ProjectMember
from app.services.numbering import today_jakarta
from app.services.storage import Storage
from app.setup import service as settings_store
from tests.test_dor import _dor, _setup
from tests.test_inventory import _opening, masters  # noqa: F401
from tests.test_maintenance_qhse import _approve_dor

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000
D = Decimal


def _png() -> str:
    """A 1x1 PNG as a data URL (what the signature pad sends)."""

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00"))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(raw).decode()


async def _journal(
    sm: async_sessionmaker[AsyncSession], source_id: str
) -> list[tuple[str, int, int]]:
    async with sm() as s:
        rows = await s.execute(
            select(JournalLine.account_code, JournalLine.debit, JournalLine.credit)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalEntry.source_id == source_id)
            .order_by(JournalEntry.number, JournalLine.seq)
        )
        return [(a, int(d), int(c)) for a, d, c in rows.tuples()]


async def _ticketed(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sm: async_sessionmaker[AsyncSession],
) -> tuple[Any, dict[str, Any], dict[str, str]]:
    fe_user = await make_user("field_engineer")
    sup_user = await make_user("ofs_superintendent")
    p, rates = await _setup(sm, [fe_user, sup_user])
    await _opening(sm, "ITM-1", "WH-RKN", 4, 24 * M)
    async with sm() as s:
        await s.execute(
            update(Client)
            .where(Client.code == "C-1")
            .values(npwp="02.345.678.9-012.000", email="ap@kkks.co.id", address="Jakarta")
        )
        await settings_store.put(s, settings_store.COMPANY, {"npwp": "01.234.567.8-901.000"}, None)
        await s.commit()
    fe, sup = await login(fe_user), await login(sup_user)
    day = today_jakarta() - timedelta(days=1)
    await _approve_dor(client, fe, sup, p, _dor(rates, report_date=day.isoformat()))
    ba = await login(await make_user("billing_admin"))
    r = await client.post(
        "/api/billing/tickets",
        json={"project_id": str(p.id), "date_from": day.isoformat(), "date_to": day.isoformat()},
        headers=ba,
    )
    assert r.status_code == 201, r.text
    return p, r.json(), ba


async def test_ticket_dispute_invoice_faktur_xml_and_receipt(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    p, tk, ba = await _ticketed(client, make_user, login, sessionmaker)
    assert tk["gross_value"] == "29033333" and len(tk["lines"]) == 3
    # The same DOR cannot be ticketed twice.
    r = await client.post(
        "/api/billing/tickets",
        json={"project_id": str(p.id), "date_from": tk["period_from"], "date_to": tk["period_to"]},
        headers=ba,
    )
    assert r.status_code == 422 and r.json()["code"] == "NO_DORS"

    # 1. Invoice from an unsigned ticket is rejected.
    today = today_jakarta().isoformat()
    r = await client.post(
        "/api/billing/invoices", json={"ticket_ids": [tk["id"]], "invoice_date": today}, headers=ba
    )
    assert r.status_code == 422 and r.json()["code"] == "TICKET_NOT_SIGNED"

    # 2. Client signs on the tablet and disputes the chemicals line.
    chem = next(x for x in tk["lines"] if x["kind"] == "consumable")
    r = await client.post(
        f"/api/billing/tickets/{tk['id']}/sign",
        json={
            "signer_name": "Pak Client Rep",
            "signature": _png(),
            "acceptance_no": "SES-4500012345",
            "disputes": [{"line_id": chem["id"], "reason": "Pemakaian kimia belum disepakati"}],
        },
        headers=ba,
    )
    assert r.status_code == 200, r.text
    signed = r.json()
    assert (signed["status"], signed["value"], signed["disputed_value"]) == (
        "signed",
        "15833333",
        "13200000",
    )
    assert signed["signed_pdf_attachment_id"] and signed["psre_ref"].startswith("INT-")
    assert await _journal(sessionmaker, tk["id"]) == [
        ("4100", 13_200_000, 0),
        ("1220", 0, 13_200_000),
    ]
    reg = (await client.get("/api/billing/disputes", headers=ba)).json()
    assert reg[0]["dispute_reason"] == "Pemakaian kimia belum disepakati"
    async with sessionmaker() as s:
        assert (await s.execute(select(Contract.used_value))).scalar_one() == D(15_833_333)

    # 3. Invoice: DPP 11/12, PPN 12 %, expected PPh 23 2 %, stamp duty.
    r = await client.post(
        "/api/billing/invoices", json={"ticket_ids": [tk["id"]], "invoice_date": today}, headers=ba
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    assert (inv["subtotal"], inv["dpp_other"], inv["ppn"], inv["total"]) == (
        "15833333",
        "14513889",
        "1741667",
        "17575000",
    )
    assert (inv["pph23_expected"], inv["net_cash"], inv["stamp_duty"]) == (
        "316667",
        "17258333",
        "10000",
    )
    r = await client.post(
        f"/api/billing/invoices/{inv['id']}/faktur",
        json={"faktur_number": "123", "faktur_date": today},
        headers=ba,
    )
    assert r.status_code == 422
    r = await client.post(
        f"/api/billing/invoices/{inv['id']}/faktur",
        json={"faktur_number": "04002600000000123", "faktur_date": today},
        headers=ba,
    )
    assert r.status_code == 200 and r.json()["status"] == "faktur_issued"
    assert await _journal(sessionmaker, inv["id"]) == [
        ("1210", 17_575_000, 0),
        ("1220", 0, 15_833_333),
        ("2210", 0, 1_741_667),
    ]
    assert (await client.get(f"/api/billing/tickets/{tk['id']}", headers=ba)).json()[
        "status"
    ] == "invoiced"

    # 4. Coretax XML.
    r = await client.get("/api/billing/coretax.xml", params={"ids": inv["id"]}, headers=ba)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(r.content)  # noqa: S314 - our own export
    assert root.tag == "TaxInvoiceBulk" and root.findtext("TIN") == "0012345678901000"
    ti = root.find("ListOfTaxInvoice/TaxInvoice")
    assert (
        ti is not None
        and ti.findtext("TrxCode") == "04"
        and ti.findtext("RefDesc") == inv["number"]
    )
    assert ti.findtext("BuyerTin") == "0023456789012000" and ti.findtext("BuyerName") == "PT KKKS"
    g = ti.find("ListOfGoodService/GoodService")
    assert g is not None
    assert (
        g.findtext("TaxBase"),
        g.findtext("OtherTaxBase"),
        g.findtext("VATRate"),
        g.findtext("VAT"),
    ) == (
        "15833333.00",
        "14513889.00",
        "12",
        "1741667.00",
    )

    # 5. Send: invoice pack PDF to the DMS, status sent (no e-mail provider in tests).
    r = await client.post(
        f"/api/billing/invoices/{inv['id']}/send", json={"email": "ap@kkks.co.id"}, headers=ba
    )
    assert r.status_code == 200 and r.json()["status"] == "sent" and r.json()["pack_attachment_id"]

    # 6. Bank import (CSV) auto-matches by invoice number; net cash => PPh 23 withheld.
    csv = (
        "Tanggal;Keterangan;Jumlah;Referensi\n"
        f"{today};TRF PT KKKS {inv['number']};17.258.333;FT123\n"
        f"{today};Biaya admin;-6.500;ADM\n"
    )
    r = await client.post(
        "/api/billing/bank-import",
        files={"file": ("mutasi.csv", csv.encode(), "text/csv")},
        headers=ba,
    )
    assert r.status_code == 200 and r.json()["lines"] == 1 and r.json()["suggested"] == 1
    again = await client.post(
        "/api/billing/bank-import",
        files={"file": ("mutasi.csv", csv.encode(), "text/csv")},
        headers=ba,
    )
    assert again.json()["duplicates"] == 1 and again.json()["lines"] == 0
    line = (await client.get("/api/billing/bank-lines", headers=ba)).json()[0]
    assert (
        line["suggested_invoice_number"] == inv["number"] and line["match_rule"] == "invoice_number"
    )
    r = await client.post(
        f"/api/billing/bank-lines/{line['id']}/confirm", json={"invoice_id": inv["id"]}, headers=ba
    )
    assert r.status_code == 200 and (r.json()["cash"], r.json()["pph23"]) == ("17258333", "316667")
    async with sessionmaker() as s:
        rid = (
            await s.execute(
                select(JournalEntry.source_id).where(JournalEntry.source_type == "customer_receipt")
            )
        ).scalar_one()
    assert await _journal(sessionmaker, rid) == [
        ("1110", 17_258_333, 0),
        ("1410", 316_667, 0),
        ("1210", 0, 17_575_000),
    ]
    paid = (await client.get(f"/api/billing/invoices/{inv['id']}", headers=ba)).json()
    assert paid["status"] == "paid" and paid["outstanding"] == "0"
    k = (await client.get("/api/billing/kpis", headers=ba)).json()
    assert k["days_to_cash"] == "0.0" and k["paid_invoices"] == 1


async def test_client_signs_through_link(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    p, tk, ba = await _ticketed(client, make_user, login, sessionmaker)
    r = await client.post(
        f"/api/billing/tickets/{tk['id']}/sign-link", json={"email": "rep@kkks.co.id"}, headers=ba
    )
    token = r.json()["url"].rsplit("/", 1)[1]
    rep_user = await make_user("client_rep")
    async with sessionmaker() as s:
        s.add(ProjectMember(project_id=p.id, user_id=rep_user.id))
        await s.commit()
    rep = await login(rep_user)
    outsider = await login(await make_user("engineer"))
    assert (await client.get(f"/api/billing/sign/{token}", headers=outsider)).status_code == 403
    assert (await client.get("/api/billing/sign/not-a-token", headers=rep)).status_code == 404
    view = (await client.get(f"/api/billing/sign/{token}", headers=rep)).json()
    assert view["can_sign"] and view["number"] == tk["number"]
    r = await client.post(
        f"/api/billing/sign/{token}",
        json={"signer_name": "Ibu Rep KKKS", "signature": _png(), "acceptance_no": "BAST-77"},
        headers=rep,
    )
    assert (
        r.status_code == 200
        and r.json()["sign_method"] == "link"
        and r.json()["value"] == "29033333"
    )
    # The link is single-use.
    assert (await client.get(f"/api/billing/sign/{token}", headers=rep)).status_code == 404
    # Expired links are refused.
    r = await client.post(
        "/api/billing/tickets",
        json={"project_id": str(p.id), "date_from": "2020-01-01", "date_to": "2020-01-02"},
        headers=ba,
    )
    assert r.status_code == 422
    async with sessionmaker() as s:
        await s.execute(
            update(ServiceTicket).values(
                link_token_hash="x", link_expires_at=datetime.now(UTC) - timedelta(days=1)
            )
        )
        await s.commit()


def test_mt940_parser() -> None:
    text = (
        ":20:STMT\n:25:1234567890\n:28C:1/1\n:60F:C261109IDR0,00\n"
        ":61:2611091109C17258333,00NTRFFT123//BANK\n"
        ":86:TRF PT KKKS INV-26-001\n"
        ":61:2611091109D6500,00NCHGADM\n:86:BIAYA ADMIN\n:62F:C261109IDR17251833,00\n"
    )
    lines = receipt_service.parse_mt940(text)
    assert [(str(x.value_date), x.amount, x.reference) for x in lines] == [
        ("2026-11-09", D("17258333.00"), "FT123"),
        ("2026-11-09", D("-6500.00"), "ADM"),
    ]
    assert lines[0].description == "TRF PT KKKS INV-26-001"
