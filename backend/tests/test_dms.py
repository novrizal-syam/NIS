from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.auth.models import User
from app.dms.service import MAX_BYTES, safe_name, sniff
from app.services.storage import Storage

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def _vendor(client: AsyncClient, h: dict[str, str]) -> str:
    res = await client.post(
        "/api/master/vendors",
        json={"code": "V-1", "name": "PT Uji", "category": "chemicals"},
        headers=h,
    )
    return str(res.json()["id"])


def _form(entity_id: str, **extra: str) -> dict[str, str]:
    return {"entity_type": "vendors", "entity_id": entity_id, **extra}


async def test_upload_version_preview_archive(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    po = await login(await make_user("procurement_officer"))
    vid = await _vendor(client, po)

    res = await client.post(
        "/api/attachments",
        data=_form(vid, note="SIUP 2026"),
        files={"file": ("siup scan!.pdf", PDF, "application/pdf")},
        headers=po,
    )
    assert res.status_code == 201, res.text
    first = res.json()
    assert (
        first["filename"] == "siup scan_.pdf"
        and first["version"] == 1
        and first["size"] == len(PDF)
    )

    v2 = await client.post(
        "/api/attachments",
        data=_form(vid, replaces=first["group_id"]),
        files={"file": ("siup-baru.pdf", PDF + b"\n%v2", "application/pdf")},
        headers=po,
    )
    assert v2.json()["version"] == 2

    listed = (
        await client.get(f"/api/attachments?entity_type=vendors&entity_id={vid}", headers=po)
    ).json()
    assert len(listed) == 1 and listed[0]["version"] == 2 and listed[0]["versions"] == 2
    versions = (await client.get(f"/api/attachments/{first['id']}/versions", headers=po)).json()
    assert [v["version"] for v in versions] == [2, 1]

    preview = await client.get(f"/api/attachments/{first['id']}/content", headers=po)
    assert preview.status_code == 200 and preview.content == PDF
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.headers["content-disposition"].startswith("inline")
    dl = await client.get(f"/api/attachments/{first['id']}/content?download=true", headers=po)
    assert dl.headers["content-disposition"].startswith("attachment")

    assert (
        await client.post(f"/api/attachments/{first['id']}/archive", headers=po)
    ).status_code == 204
    assert (
        await client.get(f"/api/attachments?entity_type=vendors&entity_id={vid}", headers=po)
    ).json() == []
    # Archived files stay retrievable for retention/audit.
    assert (
        await client.get(f"/api/attachments/{first['id']}/content", headers=po)
    ).status_code == 200
    hist = (await client.get(f"/api/audit/history/vendors/{vid}", headers=po)).json()
    assert {"upload", "archive"} <= {i["action"] for i in hist["items"]}


async def test_only_pdf_jpg_png_by_content(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    po = await login(await make_user("procurement_officer"))
    vid = await _vendor(client, po)
    # An executable renamed to .pdf is refused.
    fake = await client.post(
        "/api/attachments",
        data=_form(vid),
        files={"file": ("x.pdf", b"MZ\x90\x00", "application/pdf")},
        headers=po,
    )
    assert fake.status_code == 415 and fake.json()["code"] == "FILE_TYPE_NOT_ALLOWED"
    png = await client.post(
        "/api/attachments", data=_form(vid), files={"file": ("foto", PNG, "image/png")}, headers=po
    )
    assert png.json()["filename"] == "foto.png" and png.json()["content_type"] == "image/png"


async def test_size_limit(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    po = await login(await make_user("procurement_officer"))
    vid = await _vendor(client, po)
    big = PDF + b"0" * MAX_BYTES
    res = await client.post(
        "/api/attachments",
        data=_form(vid),
        files={"file": ("big.pdf", big, "application/pdf")},
        headers=po,
    )
    assert res.status_code == 413 and res.json()["message"] == "Ukuran file maksimal 20 MB."


async def test_attachment_permissions(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    po = await login(await make_user("procurement_officer"))
    vid = await _vendor(client, po)
    att = (
        await client.post(
            "/api/attachments",
            data=_form(vid),
            files={"file": ("a.pdf", PDF, "application/pdf")},
            headers=po,
        )
    ).json()
    eng = await login(await make_user("engineer"))  # reads master data, cannot edit
    assert (
        await client.get(f"/api/attachments/{att['id']}/content", headers=eng)
    ).status_code == 200
    up = await client.post(
        "/api/attachments",
        data=_form(vid),
        files={"file": ("b.pdf", PDF, "application/pdf")},
        headers=eng,
    )
    assert up.status_code == 403
    assert (
        await client.post(f"/api/attachments/{att['id']}/archive", headers=eng)
    ).status_code == 403
    rep = await login(await make_user("client_rep"))
    assert (
        await client.get(f"/api/attachments/{att['id']}/content", headers=rep)
    ).status_code == 404


@pytest.mark.parametrize(
    ("name", "ctype", "expected"),
    [
        ("../../etc/passwd", "application/pdf", "passwd.pdf"),
        ("foto.JPEG", "image/jpeg", "foto.JPEG"),
        ("", "image/png", "lampiran.png"),
    ],
)
def test_safe_name(name: str, ctype: str, expected: str) -> None:
    assert safe_name(name, ctype) == expected


def test_sniff() -> None:
    assert sniff(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
