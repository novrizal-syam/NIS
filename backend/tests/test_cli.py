import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from tests.conftest import TEST_DB_URL

BACKEND = Path(__file__).resolve().parents[1]


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    # A fresh interpreter: catches models that only resolve when tests import everything.
    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "app.auth.cli", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


async def test_cli_create_user_unlock_and_reset_2fa(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    res = _cli("create-user", "--email", "kasir@gek.co.id", "--name", "Sari", "--role", "cashier")
    assert res.returncode == 0, res.stderr
    assert "Kata sandi sementara" in res.stdout
    async with sessionmaker() as s:
        user = (await s.execute(select(User).where(User.email == "kasir@gek.co.id"))).scalar_one()
        assert user.must_change_password
        user.totp_enabled = True
        user.locked_until = user.created_at
        await s.commit()

    assert _cli("unlock", "--email", "kasir@gek.co.id").returncode == 0
    assert _cli("reset-2fa", "--email", "kasir@gek.co.id").returncode == 0
    async with sessionmaker() as s:
        user = (await s.execute(select(User).where(User.email == "kasir@gek.co.id"))).scalar_one()
        assert user.locked_until is None and not user.totp_enabled

    missing = _cli("unlock", "--email", "tidak.ada@gek.co.id")
    assert missing.returncode != 0


def test_app_imports_standalone() -> None:
    code = "import app.main, sqlalchemy.orm as o; o.configure_mappers(); print('ok')"
    res = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=False
    )
    assert res.stdout.strip() == "ok", res.stderr
