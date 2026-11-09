"""Phase 09 (LMS): SOP release assigns read-and-acknowledge and archives the old revision;
certificate renewal (scan in DMS) unblocks DOR crew selection; matrix onboarding assignment,
quiz, classroom attendance, training budget, compliance and evidence pack."""

import io
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from fpdf import FPDF
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.master.models import Employee
from app.services.numbering import today_jakarta
from app.services.storage import Storage
from tests.test_dor import _dor, _setup, _sync
from tests.test_inventory import _opening, masters  # noqa: F401

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
M = 1_000_000


def _pdf(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, text)
    return bytes(pdf.output())


async def _upload(client: AsyncClient, h: dict[str, str], et: str, eid: str, text: str) -> str:
    r = await client.post(
        "/api/attachments",
        data={"entity_type": et, "entity_id": eid},
        files={"file": ("f.pdf", _pdf(text), "application/pdf")},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_sop_release_archives_old_revision_and_assigns_training(
    client: AsyncClient, make_user: MakeUser, login: Login, storage: Storage
) -> None:
    owner = await login(await make_user("qhse_coordinator"))
    director = await login(await make_user("director"))
    fe = await login(await make_user("field_engineer"))
    office = await login(await make_user("procurement_officer"))
    hcbp = await login(await make_user("hcbp_officer"))
    doc = (
        await client.post(
            "/api/dms/controlled",
            json={
                "code": "GEK-BPM-001-SOP-12",
                "title": "SOP Isolasi energi (LOTO)",
                "kind": "sop",
                "affected_roles": ["field_engineer"],
            },
            headers=owner,
        )
    ).json()
    url = f"/api/dms/controlled/{doc['id']}"

    async def release(n: int) -> str:
        att = await _upload(client, owner, "controlled_doc", doc["id"], f"LOTO revisi {n}")
        rev = (
            await client.post(
                f"{url}/revisions",
                json={"change_summary": f"Rev {n}", "attachment_id": att},
                headers=owner,
            )
        ).json()
        sub = (await client.post(f"{url}/revisions/{rev['id']}/submit", headers=owner)).json()
        r = await client.post(
            f"/api/workflow/requests/{sub['request_id']}/approve", json={}, headers=director
        )
        assert r.status_code == 200, r.text
        return str(rev["id"])

    rev0 = await release(0)
    mine = (await client.get("/api/lms/my", headers=fe)).json()
    assert [(a["kind"], a["reason"], a["document"]["revision_id"]) for a in mine] == [
        ("acknowledge", "sop_revision", rev0)
    ]
    assert (await client.get("/api/lms/my", headers=office)).json() == []  # not an affected role
    rev1 = await release(1)
    revs = {
        r["revision"]: r["status"]
        for r in (await client.get(url, headers=owner)).json()["revisions"]
    }
    assert revs == {0: "uncontrolled", 1: "effective"}
    mine = (await client.get("/api/lms/my", headers=fe)).json()
    assert [a["document"]["revision_id"] for a in mine] == [rev1]  # Rev 0 task cancelled
    r = await client.post(f"/api/lms/assignments/{mine[0]['id']}/acknowledge", headers=office)
    assert r.status_code == 403
    r = await client.post(f"/api/lms/assignments/{mine[0]['id']}/acknowledge", headers=fe)
    assert r.status_code == 200 and r.json()["status"] == "completed"
    pack = await client.get("/api/lms/evidence-pack", headers=hcbp)
    wb = load_workbook(io.BytesIO(pack.content))
    rows = list(wb["Konfirmasi SOP"].iter_rows(values_only=True))
    assert ("GEK-BPM-001-SOP-12", 1, "completed") in {(r[1], r[2], r[3]) for r in rows[1:]}


async def test_certificate_renewal_unblocks_dor_crew_selection(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    masters: None,  # noqa: F811
    storage: Storage,
) -> None:
    fe_user = await make_user("field_engineer")
    p, rates = await _setup(sessionmaker, [fe_user])
    await _opening(sessionmaker, "ITM-1", "WH-RKN", 4, 24 * M)
    fe = await login(fe_user)
    hcbp = await login(await make_user("hcbp_officer"))
    body = _dor(rates, crew=[{"employee_code": "E-2", "rate_id": rates["fe"], "hours": "12"}])
    r = await _sync(client, fe, p, body)
    assert r.status_code == 422 and "Budi Kadaluarsa" in r.json()["message"]
    # The H2S course renews the H2S certificate; the expired one gets a renewal task.
    r = await client.put(
        "/api/lms/courses/H2S-AWR",
        json={
            "code": "H2S-AWR",
            "title": "H2S awareness",
            "kind": "classroom",
            "validity_months": 24,
            "certificate_name": "H2S",
        },
        headers=hcbp,
    )
    assert r.status_code == 200, r.text
    assert (await client.post("/api/lms/run", headers=hcbp)).json()["assigned"] >= 1
    tasks = (
        await client.get("/api/lms/assignments", params={"employee_code": "E-2"}, headers=hcbp)
    ).json()
    assert [(t["reason"], t["course"]["code"], t["status"]) for t in tasks] == [
        ("certificate_expiry", "H2S-AWR", "assigned")
    ]
    async with sessionmaker() as s:
        emp_id = str(
            (await s.execute(select(Employee.id).where(Employee.code == "E-2"))).scalar_one()
        )
    expiry = (today_jakarta() + timedelta(days=730)).isoformat()
    r = await client.post(
        "/api/lms/certificates/renew",
        json={
            "employee_code": "E-2",
            "name": "H2S",
            "number": "H2S-2026-88",
            "expiry_date": expiry,
            "attachment_id": str(uuid.uuid4()),
        },
        headers=hcbp,
    )
    assert r.status_code == 422 and r.json()["code"] == "SCAN_REQUIRED"
    scan = await _upload(client, hcbp, "employees", emp_id, "Sertifikat H2S Budi")
    r = await client.post(
        "/api/lms/certificates/renew",
        json={
            "employee_code": "E-2",
            "name": "H2S",
            "number": "H2S-2026-88",
            "expiry_date": expiry,
            "attachment_id": scan,
        },
        headers=hcbp,
    )
    assert r.status_code == 200, r.text
    h2s = [c for c in r.json()["certificates"] if c["name"] == "H2S"]
    assert len(h2s) == 1 and h2s[0]["expiry_date"] == expiry and h2s[0]["attachment_id"] == scan
    tasks = (
        await client.get("/api/lms/assignments", params={"employee_code": "E-2"}, headers=hcbp)
    ).json()
    assert tasks[0]["status"] == "completed"
    # The mobilisation gate is lifted: E-2 can be on the DOR now.
    r = await _sync(client, fe, p, body)
    assert r.status_code == 201, r.text
    assert [c["employee_code"] for c in r.json()["crew"]] == ["E-2"]


async def test_matrix_quiz_attendance_budget_and_compliance(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    hcbp = await login(await make_user("hcbp_officer"))
    learner_user = await make_user("field_engineer")
    async with sessionmaker() as s:
        s.add(
            Employee(
                code="E-NEW",
                full_name="Dian Baru",
                position="Field Engineer",
                position_code="FE",
                department_code=None,
                is_field=True,
                join_date=today_jakarta() - timedelta(days=3),
            )
        )
        await s.commit()
        await s.execute(
            update(User).where(User.id == learner_user.id).values(employee_code="E-NEW")
        )
        await s.commit()
    learner = await login(learner_user)
    quiz: dict[str, Any] = {
        "code": "SOP-INDUKSI",
        "title": "Induksi HSE",
        "kind": "quiz",
        "pass_score": 100,
        "questions": [
            {"q": "Warna tanda bahaya?", "options": ["Merah", "Hijau"], "answer": 0},
            {"q": "APD wajib?", "options": ["Sandal", "Safety shoes"], "answer": 1},
        ],
    }
    assert (
        await client.put("/api/lms/courses/SOP-INDUKSI", json=quiz, headers=hcbp)
    ).status_code == 200
    cls = {
        "code": "FIRST-AID",
        "title": "Pertolongan pertama",
        "kind": "classroom",
        "cost": "2000000",
        "validity_months": 36,
    }
    assert (
        await client.put("/api/lms/courses/FIRST-AID", json=cls, headers=hcbp)
    ).status_code == 200
    await client.put(
        "/api/lms/positions/FE", json={"code": "FE", "name": "Field Engineer"}, headers=hcbp
    )
    r = await client.put(
        "/api/lms/positions/FE/requirements",
        json={"requirements": [{"course_code": "SOP-INDUKSI"}, {"course_code": "FIRST-AID"}]},
        headers=hcbp,
    )
    assert r.status_code == 200
    assert (await client.post("/api/lms/run", headers=hcbp)).json()["assigned"] == 2
    mine = (await client.get("/api/lms/my", headers=learner)).json()
    assert {a["course"]["code"]: a["reason"] for a in mine} == {
        "SOP-INDUKSI": "onboarding",
        "FIRST-AID": "onboarding",
    }
    quiz_task = next(a for a in mine if a["course"]["code"] == "SOP-INDUKSI")
    assert "answer" not in quiz_task["course"]["questions"][0]  # answers are not sent to learners
    r = await client.post(
        f"/api/lms/assignments/{quiz_task['id']}/quiz", json={"answers": [0, 0]}, headers=learner
    )
    assert r.json()["passed"] is False and r.json()["status"] == "assigned"
    r = await client.post(
        f"/api/lms/assignments/{quiz_task['id']}/quiz", json={"answers": [0, 1]}, headers=learner
    )
    assert r.json()["passed"] is True and r.json()["status"] == "completed"
    # Classroom: attendance completes the task and books the cost.
    sess = (
        await client.post(
            "/api/lms/sessions",
            json={"course_code": "FIRST-AID", "starts_on": today_jakarta().isoformat()},
            headers=hcbp,
        )
    ).json()
    r = await client.post(
        f"/api/lms/sessions/{sess['id']}/attendance",
        json={"rows": [{"employee_code": "E-NEW", "attended": True, "passed": True, "score": 90}]},
        headers=hcbp,
    )
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert (await client.get("/api/lms/my", headers=learner)).json() == []
    comp = (await client.get("/api/lms/compliance", headers=hcbp)).json()
    dian = next(x for x in comp if x["employee_code"] == "E-NEW")
    assert dian["compliance_pct"] == 100 and {i["status"] for i in dian["items"]} == {"valid"}
    # Running again does not re-assign completed, still-valid courses.
    assert (await client.post("/api/lms/run", headers=hcbp)).json()["assigned"] == 0
    await client.put(
        f"/api/lms/budget/{today_jakarta().year}",
        json={"department_code": "OPS", "amount": "10000000"},
        headers=hcbp,
    )
    budget = (await client.get(f"/api/lms/budget/{today_jakarta().year}", headers=hcbp)).json()
    assert {b["department"]: b["budget"] for b in budget}["OPS"] == "10000000"
    # Learners cannot manage the catalogue.
    assert (await client.put("/api/lms/courses/X", json=cls, headers=learner)).status_code == 403


async def test_renew_upload_stores_scan_and_renews(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
) -> None:
    async with sessionmaker() as s:
        s.add(
            Employee(
                code="E-CR",
                full_name="Cahya Rig",
                position="Operator",
                is_field=True,
                certificates=[{"name": "BOSIET", "expiry_date": "2020-01-01", "mandatory": True}],
            )
        )
        await s.commit()
    hcbp = await login(await make_user("hcbp_officer"))
    expiry = (today_jakarta() + timedelta(days=1460)).isoformat()
    r = await client.post(
        "/api/lms/certificates/renew-upload",
        data={"employee_code": "E-CR", "name": "bosiet", "number": "B-77", "expiry_date": expiry},
        files={"file": ("bosiet.pdf", _pdf("BOSIET Cahya"), "application/pdf")},
        headers=hcbp,
    )
    assert r.status_code == 200, r.text
    certs = r.json()["certificates"]
    assert len(certs) == 1 and certs[0]["name"] == "BOSIET" and certs[0]["expiry_date"] == expiry
    async with sessionmaker() as s:
        emp_id = (await s.execute(select(Employee.id).where(Employee.code == "E-CR"))).scalar_one()
    files = (
        await client.get(
            "/api/attachments",
            params={"entity_type": "employees", "entity_id": str(emp_id)},
            headers=hcbp,
        )
    ).json()
    assert [f["id"] for f in files] == [certs[0]["attachment_id"]]
