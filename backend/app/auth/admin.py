"""User administration (Settings > Pengguna & Peran). Users are never deleted."""

import csv
import io
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from openpyxl import load_workbook
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.models import RefreshToken, Role, User, UserInvite, UserRole
from app.auth.principal import Principal
from app.auth.security import (
    generate_temp_password,
    hash_password,
    hash_refresh_token,
    validate_password_policy,
)
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.master.models import Department, Employee
from app.notifications import service as notifications
from app.services import audit
from app.services.audit import AuditAction
from app.setup import service as setup_service

INVITE_HOURS = 72
Status = Literal["invited", "active", "locked", "inactive"]


def _now() -> datetime:
    return datetime.now(UTC)


def status_of(user: User, has_open_invite: bool) -> Status:
    if not user.is_active:
        return "inactive"
    if user.locked_until and user.locked_until > _now():
        return "locked"
    if user.last_login_at is None and has_open_invite:
        return "invited"
    return "active"


async def role_codes(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return sorted(rows.scalars())


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("USER_NOT_FOUND", "Pengguna tidak ditemukan.")
    return user


async def _guard_super_admin_target(session: AsyncSession, actor: Principal, user: User) -> None:
    """Only a Super Admin may change another Super Admin's account."""
    if (
        "super_admin" in await role_codes(session, user.id)
        and "super_admin" not in actor.role_codes
    ):
        raise ForbiddenError(
            "SUPER_ADMIN_TARGET", "Hanya Super Admin yang dapat mengubah akun Super Admin."
        )


# --- invites ----------------------------------------------------------------------------------


async def create_invite(session: AsyncSession, actor_id: uuid.UUID | None, user: User) -> str:
    await session.execute(
        update(UserInvite)
        .where(
            UserInvite.user_id == user.id,
            UserInvite.used_at.is_(None),
            UserInvite.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    raw = secrets.token_urlsafe(32)
    session.add(
        UserInvite(
            user_id=user.id,
            token_hash=hash_refresh_token(raw),
            expires_at=_now() + timedelta(hours=INVITE_HOURS),
            created_by=actor_id,
        )
    )
    await session.flush()
    link = f"/undangan/{raw}"
    await notifications.notify(
        session,
        [user.id],
        kind="invite",
        title="Undangan Nustrad ERP",
        body=(
            f"Halo {user.full_name}, Anda diundang ke Nustrad ERP PT Global Energi KITA. "
            f"Tautan berlaku {INVITE_HOURS} jam dan hanya sekali pakai."
        ),
        link=link,
    )
    await audit.record(
        session,
        action="invite",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor_id,
        after={"email": user.email, "expires_hours": INVITE_HOURS},
    )
    return raw


async def open_invite_users(session: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not user_ids:
        return set()
    rows = await session.execute(
        select(UserInvite.user_id).where(
            UserInvite.user_id.in_(user_ids),
            UserInvite.used_at.is_(None),
            UserInvite.revoked_at.is_(None),
            UserInvite.expires_at > _now(),
        )
    )
    return set(rows.scalars())


async def accept_invite(session: AsyncSession, raw: str, password: str) -> User:
    invite = (
        await session.execute(
            select(UserInvite)
            .where(UserInvite.token_hash == hash_refresh_token(raw))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if invite is None or invite.used_at or invite.revoked_at:
        raise AppError(
            "INVITE_INVALID", "Tautan undangan tidak valid atau sudah dipakai.", status_code=410
        )
    if invite.expires_at <= _now():
        raise AppError(
            "INVITE_EXPIRED",
            "Tautan undangan sudah kedaluwarsa. Minta admin mengirim ulang.",
            status_code=410,
        )
    user = await get_user(session, invite.user_id)
    if not user.is_active:
        raise AppError("ACCOUNT_INACTIVE", "Akun tidak aktif. Hubungi admin.", status_code=403)
    validate_password_policy(
        password, email=user.email, strong="super_admin" in await role_codes(session, user.id)
    )
    user.password_hash = hash_password(password)
    user.must_change_password = False
    user.password_changed_at = _now()
    invite.used_at = _now()
    await audit.record(
        session, action="invite_accepted", entity_type="user", entity_id=user.id, actor_id=user.id
    )
    return user


# --- create / update --------------------------------------------------------------------------


async def _check_roles(session: AsyncSession, actor: Principal, codes: list[str]) -> None:
    if "super_admin" in codes and "super_admin" not in actor.role_codes:
        raise ForbiddenError(
            "SUPER_ADMIN_ONLY", "Hanya Super Admin yang dapat memberi peran Super Admin."
        )
    known = set(
        (
            await session.execute(
                select(Role.code).where(Role.code.in_(codes), Role.is_active.is_(True))
            )
        ).scalars()
    )
    if set(codes) - known:
        raise AppError(
            "UNKNOWN_ROLE",
            f"Peran tidak dikenal: {', '.join(sorted(set(codes) - known))}.",
            status_code=422,
        )


async def _check_employee(
    session: AsyncSession, code: str | None, user_id: uuid.UUID | None
) -> None:
    if not code:
        return
    if (await session.execute(select(Employee.id).where(Employee.code == code))).first() is None:
        raise AppError("EMPLOYEE_NOT_FOUND", f"Karyawan {code} tidak ditemukan.", status_code=422)
    taken = (
        await session.execute(select(User.id).where(User.employee_code == code))
    ).scalar_one_or_none()
    if taken and taken != user_id:
        raise ConflictError("EMPLOYEE_LINKED", f"Karyawan {code} sudah terhubung ke pengguna lain.")


async def create(
    session: AsyncSession,
    actor: Principal,
    *,
    email: str,
    full_name: str,
    role_codes_: list[str],
    department_code: str | None,
    employee_code: str | None,
    mode: Literal["invite", "password"],
) -> tuple[User, str | None]:
    await _check_roles(session, actor, role_codes_)
    await _check_employee(session, employee_code, None)
    dept_id = None
    if department_code:
        dept_id = (
            await session.execute(select(Department.id).where(Department.code == department_code))
        ).scalar_one_or_none()
        if dept_id is None:
            raise AppError(
                "DEPARTMENT_NOT_FOUND",
                f"Departemen {department_code} tidak ditemukan.",
                status_code=422,
            )
    temp = generate_temp_password() if mode == "password" else None
    user, _ = await auth_service.create_user(
        session,
        email=email,
        full_name=full_name,
        role_codes=role_codes_,
        actor_id=actor.id,
        password=temp or secrets.token_urlsafe(24),
        department_id=dept_id,
    )
    user.employee_code = employee_code
    if mode == "invite":
        await create_invite(session, actor.id, user)
    return user, temp


async def set_roles(
    session: AsyncSession, actor: Principal, user: User, codes: list[str], hook: Any = None
) -> None:
    await _guard_super_admin_target(session, actor, user)
    await _check_roles(session, actor, codes)
    before = await role_codes(session, user.id)
    if "super_admin" in before and "super_admin" not in codes:
        await setup_service.ensure_super_admin_remains(session, losing_user_id=user.id)
    if hook is not None:  # SoD conflict check (phase 01a.5)
        await hook(session, actor, user, before, codes)
    roles = (await session.execute(select(Role).where(Role.code.in_(codes)))).scalars().all()
    await session.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for r in roles:
        session.add(UserRole(user_id=user.id, role_id=r.id, assigned_by=actor.id))
    await session.flush()
    if sorted(codes) != before:
        await audit.record(
            session,
            action=AuditAction.UPDATE,
            entity_type="user",
            entity_id=user.id,
            actor_id=actor.id,
            before={"roles": before},
            after={"roles": sorted(codes)},
        )


async def update_profile(
    session: AsyncSession,
    actor: Principal,
    user: User,
    *,
    full_name: str | None,
    department_code: str | None,
    employee_code: str | None,
    fields_set: set[str],
) -> None:
    await _guard_super_admin_target(session, actor, user)
    before = {
        "full_name": user.full_name,
        "department_id": str(user.department_id) if user.department_id else None,
        "employee_code": user.employee_code,
    }
    if "full_name" in fields_set and full_name:
        user.full_name = full_name.strip()
    if "department_code" in fields_set:
        if department_code:
            dept = (
                await session.execute(
                    select(Department.id).where(Department.code == department_code)
                )
            ).scalar_one_or_none()
            if dept is None:
                raise AppError(
                    "DEPARTMENT_NOT_FOUND",
                    f"Departemen {department_code} tidak ditemukan.",
                    status_code=422,
                )
            user.department_id = dept
        else:
            user.department_id = None
    if "employee_code" in fields_set:
        await _check_employee(session, employee_code, user.id)
        user.employee_code = employee_code or None
    await session.flush()
    after = {
        "full_name": user.full_name,
        "department_id": str(user.department_id) if user.department_id else None,
        "employee_code": user.employee_code,
    }
    if after != before:
        await audit.record(
            session,
            action=AuditAction.UPDATE,
            entity_type="user",
            entity_id=user.id,
            actor_id=actor.id,
            before=before,
            after=after,
        )


# --- account actions --------------------------------------------------------------------------


async def set_active(session: AsyncSession, actor: Principal, user: User, active: bool) -> None:
    await _guard_super_admin_target(session, actor, user)
    if user.id == actor.id and not active:
        raise AppError(
            "SELF_DEACTIVATE", "Anda tidak dapat menonaktifkan akun sendiri.", status_code=409
        )
    if not active and "super_admin" in await role_codes(session, user.id):
        await setup_service.ensure_super_admin_remains(session, losing_user_id=user.id)
    if user.is_active == active:
        return
    user.is_active = active
    if not active:
        await auth_service.revoke_all_for_user(session, user.id)
    await audit.record(
        session,
        action="activate" if active else "deactivate",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor.id,
    )


async def reset_password(session: AsyncSession, actor: Principal, user: User) -> str:
    await _guard_super_admin_target(session, actor, user)
    temp = generate_temp_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    await auth_service.revoke_all_for_user(session, user.id)
    await audit.record(
        session, action="password_reset", entity_type="user", entity_id=user.id, actor_id=actor.id
    )
    return temp


async def unlock(session: AsyncSession, actor: Principal, user: User) -> None:
    user.failed_login_count, user.locked_until = 0, None
    await audit.record(
        session, action="unlock", entity_type="user", entity_id=user.id, actor_id=actor.id
    )


async def reset_2fa(session: AsyncSession, actor: Principal, user: User) -> None:
    # Break-glass for Super Admins stays with recovery codes or the audited CLI.
    if "super_admin" in await role_codes(session, user.id):
        raise ForbiddenError(
            "SUPER_ADMIN_2FA",
            "2FA Super Admin hanya dapat direset dengan kode pemulihan atau perintah CLI "
            "yang diaudit.",
        )
    user.totp_enabled, user.totp_secret_enc, user.totp_last_step = False, None, None
    await auth_service.revoke_all_for_user(session, user.id)
    await audit.record(
        session, action="totp_reset", entity_type="user", entity_id=user.id, actor_id=actor.id
    )


async def force_logout(session: AsyncSession, actor: Principal, user: User) -> None:
    await auth_service.revoke_all_for_user(session, user.id)
    await audit.record(
        session, action="force_logout", entity_type="user", entity_id=user.id, actor_id=actor.id
    )


async def sessions(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Active sign-ins: one row per refresh-token family (latest token)."""
    rows = (
        (
            await session.execute(
                select(RefreshToken)
                .where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > _now(),
                )
                .order_by(RefreshToken.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    first_seen = dict(
        (
            await session.execute(
                select(RefreshToken.family_id, func.min(RefreshToken.created_at))
                .where(RefreshToken.user_id == user_id)
                .group_by(RefreshToken.family_id)
            )
        )
        .tuples()
        .all()
    )
    return [
        {
            "family_id": str(r.family_id),
            "signed_in_at": first_seen.get(r.family_id, r.created_at),
            "last_active_at": r.created_at,
            "user_agent": r.user_agent,
            "ip": r.ip,
        }
        for r in rows
    ]


async def revoke_session(
    session: AsyncSession, actor: Principal, user: User, family_id: uuid.UUID
) -> None:
    await auth_service.revoke_family(session, family_id)
    await audit.record(
        session,
        action="revoke_session",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor.id,
        after={"family_id": str(family_id)},
    )


# --- import -----------------------------------------------------------------------------------


@dataclass
class ImportReport:
    created: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


def _rows(filename: str, content: bytes) -> list[dict[str, str]]:
    if filename.lower().endswith(".xlsx"):
        ws = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
        assert ws is not None
        values = [
            [("" if v is None else str(v)).strip() for v in row]
            for row in ws.iter_rows(values_only=True)
        ]
        if not values:
            return []
        header = [h.lower() for h in values[0]]
        return [dict(zip(header, r, strict=False)) for r in values[1:] if any(r)]
    text = content.decode("utf-8-sig")
    first = text.splitlines()[0] if text else ""
    delim = ";" if first.count(";") >= first.count(",") else ","
    return [
        {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        for r in csv.DictReader(io.StringIO(text), delimiter=delim)
    ]


async def import_users(
    session: AsyncSession, actor: Principal, filename: str, content: bytes
) -> ImportReport:
    """Columns: email, full_name, roles (codes separated by |), department_code, employee_code.
    All rows valid or nothing is saved; every new user gets an invitation email."""
    report = ImportReport()
    rows = _rows(filename, content)
    if not rows:
        report.errors.append({"row": 1, "field": None, "message": "File kosong atau tanpa header."})
        return report
    missing = {"email", "full_name", "roles"} - set(rows[0])
    if missing:
        report.errors.append(
            {
                "row": 1,
                "field": None,
                "message": f"Kolom wajib tidak ada: {', '.join(sorted(missing))}.",
            }
        )
        return report
    seen: set[str] = set()
    for i, r in enumerate(rows, start=2):
        email = r.get("email", "").lower()
        codes = [c.strip() for c in r.get("roles", "").replace(",", "|").split("|") if c.strip()]
        if not email or "@" not in email:
            report.errors.append({"row": i, "field": "email", "message": "email tidak valid"})
            continue
        if email in seen:
            report.errors.append({"row": i, "field": "email", "message": "email ganda di file"})
            continue
        seen.add(email)
        if not r.get("full_name"):
            report.errors.append({"row": i, "field": "full_name", "message": "wajib diisi"})
            continue
        if not codes:
            report.errors.append({"row": i, "field": "roles", "message": "minimal satu peran"})
            continue
        try:
            async with session.begin_nested():
                await create(
                    session,
                    actor,
                    email=email,
                    full_name=r["full_name"],
                    role_codes_=codes,
                    department_code=r.get("department_code") or None,
                    employee_code=r.get("employee_code") or None,
                    mode="invite",
                )
            report.created += 1
        except AppError as exc:
            report.errors.append({"row": i, "field": None, "message": exc.message})
    return report
