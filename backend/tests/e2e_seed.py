"""Seed a throw-away database for the Playwright end-to-end happy path (frontend/e2e/real).

    DATABASE_URL=... alembic upgrade head && DATABASE_URL=... python -m tests.e2e_seed

Never run against a real database: it marks setup as completed and creates users with a
known password whose 2FA is marked enrolled without a secret (login asks no code).
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as _models  # noqa: F401
from app.auth import service as auth_service
from app.auth.models import User
from app.auth.principal import PRIVACY_VERSION
from app.contract.models import Contract, ContractRate
from app.core.db import SessionLocal
from app.crm.models import Opportunity
from app.inventory import stock_service as stock
from app.master.models import Asset, Employee, Item, PriceItem, Warehouse
from app.project.models import (
    BudgetVersion,
    BudgetVersionLine,
    Project,
    ProjectBudgetLine,
    ProjectMember,
    ProjectWbs,
)
from app.services import ledger
from app.services.numbering import today_jakarta
from app.setup import service as settings_store

PASSWORD = "E2e-Rahasia-2026"
USERS = {
    "account_executive": ("ae@e2e.gek.co.id", "Citra Sales"),
    "head_of_sales": ("hos@e2e.gek.co.id", "Bayu Head of Sales"),
    "director": ("director@e2e.gek.co.id", "Rahman Direktur"),
    "lead_engineer": ("planner@e2e.gek.co.id", "Dewi Planner"),
    "lead_controller": ("controller@e2e.gek.co.id", "Hadi Controller"),
    "head_of_operation": ("hoo@e2e.gek.co.id", "Agus Head of Operation"),
    "admin": ("admin@e2e.gek.co.id", "Admin IT"),
    "engineer": ("engineer@e2e.gek.co.id", "Budi Engineer"),
    "head_of_finance": ("hof@e2e.gek.co.id", "Sinta Head of Finance"),
    "field_engineer": ("fe@e2e.gek.co.id", "Eko Field Engineer"),
    "warehouse_head": ("wh@e2e.gek.co.id", "Hadi Kepala Gudang"),
    "ofs_superintendent": ("sup@e2e.gek.co.id", "Rudi Superintendent"),
}


async def main() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if "e2e" not in url:
        raise SystemExit("Refusing to seed: DATABASE_URL must point to an *e2e* database.")
    async with SessionLocal() as s:
        await settings_store.put(s, settings_store.SETUP_COMPLETED, True, None)
        for role, (email, name) in USERS.items():
            user, _ = await auth_service.create_user(
                s, email=email, full_name=name, role_codes=[role], actor_id=None, password=PASSWORD
            )
            user.must_change_password = False
            user.totp_enabled = True
            user.privacy_version = PRIVACY_VERSION
            user.privacy_accepted_at = user.created_at
            user.profile_completed_at = user.created_at
            user.phone = "0812000000"
            user.tour_done_at = user.created_at
        # Cost 6.6 M, price 10 M -> 34 % margin (Head of Sales approves).
        s.add(
            PriceItem(
                code="SRV-E2E",
                name="Well testing package (E2E)",
                unit="hari",
                unit_cost=Decimal(6_600_000),
                unit_price=Decimal(10_000_000),
                cost_element_code="EQUIP-OWN",
            )
        )
        await s.flush()
        # Budget flow (03a-03c): draft project at 18 % margin, planner assigned.
        planner = await auth_service.find_user_by_email(s, USERS["lead_engineer"][0])
        assert planner is not None
        project = Project(
            number="PRJ-26-900",
            name="Budget E2E Blok Rokan",
            company_name="PT KKKS E2E",
            status="draft",
            revenue=Decimal(1_000_000_000),
            budget_total=Decimal(820_000_000),
            contingency_pct=Decimal(5),
            manager_id=planner.id,
        )
        s.add(project)
        await s.flush()
        wbs = ProjectWbs(project_id=project.id, code="EXEC", name="Execution", seq=1)
        s.add(wbs)
        await s.flush()
        for code, amount in (("EQUIP-OWN", 780_000_000), ("CONTINGENCY", 40_000_000)):
            s.add(
                ProjectBudgetLine(
                    project_id=project.id,
                    version=0,
                    wbs_id=wbs.id,
                    cost_element_code=code,
                    amount=Decimal(amount),
                    source="quotation",
                    locked_reserve=code == "CONTINGENCY",
                )
            )
        # PR flow (04a): locked project with Rp 55 jt on EXEC/EQUIP-RENT and a baseline v0.
        locked = Project(
            number="PRJ-26-901",
            name="PR E2E Blok Jambi",
            company_name="PT KKKS E2E",
            status="locked",
            revenue=Decimal(1_000_000_000),
            budget_total=Decimal(105_000_000),
            contingency_pct=Decimal(5),
            manager_id=planner.id,
            locked_at=datetime.now(UTC),
        )
        s.add(locked)
        await s.flush()
        exec_wbs = ProjectWbs(project_id=locked.id, code="EXEC", name="Execution", seq=1)
        s.add(exec_wbs)
        await s.flush()
        version = BudgetVersion(
            project_id=locked.id,
            version=0,
            kind="baseline",
            revenue=locked.revenue,
            total_cost=locked.budget_total,
            margin_pct=Decimal("89.50"),
            approved_at=datetime.now(UTC),
        )
        s.add(version)
        await s.flush()
        for code, amount in (("EQUIP-RENT", 55_000_000), ("CONTINGENCY", 50_000_000)):
            s.add(
                ProjectBudgetLine(
                    project_id=locked.id,
                    version=0,
                    wbs_id=exec_wbs.id,
                    cost_element_code=code,
                    amount=Decimal(amount),
                    source="quotation",
                    locked_reserve=code == "CONTINGENCY",
                )
            )
            s.add(
                BudgetVersionLine(
                    version_id=version.id,
                    wbs_code="EXEC",
                    wbs_name="Execution",
                    cost_element_code=code,
                    amount=Decimal(amount),
                    locked_reserve=code == "CONTINGENCY",
                )
            )
        await s.flush()
        await _inventory(s, planner.id)
        await s.commit()
    print("e2e seed ok")


async def _inventory(s: AsyncSession, manager_id: uuid.UUID) -> None:
    """MR flow (04c): PRJ-26-902 with Rp 100 jt consumables; 2 drums at the site and 3 at
    Base (opening stock posted to 1310); the field engineer is on the project team."""
    fe = (
        await s.execute(select(User).where(User.email == USERS["field_engineer"][0]))
    ).scalar_one()
    p = Project(
        number="PRJ-26-902",
        name="MR E2E Blok Rokan",
        company_name="PT KKKS E2E",
        status="locked",
        revenue=Decimal(1_000_000_000),
        budget_total=Decimal(100_000_000),
        contingency_pct=Decimal(5),
        manager_id=manager_id,
        locked_at=datetime.now(UTC),
    )
    s.add(p)
    await s.flush()
    w = ProjectWbs(project_id=p.id, code="EXEC", name="Execution", seq=1)
    s.add(w)
    await s.flush()
    for ce in ("CONSUMABLE", "EQUIP-OWN", "MANPOWER"):
        s.add(
            ProjectBudgetLine(
                project_id=p.id,
                version=0,
                wbs_id=w.id,
                cost_element_code=ce,
                amount=Decimal(100_000_000),
                source="quotation",
            )
        )
    sup = (
        await s.execute(select(User).where(User.email == USERS["ofs_superintendent"][0]))
    ).scalar_one()
    s.add(ProjectMember(project_id=p.id, user_id=fe.id))
    s.add(ProjectMember(project_id=p.id, user_id=sup.id))
    # DOR flow (05a): contract rate schedule, a pump unit and a field crew member.
    opp = Opportunity(
        number="OPP-26-902",
        company_name="PT KKKS E2E",
        title="Well test Rokan",
        owner_id=manager_id,
    )
    s.add(opp)
    await s.flush()
    contract = Contract(
        number="CTR-26-902",
        opportunity_id=opp.id,
        company_name="PT KKKS E2E",
        title="Well test Rokan",
        owner_id=manager_id,
        value=Decimal(500_000_000),
    )
    s.add(contract)
    await s.flush()
    s.add_all(
        [
            ContractRate(
                contract_id=contract.id,
                seq=1,
                kind="equipment",
                description="Pump unit 600 HP",
                unit="hari",
                rate=Decimal(14_000_000),
                standby_rate=Decimal(7_000_000),
                breakdown_rate=Decimal(0),
            ),
            ContractRate(
                contract_id=contract.id,
                seq=2,
                kind="personnel",
                description="Field engineer",
                unit="hari",
                rate=Decimal(3_000_000),
            ),
            Asset(
                code="AST-E2E",
                name="Pump unit E2E",
                asset_class="Pumping unit",
                criticality="A",
                internal_day_rate=Decimal(9_500_000),
            ),
            Employee(code="E-E2E", full_name="Andi Operator", position="Operator", is_field=True),
        ]
    )
    p.contract_id, p.service_type = contract.id, "well_test"
    s.add_all(
        [
            Item(
                code="ITM-E2E",
                name="Demulsifier E2E",
                uom="drum",
                category="chemicals",
                reorder_point=Decimal(6),
                last_price=Decimal(6_400_000),
            ),
            Warehouse(code="WH-CLG", name="Base Cilegon", kind="base"),
            Warehouse(code="WH-902", name="Site Rokan E2E", kind="site", project_code="PRJ-26-902"),
        ]
    )
    await s.flush()
    doc = stock.Doc("opening", "e2e", "Saldo awal", None)
    await stock.receive(s, "ITM-E2E", "WH-CLG", Decimal(3), Decimal(18_000_000), doc)
    await stock.receive(s, "ITM-E2E", "WH-902", Decimal(2), Decimal(12_000_000), doc)
    await ledger.post_journal(
        s,
        entry_date=today_jakarta(),
        description="Saldo awal persediaan (e2e)",
        lines=[
            ledger.JLine("1310", debit=Decimal(30_000_000)),
            ledger.JLine("3200", credit=Decimal(30_000_000)),
        ],
        source_type="opening",
        source_id="e2e",
        by=None,
    )


if __name__ == "__main__":
    asyncio.run(main())
