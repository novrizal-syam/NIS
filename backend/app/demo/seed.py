"""Load or remove demo data.

python -m app.demo.seed            # load (refuses if demo data already exists)
python -m app.demo.seed --remove   # remove every is_demo row (audited)
"""

import argparse
import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as _models  # noqa: F401  (register every model)
from app.auth import service as auth_service
from app.auth.models import RefreshToken, User, UserRole
from app.core.db import SessionLocal
from app.core.errors import ConflictError
from app.crm.models import BidDecision, Lead, Opportunity, Quotation
from app.crm.service import QUALIFICATION
from app.demo import data as d
from app.letters.models import OutgoingLetter
from app.master.models import (
    Asset,
    Client,
    CostCenter,
    Department,
    Employee,
    FiscalPeriod,
    FxRate,
    Item,
    PriceItem,
    Vendor,
    Warehouse,
)
from app.notifications.models import Notification
from app.services import audit, numbering
from app.services.numbering import today_jakarta
from app.workflow.models import ApprovalRequest, ApprovalStep, Delegation

# Removal order: children before parents.
DEMO_TABLES: tuple[Any, ...] = (
    PriceItem,
    FxRate,
    Employee,
    CostCenter,
    Client,
    Vendor,
    Item,
    Warehouse,
    Asset,
    FiscalPeriod,
)


@dataclass
class Summary:
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, name: str, n: int) -> None:
        self.counts[name] = self.counts.get(name, 0) + n


async def demo_exists(session: AsyncSession) -> bool:
    # Demo users mark demo data (departments may be real ones from the setup wizard).
    found = await session.execute(select(User.id).where(User.is_demo.is_(True)).limit(1))
    return found.first() is not None


async def demo_counts(session: AsyncSession) -> dict[str, int]:
    out: dict[str, int] = {}
    for model in (
        Lead,
        Opportunity,
        BidDecision,
        Quotation,
        OutgoingLetter,
        *DEMO_TABLES,
        User,
        Department,
    ):
        n = await session.execute(select(func.count()).where(model.is_demo.is_(True)))
        out[model.__tablename__] = int(n.scalar_one())
    return out


def _cert(name: str, number: str, expiry: date) -> dict[str, Any]:
    return {"name": name, "number": number, "expiry_date": expiry.isoformat()}


