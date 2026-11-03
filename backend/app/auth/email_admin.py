from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import CurrentUser, Principal
from app.core.db import get_session
from app.core.errors import ForbiddenError
from app.services import email, email_log
from app.services import email_templates as templates

router = APIRouter(prefix="/admin/email", tags=["admin"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _super_admin(principal: CurrentUser) -> Principal:
    if "super_admin" not in principal.role_codes:
        raise ForbiddenError("SUPER_ADMIN_ONLY", "Hanya Super Admin yang dapat mengirim email uji.")
    return principal


@router.get("/status")
async def status(_: Annotated[Principal, Depends(_super_admin)]) -> dict[str, Any]:
    return {"provider": email.provider()}


@router.post("/test")
async def send_test(principal: Annotated[Principal, Depends(_super_admin)]) -> dict[str, Any]:
    """Synchronous so the admin sees the outcome (sent / failed / not_configured)."""
    user = principal.user
    result = await email_log.deliver(
        "test", user.email, templates.test_message(user.full_name), user.id
    )
    return {"status": result.status, "error": result.error, "to": user.email}
