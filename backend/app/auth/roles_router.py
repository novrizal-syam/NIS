from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, UserRole
from app.auth.principal import CurrentUser
from app.core.db import get_session

router = APIRouter(prefix="/roles", tags=["roles"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("")
async def list_roles(_: CurrentUser, session: Session) -> list[dict[str, Any]]:
    counts = dict(
        (await session.execute(select(UserRole.role_id, func.count()).group_by(UserRole.role_id)))
        .tuples()
        .all()
    )
    rows = (
        await session.execute(select(Role).order_by(Role.is_system.desc(), Role.name))
    ).scalars()
    return [
        {
            "id": str(r.id),
            "code": r.code,
            "name": r.name,
            "description": r.description,
            "is_system": r.is_system,
            "is_external": r.is_external,
            "requires_2fa": r.requires_2fa,
            "is_active": r.is_active,
            "user_count": counts.get(r.id, 0),
        }
        for r in rows
    ]
