"""Admin-only budget check for testing integrations (disabled in production)."""

import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import CurrentUser, Principal
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.services import budget_control as bc

router = APIRouter(prefix="/budget", tags=["budget"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _admin(principal: CurrentUser) -> Principal:
    if get_settings().is_production:
        raise NotFoundError("NOT_FOUND", "Data atau halaman tidak ditemukan.")
    if not principal.role_codes & {"admin", "super_admin"}:
        raise ForbiddenError("PERMISSION_DENIED", "Hanya Admin yang dapat memakai uji anggaran.")
    return principal


Admin = Annotated[Principal, Depends(_admin)]


class TestIn(BaseModel):
    project_id: uuid.UUID
    wbs_code: str = Field(min_length=1, max_length=20)
    cost_element_code: str = Field(min_length=1, max_length=20)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    # check: read-only; reserve/release: write ledger rows with doc_type "test"
    action: Literal["check", "reserve", "release"] = "check"
    doc_id: str = Field(default="manual", max_length=64)


def _bal(b: bc.Balance | None) -> dict[str, str] | None:
    if b is None:
        return None
    return {
        "budget": format(b.budget, "f"),
        "pre_commit": format(b.pre_commit, "f"),
        "commit": format(b.commit, "f"),
        "actual": format(b.actual, "f"),
        "available": format(b.available, "f"),
        "used_pct": str(b.used_pct),
    }


@router.post("/test-check")
async def test_check(body: TestIn, actor: Admin, session: Session) -> dict[str, Any]:
    line = await bc.resolve(session, body.project_id, body.wbs_code.upper(), body.cost_element_code)
    if body.action == "check":
        r = await bc.check(session, line, body.amount)
        return {
            "ok": r.ok,
            "code": r.code,
            "message": r.message,
            "shortfall": format(r.shortfall, "f"),
            "balance": _bal(r.balance),
        }
    if body.action == "reserve":
        bal = await bc.reserve(
            session, line, body.amount, doc_type="test", doc_id=body.doc_id, by=actor.id
        )
    else:
        bal = await bc.release(
            session,
            line,
            body.amount,
            bucket="pre_commit",
            doc_type="test",
            doc_id=body.doc_id,
            by=actor.id,
        )
    await session.commit()
    return {"ok": True, "code": None, "message": None, "shortfall": "0", "balance": _bal(bal)}
