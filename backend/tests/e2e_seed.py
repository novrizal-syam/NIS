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
from app.setup import service as settings_store

PASSWORD = "E2e-Rahasia-2026"
USERS = {
    "account_executive": ("ae@e2e.gek.co.id", "Citra Sales"),
    "head_of_sales": ("hos@e2e.gek.co.id", "Bayu Head of Sales"),
    "director": ("director@e2e.gek.co.id", "Rahman Direktur"),
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
        await s.commit()
    print("e2e seed ok")


if __name__ == "__main__":
    asyncio.run(main())
