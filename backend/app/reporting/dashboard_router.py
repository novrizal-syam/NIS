"""Dashboards API (10): process map, OKR and targets, role dashboards, management pack."""

import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import CurrentUser, Principal, require
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.reporting import dashboards, management_pack
from app.services import audit
from app.services.numbering import today_jakarta
from app.setup import service as settings_store

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
Session = Annotated[AsyncSession, Depends(get_session)]
Reporting = Annotated[Principal, Depends(require("reporting", "view"))]
TARGET_EDITORS = {"director", "head_of_finance", "super_admin"}


@router.get("/process-map")
async def process_map(p: CurrentUser, session: Session) -> dict[str, Any]:
    return await dashboards.process_map(session, p)


@router.get("/okr")
async def okr(_: Reporting, session: Session, year: int | None = None) -> dict[str, Any]:
    return await dashboards.okr(session, year or today_jakarta().year)


class TargetsIn(BaseModel):
    revenue: int = Field(ge=0)
    new_contracts: int = Field(ge=0)
    win_rate_pct: float = Field(ge=0, le=100)
    invoice_to_cash_days: float = Field(ge=0, le=365)
    cost_overrun_change_pct: float = Field(ge=-100, le=100)
    utilisation_pct: float = Field(ge=0, le=100)
    downtime_pct: float = Field(ge=0, le=100)
    net_margin_pct: float = Field(ge=-100, le=100)
    cash_months_opex: float = Field(ge=0, le=60)
    tax_penalties: int = Field(ge=0)
    accidents: int = Field(ge=0)


@router.get("/okr/targets/{year}")
async def get_targets(year: int, _: Reporting, session: Session) -> dict[str, Any]:
    return await dashboards.targets(session, year)


@router.put("/okr/targets/{year}")
async def put_targets(year: int, body: TargetsIn, p: Reporting, session: Session) -> dict[str, Any]:
    if not p.role_codes & TARGET_EDITORS:
        raise ForbiddenError(
            "PERMISSION_DENIED", "Target OKR diubah oleh Direktur / Head of Finance."
        )
    stored = await settings_store.get(session, dashboards.TARGETS_KEY, {}) or {}
    before = stored.get(str(year))
    stored[str(year)] = body.model_dump()
    await settings_store.put(session, dashboards.TARGETS_KEY, stored, p.id)
    await audit.record(
        session,
        action="update",
        entity_type="okr_targets",
        entity_id=str(year),
        actor_id=p.id,
        before=before,
        after=stored[str(year)],
    )
    await session.commit()
    return await dashboards.targets(session, year)


@router.get("/roles")
async def my_dashboards(p: CurrentUser) -> list[str]:
    return dashboards.dashboards_for(p)


@router.get("/roles/{kind}")
async def role_dashboard(kind: str, p: CurrentUser, session: Session) -> dict[str, Any]:
    if kind not in dashboards.ROLE_DASHBOARDS:
        raise NotFoundError("NOT_FOUND", "Dasbor tidak dikenal.")
    if kind not in dashboards.dashboards_for(p):
        raise ForbiddenError("PERMISSION_DENIED", "Dasbor ini bukan untuk peran Anda.")
    return {"kind": kind, "tiles": await dashboards.role_tiles(session, kind)}


@router.get("/management-pack/{year}/{month}")
async def pack(year: int, month: int, p: Reporting, session: Session) -> StreamingResponse:
    if not 1 <= month <= 12:
        raise NotFoundError("NOT_FOUND", "Bulan tidak dikenal.")
    company = (await settings_store.get(session, "company", {}) or {}).get(
        "legal_name"
    ) or "PT Global Energi KITA"
    data = await management_pack.build(session, str(company), year, month)
    await audit.record(
        session,
        action="export",
        entity_type="management_pack",
        entity_id=f"{year}-{month:02d}",
        actor_id=p.id,
    )
    await session.commit()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="laporan-manajemen-{year}-{month:02d}.pdf"'
            )
        },
    )
