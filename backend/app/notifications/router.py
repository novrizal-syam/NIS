import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import CurrentUser
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.core.pagination import PageParams, page_params
from app.notifications.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])
Session = Annotated[AsyncSession, Depends(get_session)]


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str | None
    created_at: datetime
    read: bool


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


async def _unread(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).where(
                    Notification.user_id == user_id, Notification.read_at.is_(None)
                )
            )
        ).scalar_one()
    )


@router.get("")
async def list_notifications(
    principal: CurrentUser,
    session: Session,
    pages: Annotated[PageParams, Depends(page_params)],
    unread_only: bool = False,
) -> NotificationPage:
    stmt = select(Notification).where(Notification.user_id == principal.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    rows = (
        await session.execute(
            stmt.order_by(Notification.created_at.desc())
            .offset(pages.offset)
            .limit(pages.page_size)
        )
    ).scalars()
    return NotificationPage(
        items=[
            NotificationOut(
                id=n.id,
                kind=n.kind,
                title=n.title,
                body=n.body,
                link=n.link,
                created_at=n.created_at,
                read=n.read_at is not None,
            )
            for n in rows
        ],
        total=total,
        unread=await _unread(session, principal.id),
    )


@router.get("/count")
async def count(principal: CurrentUser, session: Session) -> dict[str, int]:
    return {"unread": await _unread(session, principal.id)}


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: uuid.UUID, principal: CurrentUser, session: Session
) -> Response:
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != principal.id:
        raise NotFoundError("NOT_FOUND", "Notifikasi tidak ditemukan.")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        await session.commit()
    return Response(status_code=204)


@router.post("/read-all", status_code=204)
async def mark_all_read(principal: CurrentUser, session: Session) -> Response:
    await session.execute(
        update(Notification)
        .where(Notification.user_id == principal.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()
    return Response(status_code=204)
