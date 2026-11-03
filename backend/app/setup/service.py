"""System settings and the first-run setup state."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User, UserRole
from app.core.errors import ConflictError
from app.setup.models import SystemSetting

SETUP_COMPLETED = "setup_completed"
COMPANY = "company"
SETUP_PROGRESS = "setup_progress"

DEFAULT_COMPANY: dict[str, Any] = {
    "legal_name": "PT Global Energi KITA",
    "npwp": "",
    "address": "",
    "phone": "",
    "email": "",
    "fiscal_year_start_month": 1,
    "currency": "IDR",
    "timezone": "Asia/Jakarta",
    "language": "id",
    "logo_attachment_id": None,
}

# Once true it never goes back, so a process-wide cache is safe.
_completed_cache: bool = False


def reset_cache() -> None:
    """Tests only."""
    global _completed_cache
    _completed_cache = False


async def get(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.get(SystemSetting, key)
    return default if row is None else row.value


async def put(session: AsyncSession, key: str, value: Any, actor_id: uuid.UUID | None) -> None:
    stmt = insert(SystemSetting).values(key=key, value=value, updated_by=actor_id)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": value, "updated_by": actor_id, "updated_at": func.now()},
    )
    await session.execute(stmt)


async def is_completed(session: AsyncSession) -> bool:
    global _completed_cache
    if _completed_cache:
        return True
    _completed_cache = bool(await get(session, SETUP_COMPLETED, False))
    return _completed_cache


async def active_super_admins(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.code == "super_admin", User.is_active.is_(True))
    )
    return list(rows.scalars())


async def ensure_super_admin_remains(session: AsyncSession, *, losing_user_id: uuid.UUID) -> None:
    """Refuse a change (deactivate / remove role) that would leave no active Super Admin."""
    remaining = [u for u in await active_super_admins(session) if u != losing_user_id]
    if not remaining:
        raise ConflictError(
            "LAST_SUPER_ADMIN",
            "Ini Super Admin aktif terakhir. Tambahkan Super Admin lain sebelum menonaktifkan "
            "atau mencabut perannya.",
        )
