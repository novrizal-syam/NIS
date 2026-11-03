import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.auth.principal import Principal
from app.auth.roles_seed import SYSTEM_ROLES
from app.core.errors import AppError
from app.services.audit import AuditLog
from app.services.numbering import today_jakarta
from app.workflow import engine, service
from app.workflow.models import ApprovalRequest, DoaRule
from app.workflow.rules_seed import DOC_TYPES, RULES

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
PrincipalOf = Callable[..., Awaitable[Principal]]
M = 1_000_000

EVENTS: list[tuple[str, str, list[uuid.UUID]]] = []
HOOKS: list[tuple[str, str]] = []


async def _record_event(
    _: AsyncSession, event: str, request: ApprovalRequest, recipients: list[uuid.UUID]
) -> None:
    EVENTS.append((event, request.doc_number, recipients))


engine.on_event(_record_event)


FAKE_DOC_TYPES = ("purchase_requisition", "capex", "tender_package", "payment_run")


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    """Fake document hooks for this module only; the real ones (e.g. tender_package from
    phase 02d) are restored afterwards so other test modules see them."""
    EVENTS.clear()
    HOOKS.clear()
    saved = dict(engine._hooks)
    for dt in FAKE_DOC_TYPES:
        engine.register_document(dt, on_approved=_approved, on_rejected=_rejected)
    yield
    engine._hooks.clear()
    engine._hooks.update(saved)


async def _approved(_: AsyncSession, r: ApprovalRequest) -> None:
    HOOKS.append(("approved", r.doc_number))


async def _rejected(_: AsyncSession, r: ApprovalRequest) -> None:
    HOOKS.append(("rejected", r.doc_number))


async def _submit(
    s: AsyncSession,
    p: Principal,
    doc_type: str = "purchase_requisition",
    amount: int | None = 10 * M,
    number: str = "PR-26-001",
    **ctx: Any,
) -> ApprovalRequest:
    req = await engine.submit(
        s,
        p,
        doc_type=doc_type,
        doc_id=uuid.uuid4(),
        doc_number=number,
        title=f"Uji {number}",
        amount=amount,
        context=ctx,
    )
    await s.commit()
    return req


# --- routing ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc_type", "ctx", "roles"),
    [
        ("purchase_requisition", {"amount": 50 * M}, [["head_of_operation"]]),
        ("purchase_requisition", {"amount": 50 * M + 1}, [["head_of_finance"]]),
        ("purchase_requisition", {"amount": 500 * M}, [["head_of_finance"]]),
        ("purchase_requisition", {"amount": 500 * M + 1}, [["director"]]),
        ("quotation", {"margin_pct": 25}, [["head_of_sales"]]),
        ("quotation", {"margin_pct": "24.9"}, [["director"]]),
        ("project_budget", {"total_cost": 2_000 * M}, [["lead_controller"], ["head_of_operation"]]),
        ("project_budget", {"total_cost": 2_000 * M + 1}, [["lead_controller"], ["director"]]),
        ("bcr", {"source": "contingency_release", "increase_pct": 30}, [["head_of_operation"]]),
        ("bcr", {"source": "transfer"}, [["head_of_operation"]]),
        ("bcr", {"source": "budget_increase", "increase_pct": 10}, [["head_of_operation"]]),
        ("bcr", {"source": "budget_increase", "increase_pct": 11}, [["director"]]),
        ("bcr", {"source": "transfer", "revenue_change": True}, [["director"]]),
        ("tender_package", {}, [["director", "head_of_operation"]]),
        ("payment_run", {"amount": 1_000 * M}, [["head_of_finance"]]),
        ("payment_run", {"amount": 1_000 * M + 1}, [["director"]]),
        ("capex", {"amount": 5_000 * M}, [["director"]]),
        ("capex", {"amount": 5_000 * M + 1}, [["director"], ["shareholders"]]),
        ("dor", {"service_line": "epcom"}, [["epcom_superintendent"]]),
        ("dor", {"service_line": "ofs"}, [["ofs_superintendent"]]),
        ("cash_advance", {}, [["head_of_operation"]]),
        ("manual_journal", {}, [["lead_controller"]]),
        ("payroll", {}, [["head_of_finance"]]),
        ("doa_change", {}, [["director"]]),
    ],
)
async def test_rule_routing(
    session: AsyncSession, doc_type: str, ctx: dict[str, Any], roles: list[list[str]]
) -> None:
    rule = await engine.select_rule(session, doc_type, ctx)
    assert rule is not None
    by_seq: dict[int, list[str]] = {}
    for st in rule.steps:
        by_seq.setdefault(st.seq, []).append(st.approver_role)
    assert [sorted(v) for _, v in sorted(by_seq.items())] == roles