async def load(
    session: AsyncSession, *, password: str, actor_id: uuid.UUID | None = None
) -> Summary:
    if await demo_exists(session):
        raise ConflictError("DEMO_EXISTS", "Data demo sudah ada. Hapus dulu sebelum memuat ulang.")
    today = today_jakarta()
    s = Summary()
    demo = {"is_demo": True, "created_by": actor_id}

    # Departments may already exist (setup wizard); demo only adds the missing ones.
    have_depts = set((await session.execute(select(Department.code))).scalars())
    new_depts = [(c, n) for c, n in d.DEPARTMENTS if c not in have_depts]
    session.add_all(Department(code=c, name=n, **demo) for c, n in new_depts)
    await session.flush()
    have_cc = set((await session.execute(select(CostCenter.code))).scalars())
    new_cc = [x for x in d.COST_CENTERS if x[0] not in have_cc]
    session.add_all(CostCenter(code=c, name=n, department_code=dep, **demo) for c, n, dep in new_cc)
    s.add("departments", len(new_depts))
    s.add("cost_centers", len(new_cc))

    dept_ids = dict((await session.execute(select(Department.code, Department.id))).tuples().all())
    for role, (name, dept) in d.USERS.items():
        user, _ = await auth_service.create_user(
            session,
            email=f"{role.replace('_', '.')}@{d.EMAIL_DOMAIN}",
            full_name=name,
            role_codes=[role],
            actor_id=actor_id,
            password=password,
            department_id=dept_ids[dept],
            is_demo=True,
        )
        user.must_change_password = False  # demo convenience; 2FA stays required per role
    s.add("users", len(d.USERS))

    session.add_all(
        Client(
            code=c,
            name=n,
            npwp=npwp,
            csms_status=csms,
            payment_term_days=term,
            currency=cur,
            contact_name="Procurement Dept.",
            **demo,
        )
        for c, n, npwp, csms, term, cur in d.CLIENTS
    )
    s.add("clients", len(d.CLIENTS))

    n = 0
    for cat in d.VENDOR_CATEGORIES:
        for i, name in enumerate(d.VENDOR_NAMES[cat]):
            n += 1
            session.add(
                Vendor(
                    code=f"VND-{n:03d}",
                    name=name,
                    category=cat,
                    # One vendor still waiting for CSMS: excluded from RFQs later.
                    status="csms_pending" if (cat, i) == ("subcontract", 2) else "qualified",
                    rating=Decimal(["4.5", "4.0", "3.5"][i]),
                    npwp=f"0{n % 10}.111.222.{n:01d}-0{n % 9}1.000",
                    bank_name="Bank Mandiri",
                    bank_account_no=f"12300{n:05d}",
                    bank_account_name=name,
                    legal_docs=[
                        _cert("NIB", f"91200{n:05d}", today + timedelta(days=400)),
                        _cert(
                            "SIUP", f"SIUP-{n:04d}", today + timedelta(days=45 if n == 1 else 300)
                        ),
                    ],
                    **demo,
                )
            )
    s.add("vendors", n)

    for code, name, pos, salary, ptkp in d.FIELD_EMPLOYEES:
        idx = int(code[-2:])
        session.add(
            Employee(
                code=code,
                full_name=name,
                position=pos,
                department_code="OPS",
                is_field=True,
                join_date=date(2021, idx, 1),
                basic_salary=Decimal(salary),
                ptkp_status=ptkp,
                nik=f"3604010101{idx:02d}0001",
                npwp=f"09.876.543.{idx}-401.000",
                bank_name="Bank Mandiri",
                bank_account_no=f"14000{idx:05d}",
                bpjs_kesehatan_no=f"00012345{idx:05d}",
                bpjs_tk_no=f"21000{idx:06d}",
                certificates=[
                    # One expired and one close to expiry so alerts and gates can be tried.
                    _cert(
                        "BOSIET",
                        f"BOS-{idx:04d}",
                        today - timedelta(days=5)
                        if idx == 4
                        else today + timedelta(days=25 if idx == 3 else 500),
                    ),
                    _cert("H2S Awareness", f"H2S-{idx:04d}", today + timedelta(days=200)),
                ],
                **demo,
            )
        )
    for code, name, pos, dept, salary, ptkp in d.OFFICE_EMPLOYEES:
        session.add(
            Employee(
                code=code,
                full_name=name,
                position=pos,
                department_code=dept,
                is_field=False,
                basic_salary=Decimal(salary),
                ptkp_status=ptkp,
                **demo,
            )
        )
    s.add("employees", len(d.FIELD_EMPLOYEES) + len(d.OFFICE_EMPLOYEES))

    session.add_all(
        Item(
            code=c,
            name=n,
            uom=u,
            category=cat,
            reorder_point=Decimal(rop),
            last_price=Decimal(p),
            **demo,
        )
        for c, n, u, cat, rop, p in d.ITEMS
    )
    session.add_all(
        Warehouse(code=c, name=n, kind=k, location=loc, project_code=prj, **demo)
        for c, n, k, loc, prj in d.WAREHOUSES
    )
    session.add_all(
        Asset(
            code=c,
            name=n,
            asset_class=cls,
            criticality=crit,
            internal_day_rate=Decimal(rate),
            serial_no=sn,
            certificates=[
                _cert(
                    "Sertifikat inspeksi (MIGAS)",
                    f"INSP-{c}",
                    today + timedelta(days=60 if c == "AST-PMP-01" else 300),
                ),
                _cert("Kalibrasi PSV", f"CAL-{c}", today + timedelta(days=180)),
            ],
            **demo,
        )
        for c, n, cls, crit, rate, sn in d.ASSETS
    )
    s.add("items", len(d.ITEMS))
    s.add("warehouses", len(d.WAREHOUSES))
    s.add("assets", len(d.ASSETS))

    for m in range(1, 13):
        status = "closed" if m < d.OPEN_MONTH else "open" if m == d.OPEN_MONTH else "future"
        session.add(FiscalPeriod(year=d.PERIOD_YEAR, month=m, status=status, **demo))
    s.add("fiscal_periods", 12)

    session.add_all(
        PriceItem(
            code=c,
            name=n,
            unit=u,
            unit_cost=Decimal(cost),
            unit_price=Decimal(price),
            cost_element_code=ce,
            **demo,
        )
        for c, n, u, cost, price, ce in d.PRICE_ITEMS
    )
    session.add_all(
        FxRate(currency=c, rate_date=dt, rate=Decimal(r), source=src, **demo)
        for c, dt, r, src in d.FX
    )
    s.add("price_items", len(d.PRICE_ITEMS))
    s.add("fx_rates", len(d.FX))
    await session.flush()
    await _load_crm(session, s, today, demo)

    await audit.record(
        session,
        action="demo_loaded",
        entity_type="system",
        entity_id="demo",
        actor_id=actor_id,
        after=s.counts,
    )
    return s


