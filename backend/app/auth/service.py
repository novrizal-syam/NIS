"""Login, refresh-token rotation, password change, TOTP enrolment. Each step is audited."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RecoveryCode, RefreshToken, Role, User, UserRole
from app.auth.principal import PENDING_TOTP, Principal, load_principal
from app.auth.security import (
    create_access_token,
    decrypt_secret,
    encrypt_secret,
    generate_temp_password,
    hash_password,
    hash_recovery_code,
    hash_refresh_token,
    needs_rehash,
    new_recovery_codes,
    new_refresh_token,
    new_totp_secret,
    totp_qr_svg,
    totp_uri,
    validate_password_policy,
    verify_password,
    verify_totp,
)
from app.core.config import get_settings
from app.core.errors import AppError, ConflictError
from app.services import audit
from app.services.audit import AuditAction

INVALID_LOGIN = "Email atau kata sandi salah."


@dataclass
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _auth_error(code: str, message: str, status: int = 401) -> AppError:
    return AppError(code, message, status_code=status)


async def find_user_by_email(
    session: AsyncSession, email: str, *, for_update: bool = False
) -> User | None:
    stmt = select(User).where(func.lower(User.email) == email.strip().lower())
    if for_update:
        # Serialises concurrent logins of one account so the failure counter is exact.
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def _issue(
    session: AsyncSession,
    user: User,
    *,
    family_id: uuid.UUID | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> IssuedTokens:
    access, expires_in = create_access_token(user.id)
    raw, digest = new_refresh_token()
    expires_at = _now() + timedelta(days=get_settings().refresh_token_days)
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=digest,
            expires_at=expires_at,
            user_agent=(user_agent or "")[:300] or None,
            ip=ip,
        )
    )
    await session.flush()
    return IssuedTokens(access, expires_in, raw, expires_at)


async def _register_failure(session: AsyncSession, user: User, reason: str) -> AppError:
    s = get_settings()
    user.failed_login_count += 1
    locked = user.failed_login_count >= s.login_max_failures
    if locked:
        user.locked_until = _now() + timedelta(minutes=s.login_lock_minutes)
    await audit.record(
        session,
        action="login_failed",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        after={"reason": reason, "failed_login_count": user.failed_login_count, "locked": locked},
    )
    # Commit the counter even though the request fails.
    await session.commit()
    if locked:
        return _auth_error(
            "ACCOUNT_LOCKED",
            f"Akun dikunci {s.login_lock_minutes} menit karena {s.login_max_failures} kali gagal "
            "masuk. Coba lagi nanti atau hubungi admin.",
            423,
        )
    if reason == "totp":
        return _auth_error(
            "TOTP_INVALID", "Kode 2FA salah atau sudah dipakai. Masukkan kode terbaru."
        )
    if reason == "recovery":
        return _auth_error("RECOVERY_INVALID", "Kode pemulihan salah atau sudah pernah dipakai.")
    return _auth_error("INVALID_CREDENTIALS", INVALID_LOGIN)


async def login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    totp_code: str | None,
    recovery_code: str | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, IssuedTokens]:
    user = await find_user_by_email(session, email, for_update=True)
    if user is None:
        verify_password(password, None)  # equal timing for unknown emails
        raise _auth_error("INVALID_CREDENTIALS", INVALID_LOGIN)
    if user.locked_until and user.locked_until > _now():
        raise _auth_error(
            "ACCOUNT_LOCKED",
            "Akun sedang dikunci karena terlalu banyak percobaan gagal. Coba lagi nanti atau "
            "hubungi admin.",
            423,
        )
    if not verify_password(password, user.password_hash):
        raise await _register_failure(session, user, "password")
    if not user.is_active:
        raise _auth_error("ACCOUNT_INACTIVE", "Akun tidak aktif. Hubungi admin.", 403)

    if user.totp_enabled and user.totp_secret_enc and recovery_code:
        if not await _use_recovery_code(session, user, recovery_code):
            raise await _register_failure(session, user, "recovery")
        await audit.record(
            session,
            action="totp_recovery_used",
            entity_type="user",
            entity_id=user.id,
            actor_id=user.id,
            note="2FA direset dengan kode pemulihan",
        )
    elif user.totp_enabled and user.totp_secret_enc:
        if not totp_code:
            raise _auth_error(
                "TOTP_REQUIRED", "Masukkan kode 2FA dari aplikasi authenticator Anda."
            )
        step = verify_totp(
            decrypt_secret(user.totp_secret_enc), totp_code, last_step=user.totp_last_step
        )
        if step is None:
            raise await _register_failure(session, user, "totp")
        user.totp_last_step = step

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = _now()
    tokens = await _issue(session, user, user_agent=user_agent, ip=ip)
    await audit.record(
        session,
        action=AuditAction.LOGIN,
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        after={"ip": ip},
    )
    await session.commit()
    return user, tokens


async def refresh(
    session: AsyncSession,
    raw_token: str | None,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, IssuedTokens]:
    expired = _auth_error("REFRESH_INVALID", "Sesi berakhir. Silakan masuk lagi.")
    if not raw_token:
        raise expired
    token = (
        await session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if token is None:
        raise expired
    if token.revoked_at is not None:
        # A rotated token was presented again: assume theft, end every session of this login.
        await revoke_family(session, token.family_id)
        await audit.record(
            session,
            action="refresh_reuse",
            entity_type="user",
            entity_id=token.user_id,
            actor_id=token.user_id,
            after={"family_id": str(token.family_id)},
        )
        await session.commit()
        raise expired
    user = await session.get(User, token.user_id)
    if token.expires_at <= _now() or user is None or not user.is_active:
        raise expired
    if user.locked_until and user.locked_until > _now():
        raise expired
    token.revoked_at = _now()
    tokens = await _issue(session, user, family_id=token.family_id, user_agent=user_agent, ip=ip)
    await session.commit()
    return user, tokens


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def logout(session: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    token = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        )
    ).scalar_one_or_none()
    if token is None:
        return
    await revoke_family(session, token.family_id)
    await audit.record(
        session,
        action="logout",
        entity_type="user",
        entity_id=token.user_id,
        actor_id=token.user_id,
    )
    await session.commit()


async def change_password(
    session: AsyncSession,
    principal: Principal,
    *,
    current: str,
    new: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> IssuedTokens:
    user = principal.user
    if not verify_password(current, user.password_hash):
        raise AppError("INVALID_CURRENT_PASSWORD", "Kata sandi saat ini salah.", status_code=422)
    if current == new:
        raise AppError(
            "PASSWORD_REUSED",
            "Kata sandi baru harus berbeda dari kata sandi saat ini.",
            status_code=422,
        )
    validate_password_policy(new, email=user.email)
    user.password_hash = hash_password(new)
    user.must_change_password = False
    user.password_changed_at = _now()
    # Other sessions must sign in again with the new password.
    await revoke_all_for_user(session, user.id)
    tokens = await _issue(session, user, user_agent=user_agent, ip=ip)
    await audit.record(
        session, action="password_change", entity_type="user", entity_id=user.id, actor_id=user.id
    )
    await session.commit()
    return tokens


async def start_totp_setup(session: AsyncSession, principal: Principal) -> dict[str, str]:
    user = principal.user
    if user.totp_enabled:
        raise ConflictError("TOTP_ALREADY_ENABLED", "2FA sudah aktif untuk akun ini.")
    secret = new_totp_secret()
    user.totp_secret_enc = encrypt_secret(secret)
    await session.commit()
    uri = totp_uri(secret, user.email)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": totp_qr_svg(uri)}


async def issue_recovery_codes(session: AsyncSession, user: User) -> list[str]:
    """Replace the user's recovery codes; the plain codes are returned once."""
    await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = new_recovery_codes()
    session.add_all(RecoveryCode(user_id=user.id, code_hash=hash_recovery_code(c)) for c in codes)
    await session.flush()
    return codes


