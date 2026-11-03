"""Phase 02d: tender details — package approval preconditions and parallel DOA."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient

from app.auth.models import User
from app.crm import service as crm
from app.services.storage import Storage

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


async def _tender_opportunity(client: AsyncClient, ae: dict[str, str]) -> dict[str, Any]:
    lead = (
        await client.post(
            "/api/crm/leads",
            json={"company_name": "PT KKKS Tender", "source": "eproc", "need": "Well testing"},
            headers=ae,
        )
    ).json()
    url = f"/api/crm/leads/{lead['id']}"
    await client.patch(
        url, json={"qualification": dict.fromkeys(crm.QUALIFICATION, True)}, headers=ae
    )
    await client.post(f"{url}/status", json={"to": "contacted"}, headers=ae)
    await client.post(f"{url}/status", json={"to": "qualified"}, headers=ae)
    r = await client.post(
        f"{url}/convert", json={"title": "Tender well testing", "is_tender": True}, headers=ae
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _setup(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> tuple[dict[str, str], dict[str, str], dict[str, Any], dict[str, Any]]:
    ae = await login(await make_user("account_executive"))
    ts = await login(await make_user("tender_specialist"))
    opp = await _tender_opportunity(client, ae)
    r = await client.post("/api/tenders", json={"opportunity_id": opp["id"]}, headers=ts)
    assert r.status_code == 201, r.text
    return ae, ts, opp, r.json()


async def _attach(client: AsyncClient, h: dict[str, str], doc_id: str) -> None:
    r = await client.post(
        "/api/attachments",
        data={"entity_type": "tender_document", "entity_id": doc_id},
        files={"file": ("dok.pdf", PDF, "application/pdf")},
        headers=h,
    )
    assert r.status_code == 201, r.text


def _put_body(t: dict[str, Any], **kw: Any) -> dict[str, Any]:
    closing = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    body = {
        "tender_number": "TND-2026-0042",
        "method": "open",
        "closing_at": closing,
        "price": t.get("price"),
    }
    body.update(kw)
    return body


async def _complete_checklist(
    client: AsyncClient, ts: dict[str, str], t: dict[str, Any], storage: Storage
) -> dict[str, Any]:
    tid = t["id"]
    for d in t["documents"]:
        if d["mandatory"]:
            await _attach(client, ts, d["id"])
    return (await client.get(f"/api/tenders/{tid}", headers=ts)).json()


async def test_only_tender_opportunities_get_tender_data(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    ts = await login(await make_user("tender_specialist"))
    lead = (
        await client.post(
            "/api/crm/leads",
            json={"company_name": "PT B", "source": "visit", "need": "Pumping unit"},
            headers=ae,
        )
    ).json()
    url = f"/api/crm/leads/{lead['id']}"
    await client.patch(
        url, json={"qualification": dict.fromkeys(crm.QUALIFICATION, True)}, headers=ae
    )
    await client.post(f"{url}/status", json={"to": "contacted"}, headers=ae)
    await client.post(f"{url}/status", json={"to": "qualified"}, headers=ae)
    opp = (await client.post(f"{url}/convert", json={"title": "Pumping"}, headers=ae)).json()
    r = await client.post("/api/tenders", json={"opportunity_id": opp["id"]}, headers=ts)
    assert r.status_code == 409 and r.json()["code"] == "NOT_A_TENDER"


async def test_package_button_preconditions(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    _, ts, _, t = await _setup(client, make_user, login)
    tid = t["id"]
    mandatory = [d for d in t["documents"] if d["mandatory"]]
    assert len(mandatory) == 12 and all(d["status"] == "missing" for d in mandatory)
    assert t["readiness"]["ready"] is False

    # Nothing attached, no price -> refused with the reasons.
    r = await client.post(f"/api/tenders/{tid}/submit-package", headers=ts)
    assert r.status_code == 422 and r.json()["code"] == "PACKAGE_NOT_READY"
    assert "12 dokumen wajib" in r.json()["message"] and "harga" in r.json()["message"]

    t = await _complete_checklist(client, ts, t, storage)
    assert t["readiness"]["missing"] == []
    assert t["readiness"]["problems"] == ["harga penawaran belum diisi"]
    r = await client.post(f"/api/tenders/{tid}/submit-package", headers=ts)
    assert r.status_code == 422

    # An expired document counts as missing (valid at closing is required).
    doc = mandatory[0]
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    await client.put(
        f"/api/tenders/{tid}/documents/{doc['id']}",
        json={"section": doc["section"], "name": doc["name"], "expiry_date": yesterday},
        headers=ts,
    )
    t = (
        await client.put(f"/api/tenders/{tid}", json=_put_body(t, price="950000000"), headers=ts)
    ).json()
    states = {d["id"]: d for d in t["documents"]}
    assert states[doc["id"]]["status"] == "missing" and states[doc["id"]]["expired"] is True
    assert t["readiness"]["missing"] == [doc["name"]]
    assert (await client.post(f"/api/tenders/{tid}/submit-package", headers=ts)).status_code == 422

    # Marked N/A (or renewed) -> ready.
    await client.put(
        f"/api/tenders/{tid}/documents/{doc['id']}",
        json={"section": doc["section"], "name": doc["name"], "not_applicable": True},
        headers=ts,
    )
    t = (await client.get(f"/api/tenders/{tid}", headers=ts)).json()
    assert t["readiness"]["ready"] is True and t["can_submit_package"] is True
    r = await client.post(f"/api/tenders/{tid}/submit-package", headers=ts)
    assert r.status_code == 200 and r.json()["package_status"] == "pending"
    again = await client.post(f"/api/tenders/{tid}/submit-package", headers=ts)
    assert again.status_code == 409


async def _ready_and_submitted(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> tuple[dict[str, str], dict[str, str], dict[str, Any], dict[str, Any]]:
    ae, ts, opp, t = await _setup(client, make_user, login)
    t = await _complete_checklist(client, ts, t, storage)
    await client.put(f"/api/tenders/{t['id']}", json=_put_body(t, price="950000000"), headers=ts)
    r = await client.post(f"/api/tenders/{t['id']}/submit-package", headers=ts)
    assert r.status_code == 200, r.text
    return ae, ts, opp, r.json()


async def test_parallel_approval_needs_both(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    _, ts, _, t = await _ready_and_submitted(client, make_user, login, storage)
    hoo = await login(await make_user("head_of_operation"))
    director = await login(await make_user("director"))
    rid = t["request_id"]
    req = (await client.get(f"/api/workflow/requests/{rid}", headers=director)).json()
    assert {s["approver_role"] for s in req["steps"]} == {"head_of_operation", "director"}
    assert {s["seq"] for s in req["steps"]} == {1}  # parallel: same step

    # The preparer cannot approve; each approver acts on their own step.
    assert (
        await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=ts)
    ).status_code == 403
    r = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=hoo)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    t1 = (await client.get(f"/api/tenders/{t['id']}", headers=ts)).json()
    assert t1["package_status"] == "pending"
    # Submission cannot be recorded until both approved.
    sub = {"submitted_at": datetime.now(UTC).isoformat(), "channel": "eproc"}
    early = await client.post(f"/api/tenders/{t['id']}/submission", json=sub, headers=ts)
    assert early.status_code == 409 and early.json()["code"] == "PACKAGE_NOT_APPROVED"

    r = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=director)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    t2 = (await client.get(f"/api/tenders/{t['id']}", headers=ts)).json()
    assert t2["package_status"] == "approved"
    locked = await client.put(
        f"/api/tenders/{t['id']}", json=_put_body(t2, price="900000000"), headers=ts
    )
    assert locked.status_code == 409 and locked.json()["code"] == "PACKAGE_LOCKED"


async def test_one_rejection_rejects_the_package(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    _, ts, _, t = await _ready_and_submitted(client, make_user, login, storage)
    hoo = await login(await make_user("head_of_operation"))
    director = await login(await make_user("director"))
    rid = t["request_id"]
    await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=director)
    await client.post(
        f"/api/workflow/requests/{rid}/reject",
        json={"comment": "Metode kerja belum sesuai TOR"},
        headers=hoo,
    )
    t2 = (await client.get(f"/api/tenders/{t['id']}", headers=ts)).json()
    assert t2["package_status"] == "rejected" and t2["can_submit_package"] is True


async def test_submission_result_and_closing_soon(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    ae, ts, opp, t = await _ready_and_submitted(client, make_user, login, storage)
    hoo = await login(await make_user("head_of_operation"))
    director = await login(await make_user("director"))
    for h in (hoo, director):
        await client.post(f"/api/workflow/requests/{t['request_id']}/approve", json={}, headers=h)

    soon = (await client.get("/api/tenders/closing-soon", headers=ts)).json()
    assert [x["id"] for x in soon] == [t["id"]] and soon[0]["missing"] == 0
    # The AE sees their own tender (view own) but cannot change it.
    assert (await client.get(f"/api/tenders/{t['id']}", headers=ae)).status_code == 200
    assert (
        await client.post(
            f"/api/tenders/{t['id']}/result", json={"result": "cancelled"}, headers=ae
        )
    ).status_code == 403

    r = await client.post(
        f"/api/tenders/{t['id']}/result", json={"result": "lost", "winner_name": "PT X"}, headers=ts
    )
    assert r.status_code == 409 and r.json()["code"] == "NOT_SUBMITTED"
    r = await client.post(
        f"/api/tenders/{t['id']}/submission",
        json={
            "submitted_at": datetime.now(UTC).isoformat(),
            "channel": "eproc",
            "receipt_number": "RCPT-778",
        },
        headers=ts,
    )
    assert r.status_code == 200 and r.json()["receipt_number"] == "RCPT-778"
    r = await client.post(
        f"/api/tenders/{t['id']}/result", json={"result": "lost", "winner_name": "PT X"}, headers=ts
    )
    assert r.status_code == 422 and r.json()["code"] == "LESSONS_REQUIRED"
    r = await client.post(
        f"/api/tenders/{t['id']}/result",
        json={
            "result": "lost",
            "rank": 2,
            "winner_name": "PT Pesaing Jaya",
            "winning_price": "910000000",
            "lessons_learned": "Harga peralatan sewa terlalu tinggi; negosiasi vendor lebih awal.",
        },
        headers=ts,
    )
    assert r.status_code == 200 and r.json()["result"] == "lost"
    d = (await client.get(f"/api/crm/opportunities/{opp['id']}", headers=ae)).json()
    assert d["stage"] == "lost" and d["winner_price"] == "910000000"
    assert "PT Pesaing Jaya" in d["lost_reason"]
    assert (await client.get("/api/tenders/closing-soon", headers=ts)).json() == []
