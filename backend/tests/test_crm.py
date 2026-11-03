"""Phase 02a: leads, opportunities, bid/no-bid (score threshold, SoD, status machines)."""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

from app.auth.models import User
from app.core.errors import AppError
from app.crm import service

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]

ALL_FIVE = {
    "budget": True,
    "technical_fit": True,
    "start_6m": True,
    "decision_maker": True,
    "csms": True,
}


def scores(*values: int) -> dict[str, int]:
    return dict(zip(service.SCORES, values, strict=True))


async def _lead(client: AsyncClient, h: dict[str, str], **kw: Any) -> dict[str, Any]:
    body = {
        "company_name": "PT Migas Hulu Contoh",
        "contact_name": "Bapak Andi",
        "source": "civd",
        "need": "Well testing 3 sumur, Q1 2027",
        "estimated_value": "4500000000",
        **kw,
    }
    r = await client.post("/api/crm/leads", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def _opportunity(client: AsyncClient, h: dict[str, str]) -> dict[str, Any]:
    lead = await _lead(client, h)
    lid = lead["id"]
    await client.patch(f"/api/crm/leads/{lid}", json={"qualification": ALL_FIVE}, headers=h)
    await client.post(f"/api/crm/leads/{lid}/status", json={"to": "contacted"}, headers=h)
    await client.post(f"/api/crm/leads/{lid}/status", json={"to": "qualified"}, headers=h)
    r = await client.post(
        f"/api/crm/leads/{lid}/convert",
        json={"title": "Well testing Blok X", "probability": 40},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- score threshold


def test_score_percent_and_threshold() -> None:
    assert service.score_percent(scores(5, 5, 5, 5, 5, 5)) == Decimal("100.00")
    assert service.score_percent(scores(1, 1, 1, 1, 1, 1)) == Decimal("20.00")
    # 18 / 30 = exactly 60 % -> recommends bid (>= threshold).
    pct = service.score_percent(scores(3, 3, 3, 3, 3, 3))
    assert pct == Decimal("60.00")
    assert service.recommend(pct, Decimal(60)) == "bid"
    # 17 / 30 = 56.67 % -> no-bid.
    low = service.score_percent(scores(3, 3, 3, 3, 3, 2))
    assert low == Decimal("56.67")
    assert service.recommend(low, Decimal(60)) == "no_bid"
    with pytest.raises(AppError):
        service.score_percent(scores(3, 3, 3, 3, 3, 6))
    with pytest.raises(AppError):
        service.score_percent({"strategic_fit": 5})


async def test_bid_against_recommendation_needs_justification(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    opp = await _opportunity(client, ae)
    url = f"/api/crm/opportunities/{opp['id']}/bid-decision"

    low = scores(3, 3, 3, 3, 3, 2)
    r = await client.post(url, json={"scores": low, "proposal": "bid"}, headers=ae)
    assert r.status_code == 422 and r.json()["code"] == "JUSTIFICATION_REQUIRED"
    assert "56.67%" in r.json()["message"]

    r = await client.post(
        url,
        json={"scores": low, "proposal": "bid", "note": "Klien strategis untuk RJPP 2027"},
        headers=ae,
    )
    assert r.status_code == 201, r.text
    assert r.json()["recommendation"] == "no_bid" and r.json()["percent"] == "56.67"

    # Only one decision at a time.
    again = await client.post(
        url, json={"scores": scores(5, 5, 5, 5, 5, 5), "proposal": "bid"}, headers=ae
    )
    assert again.status_code == 409 and again.json()["code"] == "BID_PENDING"


async def test_threshold_comes_from_settings(
    client: AsyncClient, make_user: MakeUser, login: Login, session: Any
) -> None:
    from app.setup import service as settings_store

    await settings_store.put(session, service.BID_THRESHOLD, 50, None)
    await session.commit()
    try:
        ae = await login(await make_user("account_executive"))
        opp = await _opportunity(client, ae)
        r = await client.post(
            f"/api/crm/opportunities/{opp['id']}/bid-decision",
            json={"scores": scores(3, 3, 3, 3, 3, 2), "proposal": "bid"},
            headers=ae,
        )
        assert r.status_code == 201 and r.json()["recommendation"] == "bid"
        cfg = (await client.get("/api/crm/config", headers=ae)).json()
        assert cfg["bid_threshold"] == "50"
    finally:
        await settings_store.put(session, service.BID_THRESHOLD, 60, None)
        await session.commit()


# ---------------------------------------------------------------- DOA + SoD


async def test_bid_approved_moves_to_quotation(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))
    opp = await _opportunity(client, ae)
    r = await client.post(
        f"/api/crm/opportunities/{opp['id']}/bid-decision",
        json={"scores": scores(4, 4, 3, 4, 3, 4), "proposal": "bid"},
        headers=ae,
    )
    rid = r.json()["request_id"]
    detail = (await client.get(f"/api/crm/opportunities/{opp['id']}", headers=ae)).json()
    assert detail["bid_status"] == "pending" and detail["stage"] == "qualified"

    # Stage cannot change while the Director decides.
    blocked = await client.post(
        f"/api/crm/opportunities/{opp['id']}/stage",
        json={"to": "lost", "reason": "Klien batal"},
        headers=ae,
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "BID_PENDING"

    inbox = (await client.get("/api/workflow/inbox", headers=director)).json()
    assert any(i["request_id"] == rid or i.get("id") == rid for i in inbox["items"])

    ok = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=director)
    assert ok.status_code == 200, ok.text
    detail = (await client.get(f"/api/crm/opportunities/{opp['id']}", headers=ae)).json()
    assert detail["stage"] == "quotation" and detail["bid_status"] == "bid"
    assert detail["bid_decisions"][0]["status"] == "approved"


async def test_sod_requester_cannot_approve_own_bid_decision(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    # The Director may also prepare crm records, but never approves their own proposal.
    director = await login(await make_user("director"))
    other_director = await login(await make_user("director"))
    opp = await _opportunity(client, director)
    r = await client.post(
        f"/api/crm/opportunities/{opp['id']}/bid-decision",
        json={"scores": scores(5, 5, 5, 5, 5, 5), "proposal": "bid"},
        headers=director,
    )
    rid = r.json()["request_id"]
    own = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=director)
    assert own.status_code == 403 and own.json()["code"] == "SOD_SELF_APPROVAL"
    own_reject = await client.post(
        f"/api/workflow/requests/{rid}/reject", json={"comment": "tidak"}, headers=director
    )
    assert own_reject.status_code == 403
    ok = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=other_director)
    assert ok.status_code == 200


async def test_head_of_sales_cannot_approve_bid_decision(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    hos = await login(await make_user("head_of_sales"))
    opp = await _opportunity(client, ae)
    rid = (
        await client.post(
            f"/api/crm/opportunities/{opp['id']}/bid-decision",
            json={"scores": scores(5, 5, 5, 5, 5, 5), "proposal": "bid"},
            headers=ae,
        )
    ).json()["request_id"]
    r = await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=hos)
    assert r.status_code == 403 and r.json()["code"] == "NOT_APPROVER"


async def test_rejected_bid_and_approved_no_bid_end_as_lost(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))

    opp = await _opportunity(client, ae)
    rid = (
        await client.post(
            f"/api/crm/opportunities/{opp['id']}/bid-decision",
            json={"scores": scores(4, 4, 4, 4, 4, 4), "proposal": "bid"},
            headers=ae,
        )
    ).json()["request_id"]
    await client.post(
        f"/api/workflow/requests/{rid}/reject",
        json={"comment": "Kru tidak tersedia Q1"},
        headers=director,
    )
    d = (await client.get(f"/api/crm/opportunities/{opp['id']}", headers=ae)).json()
    assert d["stage"] == "lost" and "Kru tidak tersedia Q1" in d["lost_reason"]
    assert d["probability"] == 0

    opp2 = await _opportunity(client, ae)
    rid2 = (
        await client.post(
            f"/api/crm/opportunities/{opp2['id']}/bid-decision",
            json={
                "scores": scores(2, 2, 2, 2, 2, 2),
                "proposal": "no_bid",
                "note": "Margin rendah",
            },
            headers=ae,
        )
    ).json()["request_id"]
    await client.post(f"/api/workflow/requests/{rid2}/approve", json={}, headers=director)
    d2 = (await client.get(f"/api/crm/opportunities/{opp2['id']}", headers=ae)).json()
    assert d2["stage"] == "lost" and d2["bid_status"] == "no_bid"
    assert "Margin rendah" in d2["lost_reason"]