async def _use_recovery_code(session: AsyncSession, user: User, code: str) -> bool:
    row = (
        await session.execute(
            select(RecoveryCode)
            .where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_hash == hash_recovery_code(code),
                RecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    row.used_at = _now()
    # Break-glass: the lost authenticator is unlinked; the user must enrol again.
    user.totp_enabled, user.totp_secret_enc, user.totp_last_step = False, None, None
    return True


async def confirm_totp_setup(session: AsyncSession, principal: Principal, code: str) -> list[str]:
    user = principal.user
    if user.totp_enabled:
        raise ConflictError("TOTP_ALREADY_ENABLED", "2FA sudah aktif untuk akun ini.")
    if not user.totp_secret_enc:
        raise AppError("TOTP_NOT_STARTED", "Mulai pengaturan 2FA terlebih dahulu.", status_code=409)
    step = verify_totp(decrypt_secret(user.totp_secret_enc), code, last_step=None)
    if step is None:
        raise AppError(
            "TOTP_INVALID", "Kode 2FA salah. Periksa jam di ponsel lalu coba lagi.", status_code=422
        )
    user.totp_enabled = True
    user.totp_last_step = step
    codes = await issue_recovery_codes(session, user)
    await audit.record(
        session, action="totp_enabled", entity_type="user", entity_id=user.id, actor_id=user.id
    )
    await session.commit()
    return codes


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    role_codes: list[str],
    actor_id: uuid.UUID | None,
    password: str | None = None,
    department_id: uuid.UUID | None = None,
    is_demo: bool = False,
) -> tuple[User, str]:
    """Create a user with a temporary password (returned once; must be changed at first login)."""
    if await find_user_by_email(session, email):
        raise ConflictError("EMAIL_TAKEN", f"Email {email} sudah terdaftar.")
    roles = (await session.execute(select(Role).where(Role.code.in_(role_codes)))).scalars().all()
    missing = set(role_codes) - {r.code for r in roles}
    if missing:
        raise AppError("UNKNOWN_ROLE", f"Peran tidak dikenal: {', '.join(sorted(missing))}.")
    temp = password or generate_temp_password()
    user = User(
        email=email.strip(),
        full_name=full_name.strip(),
        password_hash=hash_password(temp),
        must_change_password=True,
        department_id=department_id,
        created_by=actor_id,
        is_demo=is_demo,
    )
    session.add(user)
    await session.flush()
    for r in roles:
        session.add(UserRole(user_id=user.id, role_id=r.id, assigned_by=actor_id))
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="user",
        entity_id=user.id,
        actor_id=actor_id,
        after={"email": user.email, "full_name": user.full_name, "roles": sorted(role_codes)},
    )
    return user, temp


async def me(session: AsyncSession, principal: Principal) -> dict[str, object]:
    u = principal.user
    # The role switcher lists every assigned role, even while one is active.
    all_roles = (
        principal.roles
        if principal.active_role is None
        else (await load_principal(session, u)).roles
    )
    return {
        "id": str(u.id),
        "email": u.email,
        "full_name": u.full_name,
        "department_id": str(u.department_id) if u.department_id else None,
        "roles": [{"code": r.code, "name": r.name} for r in all_roles],
        "active_role": principal.active_role,
        "permissions": principal.permissions_tree(),
        "pending": principal.pending,
        "totp_enabled": u.totp_enabled,
        "totp_required": PENDING_TOTP in principal.pending
        or any(r.requires_2fa for r in all_roles),
    }
