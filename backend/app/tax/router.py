"""Tax workspace (/tax) and period close incl. depreciation (/close) - 07d."""

import uuid
from datetime import date, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import CurrentUser, Principal, require
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.master.models import FiscalPeriod
from app.services.numbering import today_jakarta
from app.setup import service as settings_store
from app.tax import close as close_svc
from app.tax import depreciation as dep
from app.tax import service as svc
from app.tax.models import DepreciationRun, TaxReturn

router = APIRouter(prefix="/tax", tags=["tax"])
close_router = APIRouter(prefix="/close", tags=["close"])
Session = Annotated[AsyncSession, Depends(get_session)]
TaxViewer = Annotated[Principal, Depends(require("tax", "view"))]
TaxWorker = Annotated[Principal, Depends(require("tax", "edit"))]
TaxPoster = Annotated[Principal, Depends(require("tax", "post"))]
FinViewer = Annotated[Principal, Depends(require("finance", "view"))]
FinPoster = Annotated[Principal, Depends(require("finance", "post"))]


def _m(v: Any) -> str | None:
    return format(v, "f") if v is not None else None


def _return_out(r: TaxReturn, today: date) -> dict[str, Any]:
    pending_pay = r.status in ("draft", "billed") and r.amount > 0
    return {
        "id": str(r.id),
        "year": r.year,
        "month": r.month,
        "tax_type": r.tax_type,
        "label": svc.LABELS[r.tax_type],
        "status": r.status,
        "output_tax": _m(r.output_tax),
        "input_tax": _m(r.input_tax),
        "carried_in": _m(r.carried_in),
        "carry_forward": _m(r.carry_forward),
        "amount": _m(r.amount),
        "pay_due": r.pay_due.isoformat(),
        "file_due": r.file_due.isoformat(),
        "pay_overdue": pending_pay and today > r.pay_due,
        "file_overdue": r.status != "filed" and today > r.file_due,
        "due_soon": r.status != "filed"
        and today
        >= min(r.pay_due if pending_pay else r.file_due, r.file_due)
        - timedelta(days=svc.ALERT_DAYS),
        "billing_code": r.billing_code,
        "billing_expires": r.billing_expires.isoformat() if r.billing_expires else None,
        "ntpn": r.ntpn,
        "paid_on": r.paid_on.isoformat() if r.paid_on else None,
        "payment_method": r.payment_method,
        "payment_run_id": str(r.payment_run_id) if r.payment_run_id else None,
        "journal_id": str(r.journal_id) if r.journal_id else None,
        "bpe_no": r.bpe_no,
        "filed_on": r.filed_on.isoformat() if r.filed_on else None,
    }


@router.get("/periods/{year}/{month}")
async def workspace(year: int, month: int, _: TaxViewer, session: Session) -> dict[str, Any]:
    if not 1 <= month <= 12:
        raise NotFoundError("NOT_FOUND", "Periode tidak dikenal.")
    rows = await svc.returns(session, year, month)
    await session.commit()
    today = today_jakarta()
    return {
        "year": year,
        "month": month,
        "returns": [_return_out(r, today) for r in rows],
        "documents": await svc.documents(session, year, month),
    }


class BillingIn(BaseModel):
    billing_code: str = Field(min_length=15, max_length=15)
    expires: date | None = None


class PayIn(BaseModel):
    ntpn: str = Field(min_length=16, max_length=16)
    paid_on: date
    method: Literal["payment_run", "direct"]
    payment_run_id: uuid.UUID | None = None
    bank_account_id: uuid.UUID | None = None


class FileIn(BaseModel):
    bpe_no: str = Field(min_length=5, max_length=40)
    filed_on: date


@router.post("/returns/{rid}/billing")
async def billing(
    rid: uuid.UUID, body: BillingIn, actor: TaxWorker, session: Session
) -> dict[str, Any]:
    r = await svc.set_billing(
        session, actor, await svc._get(session, rid), body.billing_code, body.expires
    )
    await session.commit()
    return _return_out(r, today_jakarta())


@router.post("/returns/{rid}/pay")
async def pay(rid: uuid.UUID, body: PayIn, actor: TaxPoster, session: Session) -> dict[str, Any]:
    r = await svc.pay(
        session,
        actor,
        await svc._get(session, rid),
        ntpn=body.ntpn,
        paid_on=body.paid_on,
        method=body.method,
        payment_run_id=body.payment_run_id,
        bank_account_id=body.bank_account_id,
    )
    await session.commit()
    return _return_out(r, today_jakarta())


