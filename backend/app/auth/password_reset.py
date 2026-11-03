"""Forgot / reset password: 60-minute single-use tokens stored hashed; 3 requests per email
per hour; the same answer whether or not the email exists."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, String, func, select, text, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.auth import service as auth_service
from app.auth.models import User
from app.auth.security import hash_password, hash_refresh_token, validate_password_policy
from app.core.errors import AppError
from app.core.models import Base
from app.services import audit

RESET_MINUTES = 60
MAX_PER_HOUR = 3
GENERIC_MESSAGE = (
    "Jika email terdaftar dan aktif, tautan untuk mengatur ulang kata sandi telah dikirim. "
    "Periksa kotak masuk Anda."
)


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetRequest(Base):
    """Every request, known email or not, for the per-email rate limit."""

    __tablename__ = "password_reset_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ip: Mapped[str | None] = mapped_column(String(64))


def _now() -> datetime:
    return datetime.now(UTC)


async def request_reset(
    session: AsyncSession, email: str, ip: str | None
) -> tuple[User, str] | None:
    """Returns (user, raw token) to email, or None. Raises only on rate limit."""
    normalized = email.strip().lower()
    recent = (
        await session.execute(
            select(func.count()).where(
                PasswordResetRequest.email == normalized,
                PasswordResetRequest.created_at > _now() - timedelta(hours=1),
            )
        )
    ).scalar_one()
    if recent >= MAX_PER_HOUR:
        raise AppError(
            "TOO_MANY_REQUESTS",
            "Terlalu banyak permintaan atur ulang kata sandi. Coba lagi dalam 1 jam.",
            status_code=429,
        )
    session.add(PasswordResetRequest(email=normalized, ip=ip))
    user = await auth_service.find_user_by_email(session, normalized)
    if user is None or not user.is_active:
        return None
    await session.execute(
        update(PasswordReset)
        .where(
            PasswordReset.user_id == user.id,
            PasswordReset.used_at.is_(None),
            PasswordReset.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    raw = secrets.token_urlsafe(32)
    session.add(
        PasswordReset(
            user_id=user.id,
            token_hash=hash_refresh_token(raw),
            expires_at=_now() + timedelta(minutes=RESET_MINUTES),
        )
    )
    await audit.record(
        session,
        action="password_reset_requested",
        entity_type="user",
        entity_id=user.id,
        actor_id=None,
        after={"ip": ip},
    )
    return user, raw


async def reset(session: AsyncSession, raw: str, password: str) -> User:
    row = (
        await session.execute(
            select(PasswordReset)
            .where(PasswordReset.token_hash == hash_refresh_token(raw))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.used_at or row.revoked_at:
        raise AppError(
            "RESET_INVALID", "Tautan atur ulang tidak valid atau sudah dipakai.", status_code=410
        )
    if row.expires_at <= _now():
        raise AppError(
            "RESET_EXPIRED",
            "Tautan atur ulang sudah kedaluwarsa. Minta tautan baru.",
            status_code=410,
        )
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AppError("ACCOUNT_INACTIVE", "Akun tidak aktif. Hubungi admin.", status_code=403)
    from app.auth.admin import role_codes  # local: avoid import cycle

    validate_password_policy(
        password, email=user.email, strong="super_admin" in await role_codes(session, user.id)
    )
    user.password_hash = hash_password(password)
    user.must_change_password = False
    user.password_changed_at = _now()
    user.failed_login_count, user.locked_until = 0, None
    row.used_at = _now()
    await auth_service.revoke_all_for_user(session, user.id)
    await audit.record(
        session,
        action="password_reset",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        note="Lewat tautan lupa kata sandi",
    )
    return user