async def _load_crm(session: AsyncSession, s: Summary, today: date, demo: dict[str, Any]) -> None:
    owners = dict(
        (await session.execute(select(User.email, User.id).where(User.is_demo.is_(True))))
        .tuples()
        .all()
    )
    clients = dict((await session.execute(select(Client.code, Client.name))).tuples().all())
    leads = opps = 0
    for i, (
        code,
        company,
        contact,
        source,
        need,
        value,
        status,
        met,
        role,
        stage,
        prob,
    ) in enumerate(d.LEADS):
        owner = owners[f"{role.replace('_', '.')}@{d.EMAIL_DOMAIN}"]
        lead = Lead(
            number=await numbering.next(session, "LD"),
            client_code=code,
            company_name=company or clients[code or ""],
            contact_name=contact,
            source=source,
            need=need,
            estimated_value=Decimal(value) if value is not None else None,
            status=status,
            disqualify_reason="Nilai di bawah minimum layanan"
            if status == "disqualified"
            else None,
            qualification={k: n < met for n, k in enumerate(QUALIFICATION)},
            owner_id=owner,
            **demo,
        )
        session.add(lead)
        leads += 1
        if stage is None:
            continue
        await session.flush()
        session.add(
            Opportunity(
                number=await numbering.next(session, "OPP"),
                lead_id=lead.id,
                client_code=code,
                company_name=lead.company_name,
                title=need,
                owner_id=owner,
                value=Decimal(value or 0),
                probability=prob,
                expected_close=today + timedelta(days=30 * (i + 1)),
                is_tender=source in ("eproc", "invitation"),
                stage=stage,
                bid_status="none"
                if stage == "qualified"
                else "no_bid"
                if stage == "lost"
                else "bid",
                lost_reason="Harga kompetitor lebih rendah" if stage == "lost" else None,
                won_at=today - timedelta(days=20) if stage == "won" else None,
                lost_at=today - timedelta(days=10) if stage == "lost" else None,
                **demo,
            )
        )
        opps += 1
    await session.flush()
    s.add("crm_leads", leads)
    s.add("crm_opportunities", opps)


async def remove(session: AsyncSession, *, actor_id: uuid.UUID | None) -> Summary:
    """Delete every is_demo row. Refuses (nothing deleted) if real data depends on demo data."""
    s = Summary()
    demo_users = select(User.id).where(User.is_demo.is_(True))
    try:
        async with session.begin_nested():
            # Sales records first: bid decisions reference approval requests.
            crm_tables: tuple[Any, ...] = (
                Quotation,
                OutgoingLetter,
                BidDecision,
                Opportunity,
                Lead,
            )
            for crm_model in crm_tables:
                res = await session.execute(delete(crm_model).where(crm_model.is_demo.is_(True)))
                s.add(crm_model.__tablename__, res.rowcount or 0)  # type: ignore[attr-defined]
            # Approval history of demo users (their requests and any steps they acted on).
            reqs = select(ApprovalRequest.id).where(ApprovalRequest.requester_id.in_(demo_users))
            await session.execute(delete(ApprovalStep).where(ApprovalStep.request_id.in_(reqs)))
            res = await session.execute(delete(ApprovalRequest).where(ApprovalRequest.id.in_(reqs)))
            s.add("approval_requests", res.rowcount or 0)  # type: ignore[attr-defined]
            await session.execute(
                update(ApprovalStep)
                .where(ApprovalStep.on_behalf_of.in_(demo_users))
                .values(on_behalf_of=None)
            )
            for model in (Notification, RefreshToken, UserRole):
                await session.execute(delete(model).where(model.user_id.in_(demo_users)))
            await session.execute(
                delete(Delegation).where(
                    Delegation.delegator_id.in_(demo_users) | Delegation.delegate_id.in_(demo_users)
                )
            )
            for model in DEMO_TABLES:
                res = await session.execute(delete(model).where(model.is_demo.is_(True)))
                s.add(model.__tablename__, res.rowcount or 0)  # type: ignore[attr-defined]
            res = await session.execute(delete(User).where(User.is_demo.is_(True)))
            s.add("users", res.rowcount or 0)  # type: ignore[attr-defined]
            res = await session.execute(delete(Department).where(Department.is_demo.is_(True)))
            s.add("departments", res.rowcount or 0)  # type: ignore[attr-defined]
    except IntegrityError as exc:
        raise ConflictError(
            "DEMO_IN_USE",
            "Data demo masih dipakai data asli (mis. pengguna asli di departemen demo, atau "
            "persetujuan yang diputus pengguna demo). Pindahkan dulu data tersebut, "
            "lalu coba lagi.",
        ) from exc
    await audit.record(
        session,
        action="demo_removed",
        entity_type="system",
        entity_id="demo",
        actor_id=actor_id,
        before=s.counts,
    )
    return s


async def _main(remove_demo: bool) -> None:
    async with SessionLocal() as session:
        if remove_demo:
            summary = await remove(session, actor_id=None)
        else:
            password = os.environ.get("DEMO_PASSWORD", d.DEMO_PASSWORD_DEFAULT)
            summary = await load(session, password=password)
        await session.commit()
    verb = "Dihapus" if remove_demo else "Dimuat"
    for name, n in summary.counts.items():
        print(f"{verb} {n:>3}  {name}")
    if not remove_demo:
        print(
            f"\nPengguna demo: <kode.peran>@{d.EMAIL_DOMAIN}, kata sandi dari DEMO_PASSWORD "
            f"(bawaan: {d.DEMO_PASSWORD_DEFAULT})."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m app.demo.seed")
    parser.add_argument("--remove", action="store_true", help="hapus semua data demo")
    asyncio.run(_main(parser.parse_args().remove))