@router.post("/returns/{rid}/file")
async def file(rid: uuid.UUID, body: FileIn, actor: TaxPoster, session: Session) -> dict[str, Any]:
    r = await svc.file(
        session, actor, await svc._get(session, rid), bpe_no=body.bpe_no, filed_on=body.filed_on
    )
    await session.commit()
    return _return_out(r, today_jakarta())


@router.get("/deadlines")
async def get_deadlines(_: TaxViewer, session: Session) -> dict[str, Any]:
    return {
        **svc.DEFAULT_DEADLINES,
        **(await settings_store.get(session, svc.DEADLINES_KEY, {}) or {}),
    }


class DeadlinesIn(BaseModel):
    pph_pay_day: int = Field(ge=1, le=31)
    pph_file_day: int = Field(ge=1, le=31)
    ppn_months_after: int = Field(ge=1, le=3)


@router.put("/deadlines")
async def put_deadlines(body: DeadlinesIn, actor: TaxWorker, session: Session) -> dict[str, Any]:
    await settings_store.put(session, svc.DEADLINES_KEY, body.model_dump(), actor.id)
    await session.commit()
    return body.model_dump()


@router.post("/run-alerts")
async def run_alerts(_: TaxWorker, session: Session) -> dict[str, Any]:
    n = await svc.deadline_alerts(session)
    await session.commit()
    return {"sent": n}


@router.get("/fiscal-depreciation/{year}")
async def fiscal_depreciation(year: int, p: CurrentUser, session: Session) -> dict[str, Any]:
    if not (p.can("tax", "view") or p.can("finance", "view")):
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin melihat laporan fiskal.")
    return await dep.fiscal_report(session, year)


# ---------------------------------------------------------------- close


def _period_out(p: FiscalPeriod | None, year: int, month: int) -> dict[str, Any]:
    return {"year": year, "month": month, "status": p.status if p else "open"}


@close_router.get("/periods/{year}/{month}")
async def close_status(year: int, month: int, _: FinViewer, session: Session) -> dict[str, Any]:
    p = (
        await session.execute(
            select(FiscalPeriod).where(FiscalPeriod.year == year, FiscalPeriod.month == month)
        )
    ).scalar_one_or_none()
    dr = (
        await session.execute(
            select(DepreciationRun).where(
                DepreciationRun.year == year, DepreciationRun.month == month
            )
        )
    ).scalar_one_or_none()
    return {
        **_period_out(p, year, month),
        "checks": await close_svc.checklist(session, year, month),
        "depreciation": (
            {
                "total": _m(dr.total),
                "fiscal_total": _m(dr.fiscal_total),
                "journal_id": str(dr.journal_id) if dr.journal_id else None,
                "lines": dr.lines,
            }
            if dr
            else None
        ),
        "history": [
            {
                "action": h.action,
                "by": str(h.by),
                "at": h.at.isoformat(),
                "note": h.note,
            }
            for h in await close_svc.history(session, year, month)
        ],
    }


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


@close_router.post("/periods/{year}/{month}/depreciation")
async def run_depreciation(
    year: int, month: int, actor: FinPoster, session: Session
) -> dict[str, Any]:
    dr = await dep.run(session, actor, year, month)
    await session.commit()
    return {
        "total": _m(dr.total),
        "fiscal_total": _m(dr.fiscal_total),
        "lines": dr.lines,
        "journal_id": str(dr.journal_id) if dr.journal_id else None,
    }


@close_router.post("/periods/{year}/{month}/close")
async def close_period(
    year: int,
    month: int,
    body: NoteIn,
    actor: Annotated[Principal, Depends(require("finance", "approve"))],
    session: Session,
) -> dict[str, Any]:
    p = await close_svc.close(session, actor, year, month, body.note)
    await session.commit()
    return _period_out(p, year, month)


@close_router.post("/periods/{year}/{month}/reopen")
async def reopen_period(
    year: int,
    month: int,
    body: ReasonIn,
    actor: Annotated[Principal, Depends(require("finance", "approve"))],
    session: Session,
) -> dict[str, Any]:
    p = await close_svc.reopen(session, actor, year, month, body.reason)
    await session.commit()
    return _period_out(p, year, month)
