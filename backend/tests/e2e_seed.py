"""Seed a throw-away database for the Playwright end-to-end happy path (frontend/e2e/real).

    DATABASE_URL=... alembic upgrade head && DATABASE_URL=... python -m tests.e2e_seed

Never run against a real database: it marks setup as completed and creates users with a
known password whose 2FA is marked enrolled without a secret (login asks no code).
"""

import asyncio
import os
from decimal import Decimal

from app import models as _models  # noqa: F401
from app.auth import service as auth_service
from app.auth.principal import PRIVACY_VERSION
from app.core.db import SessionLocal
from app.master.models import PriceItem
from app.project.models import Project, ProjectBudgetLine, ProjectWbs
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
        await s.commit()
    print("e2e seed ok")


if __name__ == "__main__":
    asyncio.run(main())