async def test_withdrawn_bid_decision_returns_to_qualified(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    opp = await _opportunity(client, ae)
    rid = (
        await client.post(
            f"/api/crm/opportunities/{opp['id']}/bid-decision",
            json={"scores": scores(4, 4, 4, 4, 4, 4), "proposal": "bid"},
            headers=ae,
        )
    ).json()["request_id"]
    r = await client.post(f"/api/workflow/requests/{rid}/cancel", json={}, headers=ae)
    assert r.status_code == 200, r.text
    d = (await client.get(f"/api/crm/opportunities/{opp['id']}", headers=ae)).json()
    assert d["stage"] == "qualified" and d["bid_status"] == "none"
    assert d["bid_decisions"][0]["status"] == "cancelled"


# ---------------------------------------------------------------- status machines


async def test_lead_status_machine_and_qualification(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    lead = await _lead(client, ae)
    assert lead["number"].startswith("LD-") and lead["status"] == "new"
    url = f"/api/crm/leads/{lead['id']}"

    # New cannot jump to Qualified.
    r = await client.post(f"{url}/status", json={"to": "qualified"}, headers=ae)
    assert r.status_code == 409 and r.json()["code"] == "ILLEGAL_TRANSITION"
    # Cannot convert before qualified.
    r = await client.post(f"{url}/convert", json={"title": "X Y Z"}, headers=ae)
    assert r.status_code == 409 and r.json()["code"] == "LEAD_NOT_QUALIFIED"

    await client.post(f"{url}/status", json={"to": "contacted"}, headers=ae)
    two = {**dict.fromkeys(ALL_FIVE, False), "budget": True, "csms": True}
    await client.patch(url, json={"qualification": two}, headers=ae)
    r = await client.post(f"{url}/status", json={"to": "qualified"}, headers=ae)
    assert r.status_code == 422 and r.json()["code"] == "QUALIFICATION_INCOMPLETE"
    assert "2 dari 5" in r.json()["message"]

    three = {**two, "technical_fit": True}
    await client.patch(url, json={"qualification": three}, headers=ae)
    r = await client.post(f"{url}/status", json={"to": "qualified"}, headers=ae)
    assert r.status_code == 200 and r.json()["qualification_count"] == 3

    # Checklist is locked once qualified; converting works once.
    r = await client.patch(url, json={"qualification": ALL_FIVE}, headers=ae)
    assert r.status_code == 409
    r = await client.post(f"{url}/convert", json={"title": "Well testing Blok X"}, headers=ae)
    assert r.status_code == 201
    opp = r.json()
    assert opp["number"].startswith("OPP-") and opp["stage"] == "qualified"
    assert opp["value"] == "4500000000" and opp["lead_number"] == lead["number"]
    r = await client.post(f"{url}/convert", json={"title": "Lagi"}, headers=ae)
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_CONVERTED"
    assert (await client.get(url, headers=ae)).json()["opportunity_number"] == opp["number"]


async def test_disqualify_needs_reason_and_is_final(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    lead = await _lead(client, ae)
    url = f"/api/crm/leads/{lead['id']}"
    r = await client.post(f"{url}/status", json={"to": "disqualified"}, headers=ae)
    assert r.status_code == 422 and r.json()["code"] == "REASON_REQUIRED"
    r = await client.post(
        f"{url}/status", json={"to": "disqualified", "reason": "Di luar wilayah kerja"}, headers=ae
    )
    assert r.status_code == 200 and r.json()["disqualify_reason"] == "Di luar wilayah kerja"
    assert (
        await client.post(f"{url}/status", json={"to": "contacted"}, headers=ae)
    ).status_code == 409
    assert (await client.patch(url, json={"need": "Ubah kebutuhan"}, headers=ae)).status_code == 409


async def test_opportunity_stage_machine(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    director = await login(await make_user("director"))
    opp = await _opportunity(client, ae)
    url = f"/api/crm/opportunities/{opp['id']}"

    r = await client.post(f"{url}/stage", json={"to": "quotation"}, headers=ae)
    assert r.status_code == 409 and r.json()["code"] == "BID_DECISION_REQUIRED"
    r = await client.post(f"{url}/stage", json={"to": "won"}, headers=ae)
    assert r.status_code == 409 and r.json()["code"] == "ILLEGAL_TRANSITION"

    rid = (
        await client.post(
            f"{url}/bid-decision",
            json={"scores": scores(5, 4, 4, 4, 4, 4), "proposal": "bid"},
            headers=ae,
        )
    ).json()["request_id"]
    await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=director)

    r = await client.post(f"{url}/stage", json={"to": "won"}, headers=ae)
    assert r.status_code == 409  # quotation must be submitted first
    r = await client.post(f"{url}/stage", json={"to": "submitted"}, headers=ae)
    assert r.status_code == 200 and r.json()["stage"] == "submitted"
    r = await client.post(f"{url}/stage", json={"to": "lost"}, headers=ae)
    assert r.status_code == 422 and r.json()["code"] == "REASON_REQUIRED"
    r = await client.post(f"{url}/stage", json={"to": "won"}, headers=ae)
    assert r.status_code == 200 and r.json()["probability"] == 100 and r.json()["won_at"]

    # Won is final.
    r = await client.post(f"{url}/stage", json={"to": "lost", "reason": "salah klik"}, headers=ae)
    assert r.status_code == 409
    r = await client.patch(url, json={"value": "1"}, headers=ae)
    assert r.status_code == 409 and r.json()["code"] == "OPPORTUNITY_CLOSED"

    history = await client.get(f"/api/audit/history/opportunity/{opp['id']}", headers=ae)
    assert history.status_code == 200, history.text
    actions = [e["action"] for e in history.json()["items"]]
    assert actions.count("stage_change") == 3  # quotation (Director), submitted, won


# ---------------------------------------------------------------- RBAC / scope / dashboard


async def test_data_scope_and_permissions(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae1_user = await make_user("account_executive")
    ae1 = await login(ae1_user)
    ae2 = await login(await make_user("account_executive"))
    hos = await login(await make_user("head_of_sales"))
    engineer = await login(await make_user("engineer"))

    lead = await _lead(client, ae1)
    assert (await client.get("/api/crm/leads", headers=ae2)).json()["total"] == 0
    assert (await client.get(f"/api/crm/leads/{lead['id']}", headers=ae2)).status_code == 404
    assert (
        await client.patch(f"/api/crm/leads/{lead['id']}", json={"need": "ubah dong"}, headers=ae2)
    ).status_code == 404
    assert (await client.get("/api/crm/leads", headers=hos)).json()["total"] == 1
    assert (await client.get("/api/crm/leads", headers=engineer)).status_code == 403

    # An AE cannot create a lead owned by someone else; Head of Sales can assign.
    me2 = (await client.get("/api/auth/me", headers=ae2)).json()["id"]
    r = await client.post(
        "/api/crm/leads",
        json={"company_name": "PT A", "source": "visit", "need": "Pumping", "owner_id": me2},
        headers=ae1,
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/crm/leads",
        json={"company_name": "PT A", "source": "visit", "need": "Pumping", "owner_id": me2},
        headers=hos,
    )
    assert r.status_code == 201 and r.json()["owner_id"] == me2

    export = await client.get("/api/crm/leads/export", headers=hos)
    assert export.status_code == 200 and export.content[:2] == b"PK"


async def test_lead_validation_messages(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    ae = await login(await make_user("account_executive"))
    r = await client.post(
        "/api/crm/leads", json={"source": "visit", "need": "Pumping unit"}, headers=ae
    )
    assert r.status_code == 422 and r.json()["code"] == "COMPANY_REQUIRED"
    r = await client.post(
        "/api/crm/leads",
        json={"client_code": "NOPE", "source": "visit", "need": "Pumping unit"},
        headers=ae,
    )
    assert r.status_code == 422 and r.json()["code"] == "CLIENT_INVALID"
    r = await client.post(
        "/api/crm/leads",
        json={"company_name": "PT A", "source": "tv", "need": "Pumping unit"},
        headers=ae,
    )
    assert r.status_code == 422


async def test_sales_dashboard(client: AsyncClient, make_user: MakeUser, login: Login) -> None:
    ae = await login(await make_user("account_executive"))
    hos = await login(await make_user("head_of_sales"))
    director = await login(await make_user("director"))
    a = await _opportunity(client, ae)  # 4.5 M at 40 %
    b = await _opportunity(client, ae)
    await client.patch(
        f"/api/crm/opportunities/{b['id']}", json={"value": "2000000000"}, headers=ae
    )
    rid = (
        await client.post(
            f"/api/crm/opportunities/{b['id']}/bid-decision",
            json={"scores": scores(5, 5, 5, 5, 5, 5), "proposal": "bid"},
            headers=ae,
        )
    ).json()["request_id"]
    await client.post(f"/api/workflow/requests/{rid}/approve", json={}, headers=director)
    await client.post(
        f"/api/crm/opportunities/{b['id']}/stage", json={"to": "submitted"}, headers=ae
    )
    await client.post(f"/api/crm/opportunities/{b['id']}/stage", json={"to": "won"}, headers=ae)
    c = await _opportunity(client, ae)
    await client.post(
        f"/api/crm/opportunities/{c['id']}/stage",
        json={"to": "lost", "reason": "Harga kalah"},
        headers=ae,
    )
    assert a["probability"] == 40

    d = (await client.get("/api/crm/dashboard", headers=hos)).json()
    assert d["open_count"] == 1
    assert d["open_pipeline"] == "4500000000"
    assert d["weighted_pipeline"] == "1800000000"
    assert d["won_count"] == 1 and d["lost_count"] == 1 and d["win_rate"] == "50.0"
    assert d["win_rate_target"] == "45"
    assert d["new_contract_value"] == "2000000000"
    assert d["contract_target"] == "80000000000"

    other = await login(await make_user("account_executive"))
    empty = (await client.get("/api/crm/dashboard", headers=other)).json()
    assert empty["open_count"] == 0 and empty["win_rate"] is None
