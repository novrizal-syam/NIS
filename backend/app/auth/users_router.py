import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import CurrentUser
from app.core import access
from app.core.db import get_session

router = APIRouter(prefix="/users", tags=["users"])
access.register("user", access.module_checker("users", "users"))


class UserLookup(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


@router.get("/lookup")
async def lookup(
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> list[UserLookup]:
    """Name/email search of active users (for pickers such as delegation)."""
    like = f"%{q.strip()}%"
    rows = await session.execute(
        select(User)
        .where(User.is_active.is_(True), or_(User.full_name.ilike(like), User.email.ilike(like)))
        .order_by(User.full_name)
        .limit(20)
    )
    return [UserLookup(id=u.id, full_name=u.full_name, email=u.email) for u in rows.scalars()]
