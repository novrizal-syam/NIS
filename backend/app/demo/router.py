from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import CurrentUser, Principal
from app.core.db import get_session
from app.core.errors import ForbiddenError
from app.demo import seed

router = APIRouter(prefix="/admin/demo", tags=["admin"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _super_admin(principal: CurrentUser) -> Principal:
    # CLAUDE.md rule 9: Super Admin only (not Admin, not a permission that can be granted).
    if "super_admin" not in principal.role_codes or principal.active_role not in (
        None,
        "super_admin",
    ):
        raise ForbiddenError(
            "SUPER_ADMIN_ONLY", "Hanya Super Admin yang dapat mengelola data demo."
        )
    return principal


SuperAdmin = Annotated[Principal, Depends(_super_admin)]


@router.get("")
async def status(_: SuperAdmin, session: Session) -> dict[str, Any]:
    counts = await seed.demo_counts(session)
    return {"present": any(counts.values()), "counts": counts}


@router.post("/remove")
async def remove_demo(principal: SuperAdmin, session: Session) -> dict[str, Any]:
    summary = await seed.remove(session, actor_id=principal.id)
    await session.commit()
    return {"removed": summary.counts}
