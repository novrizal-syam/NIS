"""Phase 09 (DMS): controlled documents (release archives the old revision as uncontrolled,
watermark), letters (incoming register + text search, disposisi, reply and close; outgoing
template -> Director -> gap-free number -> e-sign/e-Meterai -> sent), library (HR restriction,
retention, legal hold, share links, full-text search, access log)."""

import io
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fpdf import FPDF
from httpx import AsyncClient
from openpyxl import Workbook
from pypdf import PdfReader
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.dms.models import LibraryDocument, ShareLink
from app.services.numbering import today_jakarta
from app.services.storage import Storage

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]


def _pdf(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 6, text)
    return bytes(pdf.output())


async def _upload(
    client: AsyncClient, h: dict[str, str], entity_type: str, entity_id: str, data: bytes, name: str
) -> dict[str, Any]:
    r = await client.post(
        "/api/attachments",
        data={"entity_type": entity_type, "entity_id": entity_id},
        files={"file": (name, data, "application/pdf")},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_sop_release_archives_old_revision_as_uncontrolled(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    owner = await login(await make_user("qhse_coordinator"))
    director = await login(await make_user("director"))
    reader = await login(await make_user("field_engineer"))
    r = await client.post(
        "/api/dms/controlled",
        json={
            "code": "GEK-BPM-001-SOP-07",
            "title": "SOP Pekerjaan di ketinggian",
            "kind": "sop",
            "system": "GEK-BPM-001",
            "affected_roles": ["field_engineer"],
        },
        headers=owner,
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    url = f"/api/dms/controlled/{doc['id']}"
    rev_ids = []
    for n, text in enumerate(("Rev 0 tali full body harness", "Rev 1 harness dua lanyard")):
        att = await _upload(client, owner, "controlled_doc", doc["id"], _pdf(text), f"sop-{n}.pdf")
        rev = (
            await client.post(
                f"{url}/revisions",
                json={"change_summary": f"Revisi {n}", "attachment_id": att["id"]},
                headers=owner,
            )
        ).json()
        sub = (await client.post(f"{url}/revisions/{rev['id']}/submit", headers=owner)).json()
        r = await client.post(
            f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=director
        )
        assert r.status_code == 200, r.text
        rev_ids.append(rev["id"])
    full = (await client.get(url, headers=owner)).json()
    assert full["current_revision"] == 1 and full["next_review"]
    assert {r["revision"]: r["status"] for r in full["revisions"]} == {
        1: "effective",
        0: "uncontrolled",
    }
    # Readers only see the effective revision; its PDF is watermarked.
    seen = (await client.get(url, headers=reader)).json()
    assert [r["revision"] for r in seen["revisions"]] == [1]
    pdf = await client.get(f"{url}/revisions/{rev_ids[1]}/pdf", headers=reader)
    assert pdf.status_code == 200
    assert "SALINAN TERKENDALI" in PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text()
    assert (
        await client.get(f"{url}/revisions/{rev_ids[0]}/pdf", headers=reader)
    ).status_code == 404
    old = await client.get(f"{url}/revisions/{rev_ids[0]}/pdf", headers=owner)
    assert "TIDAK TERKENDALI" in PdfReader(io.BytesIO(old.content)).pages[0].extract_text()


async def test_controlled_register_import(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    owner = await login(await make_user("legal_liaison"))
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["code", "title", "kind", "system", "review_months", "affected_roles"])
    ws.append(
        [
            "GEK-BPM-001-SOP-01",
            "SOP Pengendalian dokumen",
            "sop",
            "GEK-BPM-001",
            12,
            "field_engineer",
        ]
    )
    ws.append(["GEK-MNT-001-F-01", "Form inspeksi harian", "form", "GEK-MNT-001", 24, ""])
    ws.append(["X-1", "Salah jenis", "memo", "", 12, ""])
    buf = io.BytesIO()
    wb.save(buf)
    r = await client.post(
        "/api/dms/controlled/import",
        files={"file": ("register.xlsx", buf.getvalue(), "application/octet-stream")},
        headers=owner,
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2 and len(r.json()["errors"]) == 1
    rows = (await client.get("/api/dms/controlled?system=GEK-MNT-001", headers=owner)).json()
    assert [x["code"] for x in rows] == ["GEK-MNT-001-F-01"] and rows[0]["review_months"] == 24


async def test_letters_incoming_disposition_reply_and_outgoing(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    secretary = await login(await make_user("legal_liaison"))
    director = await login(await make_user("director"))
    pic_user = await make_user("head_of_operation")
    pic = await login(pic_user)
    other = await login(await make_user("field_engineer"))
    today = today_jakarta()
    letter = (
        await client.post(
            "/api/letters/incoming",
            json={
                "received_on": today.isoformat(),
                "sender": "PT KKKS Rokan",
                "sender_ref": "123/KKKS/X/2026",
                "subject": "Undangan rapat kick-off",
            },
            headers=secretary,
        )
    ).json()
    assert letter["number"].startswith("SM-") and letter["status"] == "registered"
    scan = await _upload(
        client,
        secretary,
        "incoming_letter",
        letter["id"],
        _pdf("Mohon kehadiran tim well testing sumur RKN-77"),
        "surat.pdf",
    )
    await client.post(
        f"/api/letters/incoming/{letter['id']}/scan",
        json={"attachment_id": scan["id"]},
        headers=secretary,
    )
    # Text search finds words inside the PDF.
    hits = (
        await client.get("/api/letters/incoming", params={"q": "RKN-77"}, headers=secretary)
    ).json()
    assert [h["id"] for h in hits] == [letter["id"]]
    r = await client.post(
        f"/api/letters/incoming/{letter['id']}/dispositions",
        json={
            "pic_id": str(pic_user.id),
            "instruction": "Siapkan tim dan balas",
            "deadline": (today + timedelta(days=3)).isoformat(),
        },
        headers=secretary,
    )
    assert r.status_code == 200, r.text
    disp_id = r.json()["id"]
    # The PIC sees the letter; others do not.
    assert (
        await client.get(f"/api/letters/incoming/{letter['id']}", headers=pic)
    ).status_code == 200
    assert (
        await client.get(f"/api/letters/incoming/{letter['id']}", headers=other)
    ).status_code == 404
    r = await client.post(
        f"/api/letters/incoming/{letter['id']}/close",
        json={"note": "selesai saja"},
        headers=secretary,
    )
    assert r.status_code == 409 and r.json()["code"] == "DISPOSITION_OPEN"
    assert (
        await client.post(
            f"/api/letters/dispositions/{disp_id}/done", json={"note": "Tim siap"}, headers=pic
        )
    ).status_code == 200

    # Reply from a template: number only at Director approval, then e-sign + e-Meterai.
    templates = (await client.get("/api/letters/templates", headers=secretary)).json()
    assert {"UMUM", "BALASAN"} <= {t["code"] for t in templates}
    r = await client.post(
        "/api/letters/outgoing",
        json={
            "department": "OPS",
            "to": "PT KKKS Rokan",
            "template_code": "BALASAN",
            "values": {"nomor_surat_masuk": "123/KKKS/X/2026"},
        },
        headers=secretary,
    )
    assert r.status_code == 422 and r.json()["code"] == "TEMPLATE_VALUES"
    out = (
        await client.post(
            "/api/letters/outgoing",
            json={
                "department": "OPS",
                "to": "PT KKKS Rokan",
                "template_code": "BALASAN",
                "values": {
                    "nomor_surat_masuk": "123/KKKS/X/2026",
                    "tanggal_surat_masuk": "1 Nov 2026",
                    "perihal_surat_masuk": "Undangan rapat kick-off",
                    "isi": "Tim kami akan hadir.",
                },
                "signer_name": "Direktur Utama",
                "needs_meterai": True,
                "in_reply_to": letter["id"],
            },
            headers=secretary,
        )
    ).json()
    assert (
        out["number"] is None and out["status"] == "draft" and "123/KKKS/X/2026" in out["subject"]
    )
    sub = (await client.post(f"/api/letters/outgoing/{out['id']}/submit", headers=secretary)).json()
    await client.post(
        f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=director
    )
    approved = (await client.get(f"/api/letters/outgoing/{out['id']}", headers=secretary)).json()
    assert approved["status"] == "approved" and approved["number"].startswith("001/GEK-OPS/")
    sent = (
        await client.post(
            f"/api/letters/outgoing/{out['id']}/send", json={"via": "email"}, headers=secretary
        )
    ).json()
    assert (
        sent["status"] == "sent"
        and sent["esign_ref"]
        and sent["emeterai_ref"].startswith("EMT-")
        and sent["file_id"]
    )
    r = await client.post(
        f"/api/letters/incoming/{letter['id']}/close",
        json={"reply_id": out["id"]},
        headers=secretary,
    )
    assert r.status_code == 200 and r.json()["status"] == "closed"
    detail = (await client.get(f"/api/letters/incoming/{letter['id']}", headers=secretary)).json()
    assert [x["number"] for x in detail["replies"]] == [approved["number"]]


async def test_library_restrictions_retention_hold_share_and_search(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
) -> None:
    legal = await login(await make_user("legal_liaison"))
    hcbp = await login(await make_user("hcbp_officer"))
    staff = await login(await make_user("procurement_officer"))
    hr = (
        await client.post(
            "/api/dms/library", json={"category": "hr", "title": "Kontrak kerja Andi"}, headers=hcbp
        )
    ).json()
    assert hr["allowed_roles"] == ["hcbp_officer", "director"]
    assert (await client.get(f"/api/dms/library/{hr['id']}", headers=staff)).status_code == 404
    assert all(
        d["id"] != hr["id"] for d in (await client.get("/api/dms/library", headers=legal)).json()
    )

    deed = (
        await client.post(
            "/api/dms/library",
            json={
                "category": "legal",
                "title": "Akta pendirian dan NIB",
                "tags": ["Legal", "NIB"],
                "expiry_date": (today_jakarta() + timedelta(days=45)).isoformat(),
            },
            headers=legal,
        )
    ).json()
    assert deed["tags"] == ["legal", "nib"] and deed["retention_until"][:4] == str(
        today_jakarta().year + 10
    )
    f = await _upload(
        client,
        legal,
        "library_doc",
        deed["id"],
        _pdf("Nomor Induk Berusaha 9120001234567"),
        "nib.pdf",
    )
    hits = (
        await client.get("/api/dms/search", params={"q": "9120001234567"}, headers=legal)
    ).json()
    assert any(h["kind"] == "file" and h["id"] == f["id"] for h in hits)
    # Retention blocks archiving (document and file); legal hold too.
    r = await client.post(f"/api/dms/library/{deed['id']}/archive", headers=legal)
    assert r.status_code == 409 and r.json()["code"] == "RETENTION_ACTIVE"
    r = await client.post(f"/api/attachments/{f['id']}/archive", headers=legal)
    assert r.status_code == 409
    assert (
        await client.post(
            f"/api/dms/library/{deed['id']}/legal-hold",
            json={"hold": True, "reason": "Sengketa"},
            headers=staff,
        )
    ).status_code in (403, 404)
    r = await client.post(
        f"/api/dms/library/{deed['id']}/legal-hold",
        json={"hold": True, "reason": "Sengketa lahan"},
        headers=legal,
    )
    assert r.status_code == 200 and r.json()["legal_hold"]
    async with sessionmaker() as s:
        await s.execute(
            update(LibraryDocument)
            .where(LibraryDocument.title.like("Akta%"))
            .values(retention_until=today_jakarta() - timedelta(days=1))
        )
        await s.commit()
    r = await client.post(f"/api/dms/library/{deed['id']}/archive", headers=legal)
    assert r.status_code == 409 and r.json()["code"] == "LEGAL_HOLD"

    # Expiring share link; restricted documents cannot be shared.
    link = (
        await client.post(f"/api/dms/files/{f['id']}/share", json={"days": 3}, headers=legal)
    ).json()
    r = await client.get(link["url"])
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    hr_file = await _upload(client, hcbp, "library_doc", hr["id"], _pdf("rahasia"), "kontrak.pdf")
    r = await client.post(f"/api/dms/files/{hr_file['id']}/share", json={"days": 3}, headers=hcbp)
    assert r.status_code == 403 and r.json()["code"] == "SHARE_RESTRICTED"
    async with sessionmaker() as s:
        await s.execute(
            update(ShareLink).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await s.commit()
    assert (await client.get(link["url"])).status_code == 404
    # Access log: views, the share and the public download.
    await client.get(f"/api/attachments/{f['id']}/content", headers=legal)
    log = (await client.get(f"/api/dms/library/{deed['id']}", headers=legal)).json()["access_log"]
    assert {"share", "download"} <= {x["action"] for x in log}
    assert any(x["user"] == "Tautan publik" for x in log)
