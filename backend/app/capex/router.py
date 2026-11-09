"""CAPEX API (08)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal, require
from app.capex import calc
from app.capex import service as svc
from app.capex.models import CapexChange, CapexProposal, CapexReview
from app.core import access
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.services import budget_control as bc
from app.services.numbering import today_jakarta
from app.setup import service as settings_store

router = APIRouter(prefix="/capex", tags=["capex"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("capex", "view"))]
Creator = Annotated[Principal, Depends(require("capex", "create"))]
Editor = Annotated[Principal, Depends(require("capex", "edit"))]
Submitter = Annotated[Principal, Depends(require("capex", "submit"))]
Poster = Annotated[Principal, Depends(require("capex", "post"))]


async def _access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    return p.can("capex", "view" if mode == "read" else "edit")


access.register(svc.DOC, _access)


class ProposalIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    rjpp_ref: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    asset_class: str = Field(min_length=1, max_length=60)
    equipment_type_code: str | None = Field(default=None, max_length=20)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    funding: Literal["equity", "loan", "lease", "mixed"]
    day_rate: Decimal = Field(ge=0, max_digits=18, decimal_places=0)
    internal_day_rate: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=0)
    utilisation_pct: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    opex_pct: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    life_years: int = Field(ge=1, le=40)
    salvage_pct: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2)
    rental_annual: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=0)
    lease_monthly: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=0)
    strategic_fit: int = Field(default=3, ge=1, le=5)
    risk: int = Field(default=3, ge=1, le=5)
    tax_group: str | None = Field(default=None, max_length=30)


async def _get(session: AsyncSession, pid: uuid.UUID, lock: bool = False) -> CapexProposal:
    p = await session.get(CapexProposal, pid, with_for_update=lock)
    if p is None:
        raise NotFoundError("NOT_FOUND", "CAPEX tidak ditemukan.")
    return p


async def _detail(session: AsyncSession, p: CapexProposal) -> dict[str, Any]:
    out = svc.to_dict(p)
    out["auc"] = format(await svc.auc_balance(session, p), "f")
    if p.project_id:
        bal = await bc.available(session, await bc.resolve(session, p.project_id, svc.WBS, svc.CE))
        out["budget_status"] = {
            "budget": format(bal.budget, "f"),
            "committed": format(bal.pre_commit + bal.commit, "f"),
            "actual": format(bal.actual, "f"),
            "available": format(bal.available, "f"),
        }
    out["changes"] = [
        {
            "id": str(c.id),
            "number": c.number,
            "amount": format(c.amount, "f"),
            "reason": c.reason,
            "status": c.status,
            "request_id": str(c.request_id) if c.request_id else None,
        }
        for c in (
            await session.execute(
                select(CapexChange)
                .where(CapexChange.proposal_id == p.id)
                .order_by(CapexChange.created_at)
            )
        ).scalars()
    ]
    out["reviews"] = [
        {
            "months": r.months,
            "actuals": r.actuals,
            "comment": r.comment,
            "reviewed_on": r.reviewed_on.isoformat(),
        }
        for r in (
            await session.execute(
                select(CapexReview)
                .where(CapexReview.proposal_id == p.id)
                .order_by(CapexReview.months)
            )
        ).scalars()
    ]
    return out


@router.get("/settings")
async def get_settings(_: Viewer, session: Session) -> dict[str, Any]:
    return {
        "discount_rate": format(await svc.discount_rate(session), "f"),
        "rental_spend_12m": format(await svc.rental_spend(session), "f"),
    }


class RateIn(BaseModel):
    discount_rate: Decimal = Field(gt=0, le=50, max_digits=5, decimal_places=2)


@router.put("/settings")
async def put_settings(
    body: RateIn,
    actor: Annotated[Principal, Depends(require("capex", "approve"))],
    session: Session,
) -> dict[str, Any]:
    await settings_store.put(session, svc.RATE_KEY, format(body.discount_rate, "f"), actor.id)
    await session.commit()
    return {"discount_rate": format(body.discount_rate, "f")}


@router.post("/calculate")
async def calculate(body: ProposalIn, _: Viewer, session: Session) -> dict[str, Any]:
    """Business case preview without saving (live calculator)."""
    rental = body.rental_annual or await svc.rental_spend(session)
    out = calc.evaluate(
        calc.CaseIn(
            amount=body.amount,
            day_rate=body.day_rate,
            utilisation_pct=body.utilisation_pct,
            opex_pct=body.opex_pct,
            life_years=body.life_years,
            salvage_pct=body.salvage_pct,
            rental_annual=rental,
            lease_monthly=body.lease_monthly,
            discount_rate=await svc.discount_rate(session),
            strategic_fit=body.strategic_fit,
            risk=body.risk,
        )
    )
    return {**out.as_dict(), "rental_annual": format(rental, "f")}


@router.get("")
async def list_proposals(
    _: Viewer, session: Session, status: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(CapexProposal).order_by(CapexProposal.priority_score.desc(), CapexProposal.number)
    if status:
        stmt = stmt.where(CapexProposal.status == status)
    return [svc.to_dict(p) for p in (await session.execute(stmt)).scalars()]


@router.post("")
async def create(body: ProposalIn, actor: Creator, session: Session) -> dict[str, Any]:
    p = await svc.create(session, actor, body.model_dump())
    await session.commit()
    return await _detail(session, p)


@router.get("/{pid}")
async def get(pid: uuid.UUID, _: Viewer, session: Session) -> dict[str, Any]:
    return await _detail(session, await _get(session, pid))


@router.put("/{pid}")
async def update(
    pid: uuid.UUID, body: ProposalIn, actor: Editor, session: Session
) -> dict[str, Any]:
    p = await svc.update(session, actor, await _get(session, pid, True), body.model_dump())
    await session.commit()
    return await _detail(session, p)


@router.post("/{pid}/submit")
async def submit(pid: uuid.UUID, actor: Submitter, session: Session) -> dict[str, Any]:
    p = await _get(session, pid, True)
    req = await svc.submit(session, actor, p)
    await session.commit()
    return {**svc.to_dict(p), "request_id": str(req.id)}


class MilestoneIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    on: date | None = None
    description: str = Field(min_length=3, max_length=200)
    vendor_code: str | None = Field(default=None, max_length=20)
    pay: Literal["bank", "payable"] = "payable"
    bank_account_id: uuid.UUID | None = None


@router.post("/{pid}/milestones")
async def milestone(
    pid: uuid.UUID, body: MilestoneIn, actor: Poster, session: Session
) -> dict[str, Any]:
    p = await _get(session, pid, True)
    entry = await svc.milestone(
        session,
        actor,
        p,
        amount=body.amount,
        on=body.on or today_jakarta(),
        description=body.description,
        vendor_code=body.vendor_code,
        pay=body.pay,
        bank_account_id=body.bank_account_id,
    )
    await session.commit()
    return {**(await _detail(session, p)), "journal_id": str(entry.id)}


class ChangeIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=0)
    reason: str = Field(min_length=10, max_length=1000)


@router.post("/{pid}/changes")
async def change(
    pid: uuid.UUID, body: ChangeIn, actor: Creator, session: Session
) -> dict[str, Any]:
    p = await _get(session, pid, True)
    ch = await svc.request_change(session, actor, p, body.amount, body.reason)
    await session.commit()
    return {"id": str(ch.id), "number": ch.number, "request_id": str(ch.request_id)}


class CommissionIn(BaseModel):
    on: date | None = None
    attachment_id: uuid.UUID
    asset_code: str = Field(min_length=2, max_length=30)


@router.post("/{pid}/commission")
async def commission(
    pid: uuid.UUID, body: CommissionIn, actor: Editor, session: Session
) -> dict[str, Any]:
    p = await svc.commission(
        session,
        actor,
        await _get(session, pid, True),
        on=body.on or today_jakarta(),
        attachment_id=body.attachment_id,
        asset_code=body.asset_code,
    )
    await session.commit()
    return await _detail(session, p)


class OnIn(BaseModel):
    on: date | None = None


@router.post("/{pid}/capitalise")
async def capitalise(pid: uuid.UUID, body: OnIn, actor: Poster, session: Session) -> dict[str, Any]:
    p = await _get(session, pid, True)
    asset = await svc.capitalise(session, actor, p, on=body.on or today_jakarta())
    await session.commit()
    return {
        **(await _detail(session, p)),
        "asset": {"code": asset.code, "cost": format(asset.acquisition_cost, "f")},
    }


@router.get("/{pid}/actuals/{months}")
async def actuals(pid: uuid.UUID, months: int, _: Viewer, session: Session) -> dict[str, Any]:
    return await svc.actuals(session, await _get(session, pid), months)


class ReviewIn(BaseModel):
    months: Literal[6, 12]
    comment: str = Field(min_length=10, max_length=5000)


@router.post("/{pid}/reviews")
async def review(pid: uuid.UUID, body: ReviewIn, actor: Editor, session: Session) -> dict[str, Any]:
    p = await _get(session, pid, True)
    await svc.review(session, actor, p, body.months, body.comment)
    await session.commit()
    return await _detail(session, p)