async def test_no_matching_rule(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    po = await make_user("procurement_officer")
    async with sessionmaker() as s:
        p = await principal_of(po, s)
        with pytest.raises(AppError) as err:
            # Best-score RFQ award has no approval rule.
            await engine.submit(
                s,
                p,
                doc_type="rfq_award",
                doc_id="x",
                doc_number="RFQ-1",
                title="t",
                context={"non_best_score": False},
            )
        assert err.value.code == "NO_DOA_RULE"


def test_every_approver_role_has_module_approve_permission() -> None:
    grants = {r.code: {(m, a) for m, a, _ in r.grants} for r in SYSTEM_ROLES}
    for rule in RULES:
        module = DOC_TYPES[rule.doc_type][1]
        for st in rule.steps:
            assert (module, "approve") in grants[st.role], (rule.doc_type, st.role)


# --- lifecycle --------------------------------------------------------------------------------


async def test_single_step_approval_and_hooks(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    eng, hoo = await make_user("engineer"), await make_user("head_of_operation")
    async with sessionmaker() as s:
        req = await _submit(s, await principal_of(eng, s), amount=40 * M)
        assert [st.status for st in req.steps] == ["pending"]
        assert EVENTS[-1][0] == "submitted" and hoo.id in EVENTS[-1][2]

        await engine.approve(s, await principal_of(hoo, s), req.id, "OK")
        await s.commit()
        assert req.status == "approved"
        assert req.steps[0].acted_by == hoo.id
        assert HOOKS == [("approved", "PR-26-001")]
        assert EVENTS[-1][0] == "approved" and EVENTS[-1][2] == [eng.id]


async def test_requester_cannot_approve_own_document(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    # HoO may both raise and approve PRs <= 50 jt, but never their own.
    hoo = await make_user("head_of_operation")
    async with sessionmaker() as s:
        p = await principal_of(hoo, s)
        req = await _submit(s, p, amount=10 * M)
        for action in (engine.approve, engine.reject):
            with pytest.raises(AppError) as err:
                await action(s, p, req.id, "saya sendiri")
            assert err.value.code == "SOD_SELF_APPROVAL"


async def test_wrong_role_cannot_approve(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    eng, hof, admin = (
        await make_user("engineer"),
        await make_user("head_of_finance"),
        await make_user("admin"),
    )
    async with sessionmaker() as s:
        req = await _submit(s, await principal_of(eng, s), amount=10 * M)  # -> HoO
        for user in (hof, admin):
            with pytest.raises(AppError) as err:
                await engine.approve(s, await principal_of(user, s), req.id)
            assert err.value.code == "NOT_APPROVER"


async def test_sequential_steps_capex_to_rups(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    dirr, rups, fin = (
        await make_user("director"),
        await make_user("shareholders"),
        await make_user("finance_officer"),
    )
    async with sessionmaker() as s:
        req = await _submit(s, await principal_of(fin, s), "capex", 6_000 * M, "CPX-26-001")
        assert [st.status for st in req.steps] == ["pending", "waiting"]
        with pytest.raises(AppError):  # RUPS must wait for the Director
            await engine.approve(s, await principal_of(rups, s), req.id)

        await engine.approve(s, await principal_of(dirr, s), req.id)
        await s.commit()
        assert req.status == "pending" and req.current_seq == 2
        assert EVENTS[-1][0] == "step_activated" and EVENTS[-1][2] == [rups.id]

        await engine.approve(s, await principal_of(rups, s), req.id)
        await s.commit()
        assert req.status == "approved"
        assert HOOKS == [("approved", "CPX-26-001")]


async def test_parallel_steps_need_both_and_one_person_cannot_do_both(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    ts = await make_user("tender_specialist")
    hoo, dirr = await make_user("head_of_operation"), await make_user("director")
    both = await make_user("head_of_operation", "director")
    async with sessionmaker() as s:
        req = await _submit(s, await principal_of(ts, s), "tender_package", None, "TND-1")
        assert {st.status for st in req.steps} == {"pending"}

        await engine.approve(s, await principal_of(both, s), req.id)
        await s.commit()
        assert req.status == "pending"
        with pytest.raises(AppError) as err:
            await engine.approve(s, await principal_of(both, s), req.id)
        assert err.value.code == "SOD_ALREADY_ACTED"

        remaining = next(st for st in req.steps if st.status == "pending").approver_role
        await engine.approve(
            s, await principal_of(dirr if remaining == "director" else hoo, s), req.id
        )
        await s.commit()
        assert req.status == "approved"


async def test_reject_requires_comment_and_returns_document(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    fin, dirr = await make_user("finance_officer"), await make_user("director")
    async with sessionmaker() as s:
        req = await _submit(s, await principal_of(fin, s), "capex", 6_000 * M, "CPX-26-002")
        p = await principal_of(dirr, s)
        with pytest.raises(AppError) as err:
            await engine.reject(s, p, req.id, "  ")
        assert err.value.code == "COMMENT_REQUIRED"

        await engine.reject(s, p, req.id, "Business case belum lengkap")
        await s.commit()
        assert req.status == "rejected"
        assert [st.status for st in req.steps] == ["rejected", "skipped"]
        assert HOOKS == [("rejected", "CPX-26-002")]

        with pytest.raises(AppError) as err:
            await engine.approve(s, p, req.id)
        assert err.value.code == "APPROVAL_CLOSED"


async def test_cancel_only_by_requester_and_resubmit(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    eng, other = await make_user("engineer"), await make_user("engineer")
    async with sessionmaker() as s:
        p = await principal_of(eng, s)
        doc_id = uuid.uuid4()
        req = await engine.submit(
            s,
            p,
            doc_type="purchase_requisition",
            doc_id=doc_id,
            doc_number="PR-9",
            title="t",
            amount=1 * M,
        )
        await s.commit()
        with pytest.raises(AppError) as err:
            await engine.submit(
                s,
                p,
                doc_type="purchase_requisition",
                doc_id=doc_id,
                doc_number="PR-9",
                title="t",
                amount=1 * M,
            )
        assert err.value.code == "ALREADY_SUBMITTED"

        with pytest.raises(AppError):
            await engine.cancel(s, await principal_of(other, s), req.id)
        await engine.cancel(s, p, req.id, "salah input")
        await s.commit()
        assert req.status == "cancelled"
        # A cancelled or rejected document can be submitted again.
        await engine.submit(
            s,
            p,
            doc_type="purchase_requisition",
            doc_id=doc_id,
            doc_number="PR-9",
            title="t",
            amount=1 * M,
        )
        await s.commit()


async def test_delegation_window_and_revocation(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    eng, dirr, hof = (
        await make_user("engineer"),
        await make_user("director"),
        await make_user("head_of_finance"),
    )
    today = today_jakarta()
    async with sessionmaker() as s:
        req = await _submit(s, await principal_of(eng, s), amount=600 * M)  # -> Director
        p_dir, p_hof = await principal_of(dirr, s), await principal_of(hof, s)

        future = await service.create_delegation(
            s,
            p_dir,
            delegate_id=hof.id,
            role_code="director",
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=5),
            reason="Cuti",
        )
        await s.commit()
        with pytest.raises(AppError):
            await engine.approve(s, p_hof, req.id)

        current = await service.create_delegation(
            s,
            p_dir,
            delegate_id=hof.id,
            role_code="director",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            reason="Dinas",
        )
        await s.commit()
        assert await engine.inbox_count(s, p_hof) == 1

        await service.revoke_delegation(s, p_dir, current.id)
        await s.commit()
        assert await engine.inbox_count(s, p_hof) == 0
        await service.revoke_delegation(s, p_dir, future.id)

        again = await service.create_delegation(
            s,
            p_dir,
            delegate_id=hof.id,
            role_code=None,
            start_date=today,
            end_date=today,
            reason="Rapat RUPS",
        )
        await s.commit()
        await engine.approve(s, p_hof, req.id, "atas nama Direktur")
        await s.commit()
        assert req.status == "approved"
        assert req.steps[0].acted_by == hof.id and req.steps[0].on_behalf_of == dirr.id
        assert again.id


async def test_delegation_validation(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    dirr, eng = await make_user("director"), await make_user("engineer")
    today = today_jakarta()
    async with sessionmaker() as s:
        p = await principal_of(dirr, s)
        bad = [
            dict(delegate_id=dirr.id, role_code=None, start_date=today, end_date=today),
            dict(
                delegate_id=eng.id,
                role_code=None,
                start_date=today,
                end_date=today - timedelta(days=1),
            ),
            dict(delegate_id=eng.id, role_code="cashier", start_date=today, end_date=today),
        ]
        for kw in bad:
            with pytest.raises(AppError):
                await service.create_delegation(s, p, reason="uji", **kw)  # type: ignore[arg-type]


async def test_delegate_cannot_approve_delegators_own_request(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    hoo, hof = await make_user("head_of_operation"), await make_user("head_of_finance")
    async with sessionmaker() as s:
        p_hoo = await principal_of(hoo, s)
        req = await _submit(s, p_hoo, amount=10 * M)  # HoO's own PR -> HoO step
        await service.create_delegation(
            s,
            p_hoo,
            delegate_id=hof.id,
            role_code="head_of_operation",
            start_date=today_jakarta(),
            end_date=today_jakarta(),
            reason="Cuti",
        )
        await s.commit()
        with pytest.raises(AppError) as err:
            await engine.approve(s, await principal_of(hof, s), req.id)
        assert err.value.code == "NOT_APPROVER"


async def test_bulk_approve(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    eng, hoo = await make_user("engineer"), await make_user("head_of_operation")
    async with sessionmaker() as s:
        p_eng = await principal_of(eng, s)
        a = await _submit(s, p_eng, amount=1 * M, number="PR-1")
        b = await _submit(s, p_eng, amount=2 * M, number="PR-2")
        big = await _submit(s, p_eng, amount=600 * M, number="PR-3")  # Director, not HoO
        ca = await _submit(s, p_eng, "cash_advance", 1 * M, "CA-1")
        results = await engine.bulk_approve(
            s, await principal_of(hoo, s), [a.id, b.id, big.id, ca.id], "purchase_requisition"
        )
        await s.commit()
        ok = {r.request_id: r for r in results}
        assert ok[a.id].ok and ok[b.id].ok
        assert ok[big.id].code == "NOT_APPROVER"
        assert ok[ca.id].code == "BULK_MIXED_TYPES"
        statuses: dict[str, str] = {
            n: st
            for n, st in (
                await s.execute(select(ApprovalRequest.doc_number, ApprovalRequest.status))
            ).all()
        }
        assert statuses == {
            "PR-1": "approved",
            "PR-2": "approved",
            "PR-3": "pending",
            "CA-1": "pending",
        }


async def test_escalation(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    eng, hoo, dirr = (
        await make_user("engineer"),
        await make_user("head_of_operation"),
        await make_user("director"),
    )
    async with sessionmaker() as s:
        req = await _submit(s, await principal_of(eng, s), amount=1 * M)
        assert await engine.escalate_overdue(s) == 0
        later = datetime.now(UTC) + timedelta(hours=49)
        assert await engine.escalate_overdue(s, later) == 1
        await s.commit()
        assert await engine.escalate_overdue(s, later) == 0
        event, number, recipients = EVENTS[-1]
        assert (event, number) == ("escalated", req.doc_number)
        assert set(recipients) == {hoo.id, dirr.id}


# --- rule changes through the engine ----------------------------------------------------------


async def test_rule_change_needs_director_approval(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    admin, dirr, eng = (
        await make_user("admin"),
        await make_user("director"),
        await make_user("engineer"),
    )
    async with sessionmaker() as s:
        rule = (
            await s.execute(
                select(DoaRule).where(
                    DoaRule.doc_type == "purchase_requisition", DoaRule.priority == 10
                )
            )
        ).scalar_one()
        payload = service.rule_payload(rule)
        payload["condition"] = {"field": "amount", "op": "<=", "value": 75 * M}
        p_admin = await principal_of(admin, s)
        change, req = await service.propose_rule_change(
            s, p_admin, rule_id=rule.id, payload=payload, reason="Naikkan batas HoO"
        )
        await s.commit()

        # Not applied yet: 60 jt still goes to HoF.
        r = await engine.select_rule(s, "purchase_requisition", {"amount": 60 * M})
        assert r is not None and r.steps[0].approver_role == "head_of_finance"
        with pytest.raises(AppError):  # Admin cannot approve their own change (nor any)
            await engine.approve(s, p_admin, req.id)

        await engine.approve(s, await principal_of(dirr, s), req.id)
        await s.commit()
        await s.refresh(change)
        assert change.status == "applied"
        s.expire_all()
        r = await engine.select_rule(s, "purchase_requisition", {"amount": 60 * M})
        assert r is not None and r.steps[0].approver_role == "head_of_operation"

        log = (
            await s.execute(select(AuditLog).where(AuditLog.entity_type == "doa_rule"))
        ).scalar_one()
        assert log.before is not None and log.after is not None
        assert log.after["condition"]["value"] == 75 * M
        assert eng.id  # unused helper user


async def test_rule_change_validation(
    make_user: MakeUser, principal_of: PrincipalOf, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    admin = await make_user("admin")
    base = {
        "doc_type": "cash_advance",
        "name": "Uji",
        "priority": 5,
        "condition": {},
        "escalation_hours": 24,
        "escalate_to_role": None,
        "is_active": True,
        "note": "",
        "steps": [
            {"seq": 1, "approver_role": "head_of_operation", "label": "", "approver_scope": "all"}
        ],
    }
    async with sessionmaker() as s:
        p = await principal_of(admin, s)
        for bad in (
            {**base, "doc_type": "nope"},
            {**base, "steps": []},
            {
                **base,
                "steps": [
                    {"seq": 1, "approver_role": "ghost", "label": "", "approver_scope": "all"}
                ],
            },
            {**base, "condition": {"field": "amount", "op": "~", "value": 1}},
        ):
            with pytest.raises(AppError):
                await service.propose_rule_change(s, p, rule_id=None, payload=bad, reason="uji uji")


# --- API --------------------------------------------------------------------------------------


async def test_inbox_api_and_export(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    principal_of: PrincipalOf,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    eng, hoo = await make_user("engineer"), await make_user("head_of_operation")
    async with sessionmaker() as s:
        p = await principal_of(eng, s)
        await _submit(s, p, amount=12_500_000, number="PR-26-031")
        await _submit(s, p, "cash_advance", 3 * M, "CA-26-001")

    h_hoo, h_eng = await login(hoo), await login(eng)
    assert (await client.get("/api/workflow/inbox/count", headers=h_hoo)).json() == {"count": 2}
    assert (await client.get("/api/workflow/inbox/count", headers=h_eng)).json() == {"count": 0}

    page = (
        await client.get("/api/workflow/inbox?doc_type=purchase_requisition", headers=h_hoo)
    ).json()
    assert page["total"] == 1 and page["counts"] == {"purchase_requisition": 1, "cash_advance": 1}
    item = page["items"][0]
    assert item["doc_number"] == "PR-26-031"
    assert item["amount"] == "12500000"  # plain digits, never "1.25E+7"

    detail = (
        await client.get(f"/api/workflow/requests/{item['request_id']}", headers=h_hoo)
    ).json()
    assert (
        detail["can_act"] is True
        and detail["steps"][0]["approver_role_name"] == "Head of Operation"
    )
    mine = (await client.get(f"/api/workflow/requests/{item['request_id']}", headers=h_eng)).json()
    assert mine["can_act"] is False and mine["can_cancel"] is True

    own = await client.post(
        f"/api/workflow/requests/{item['request_id']}/approve", json={}, headers=h_eng
    )
    assert own.status_code == 403 and own.json()["code"] == "SOD_SELF_APPROVAL"
    no_reason = await client.post(
        f"/api/workflow/requests/{item['request_id']}/reject", json={"comment": ""}, headers=h_hoo
    )
    assert no_reason.json()["code"] == "COMMENT_REQUIRED"

    xlsx = await client.get("/api/workflow/inbox/export", headers=h_hoo)
    assert xlsx.status_code == 200
    import io

    ws = load_workbook(io.BytesIO(xlsx.content)).active
    assert ws is not None
    assert [c.value for c in ws[1]][:3] == ["Nomor", "Jenis", "Judul"]
    assert {ws.cell(row=i, column=4).value for i in (2, 3)} == {12_500_000, 3_000_000}

    ok = await client.post(
        f"/api/workflow/requests/{item['request_id']}/approve", json={}, headers=h_hoo
    )
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert (await client.get("/api/workflow/inbox/count", headers=h_hoo)).json() == {"count": 1}


async def test_rules_api_permissions(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    eng, admin = await make_user("engineer"), await make_user("admin")
    h_eng, h_admin = await login(eng), await login(admin)
    assert (await client.get("/api/workflow/rules", headers=h_eng)).status_code == 403
    rules = (await client.get("/api/workflow/rules", headers=h_admin)).json()
    assert len(rules) == len(RULES)
    pr = [r for r in rules if r["doc_type"] == "purchase_requisition"]
    assert [r["condition_text"] for r in pr] == [
        "amount ≤ 50.000.000",
        "amount ≤ 500.000.000",
        "Semua",
    ]

    body = {
        "rule_id": pr[0]["id"],
        "reason": "Uji perubahan",
        "rule": {
            **{
                k: pr[0][k]
                for k in (
                    "name",
                    "priority",
                    "condition",
                    "escalation_hours",
                    "escalate_to_role",
                    "is_active",
                    "note",
                    "steps",
                )
            },
            "doc_type": "purchase_requisition",
        },
    }
    assert (
        await client.post("/api/workflow/rule-changes", json=body, headers=h_eng)
    ).status_code == 403
    body["rule"]["condition"] = {"field": "amount", "op": "<=", "value": 75_000_000}
    res = await client.post("/api/workflow/rule-changes", json=body, headers=h_admin)
    assert res.status_code == 201
    detail = (
        await client.get(f"/api/workflow/requests/{res.json()['request_id']}", headers=h_admin)
    ).json()
    assert detail["change_reason"] == "Uji perubahan"
    assert detail["changes"] == [
        {"label": "Kondisi", "before": "amount ≤ 50.000.000", "after": "amount ≤ 75.000.000"}
    ]
    changes = (await client.get("/api/workflow/rule-changes", headers=h_admin)).json()
    assert (
        changes[0]["status"] == "pending" and changes[0]["request_id"] == res.json()["request_id"]
    )
    rules = (await client.get("/api/workflow/rules", headers=h_admin)).json()
    assert next(r for r in rules if r["id"] == pr[0]["id"])["pending_change"] is True


async def test_user_lookup(client: AsyncClient, make_user: MakeUser, login: Login) -> None:
    u = await make_user("engineer", email="budi.santoso@gek.co.id")
    res = await client.get("/api/users/lookup?q=budi", headers=await login(u))
    assert [x["email"] for x in res.json()] == ["budi.santoso@gek.co.id"]


def test_money_serializes_without_exponent() -> None:
    from app.workflow.schemas import InboxItem

    item = InboxItem(
        request_id=uuid.uuid4(),
        doc_type="purchase_requisition",
        doc_type_label="PR",
        doc_number="PR-1",
        title="t",
        amount=Decimal("1.250E+7"),
        currency="IDR",
        requester_name="x",
        submitted_at=datetime.now(UTC),
        step_label="s",
        due_at=None,
        overdue=False,
        escalated=False,
    )
    assert item.model_dump(mode="json")["amount"] == "12500000"
