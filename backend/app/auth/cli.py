"""Admin CLI until the first-run wizard (phase 01a) exists.

python -m app.auth.cli create-user --email a@b.co --name "Nama" --role super_admin
python -m app.auth.cli reset-2fa --email a@b.co
python -m app.auth.cli unlock --email a@b.co
"""

import argparse
import asyncio
import sys

from app import models as _models  # noqa: F401  (register every model)
from app.auth import service
from app.core.db import SessionLocal
from app.services import audit


async def _create(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        user, temp = await service.create_user(
            session, email=args.email, full_name=args.name, role_codes=args.role, actor_id=None
        )
        await session.commit()
    print(f"Pengguna dibuat: {user.email}")
    print(f"Kata sandi sementara (tampil sekali, wajib diganti saat masuk): {temp}")


async def _reset_2fa(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        user = await service.find_user_by_email(session, args.email)
        if user is None:
            sys.exit(f"Email {args.email} tidak ditemukan.")
        user.totp_enabled = False
        user.totp_secret_enc = None
        user.totp_last_step = None
        await service.revoke_all_for_user(session, user.id)
        await audit.record(
            session,
            action="totp_reset",
            entity_type="user",
            entity_id=user.id,
            actor_id=None,
            note="CLI break-glass reset",
        )
        await session.commit()
    print(f"2FA direset untuk {args.email}. Pengguna wajib mengaktifkan 2FA lagi saat masuk.")


async def _unlock(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        user = await service.find_user_by_email(session, args.email)
        if user is None:
            sys.exit(f"Email {args.email} tidak ditemukan.")
        user.failed_login_count = 0
        user.locked_until = None
        await audit.record(
            session,
            action="unlock",
            entity_type="user",
            entity_id=user.id,
            actor_id=None,
            note="CLI",
        )
        await session.commit()
    print(f"Akun {args.email} dibuka.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--role", action="append", required=True, help="role code; repeatable")
    for name in ("reset-2fa", "unlock"):
        sub.add_parser(name).add_argument("--email", required=True)
    args = parser.parse_args()
    handler = {"create-user": _create, "reset-2fa": _reset_2fa, "unlock": _unlock}[args.cmd]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
