"""Ledger API (07a): journals, reversal, manual journals, opening balance, posting rules,
financial reports with Excel/PDF export."""

import io
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Scope
from app.auth.principal import CurrentUser, Principal, require
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.finance import journal_service as js
from app.finance.models import JournalEntry, ManualJournal
from app.master.models import Account
from app.reporting import ledger_reports as rep
from app.services import audit, ledger, posting_rules
from app.services.export import build_xlsx
from app.services.numbering import today_jakarta
from app.setup import service as settings_store

router = APIRouter(prefix="/ledger", tags=["ledger"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("finance", "view"))]
Creator = Annotated[Principal, Depends(require("finance", "create"))]
Approver = Annotated[Principal, Depends(require("finance", "approve"))]


def _m(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


def _json(v: Any) -> Any:
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


async def _report_reader(principal: CurrentUser) -> Principal:
    if not (principal.can("finance", "view") or principal.can("reporting", "view")):
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin melihat laporan keuangan.")
    return principal


Reader = Annotated[Principal, Depends(_report_reader)]


async def _mj_access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    return p.can("finance", "view" if mode == "read" else "create")


access.register(js.DOC, _mj_access)


# ---------------------------------------------------------------- journals


@router.get("/journals")
async def list_journals(
    _: Viewer,
    session: Session,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    page: int = 1,
) -> dict[str, Any]:
    stmt = select(JournalEntry)
    if date_from:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            JournalEntry.number.ilike(like)
            | JournalEntry.source_number.ilike(like)
            | JournalEntry.description.ilike(like)
        )
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(JournalEntry.entry_date.desc(), JournalEntry.number.desc())
            .offset((max(page, 1) - 1) * 50)
            .limit(50)
        )
    ).scalars()
    return {
        "total": total,
        "items": [
            {
                "id": str(e.id),
                "number": e.number,
                "entry_date": e.entry_date.isoformat(),
                "description": e.description,
                "source_type": e.source_type,
                "source_number": e.source_number,
                "event": e.event,
                "total": _m(e.total),
                "reversal_of": str(e.reversal_of) if e.reversal_of else None,
                "reversed": e.reversed_by is not None,
            }
            for e in rows
        ],
    }


@router.get("/journals/{jid}")
async def get_journal(jid: uuid.UUID, _: Viewer, session: Session) -> dict[str, Any]:
    e = await session.get(JournalEntry, jid)
    if e is None:
        raise NotFoundError("NOT_FOUND", "Jurnal tidak ditemukan.")
    names = dict((await session.execute(select(Account.code, Account.name))).tuples().all())
    return {
        "id": str(e.id),
        "number": e.number,
        "entry_date": e.entry_date.isoformat(),
        "period": e.period,
        "description": e.description,
        "source_type": e.source_type,
        "source_number": e.source_number,
        "event": e.event,
        "total": _m(e.total),
        "reversal_of": str(e.reversal_of) if e.reversal_of else None,
        "reversed_by": str(e.reversed_by) if e.reversed_by else None,
        "lines": [
            {
                "account": x.account_code,
                "name": names.get(x.account_code),
                "debit": _m(x.debit),
                "credit": _m(x.credit),
                "memo": x.memo,
                "project_id": str(x.project_id) if x.project_id else None,
                "cost_element": x.cost_element_code,
                "asset": x.asset_code,
                "partner": x.partner_code,
            }
            for x in await ledger.lines_of(session, e.id)
        ],
    }


class ReverseBody(BaseModel):
    reason: str = Field(min_length=5, max_length=300)
    reversal_date: date | None = None


@router.post("/journals/{jid}/reverse")
async def reverse_journal(
    jid: uuid.UUID, body: ReverseBody, actor: Approver, session: Session
) -> dict[str, Any]:
    if actor.scope_for("finance", "approve") != Scope.ALL:
        raise ForbiddenError("PERMISSION_DENIED", "Pembalikan jurnal oleh Lead Controller.")
    rev = await ledger.reverse(
        session, jid, on=body.reversal_date or today_jakarta(), reason=body.reason, by=actor.id
    )
    await session.commit()
    return {"id": str(rev.id), "number": rev.number}


# ---------------------------------------------------------------- manual journals


class MjLine(BaseModel):
    account: str = Field(min_length=3, max_length=10)
    debit: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=0)
    credit: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=0)
    memo: str | None = Field(default=None, max_length=300)
    project_id: uuid.UUID | None = None
    cost_element: str | None = Field(default=None, max_length=20)
    cost_center: str | None = Field(default=None, max_length=20)
    asset: str | None = Field(default=None, max_length=30)
    partner_type: str | None = Field(default=None, pattern="^(client|vendor|employee)$")
    partner_code: str | None = Field(default=None, max_length=30)


class MjBody(BaseModel):
    entry_date: date
    description: str = Field(min_length=5, max_length=300)
    lines: list[MjLine] = Field(min_length=2, max_length=200)

    def raw(self) -> list[dict[str, Any]]:
        return [{k: _json(v) for k, v in x.model_dump().items()} for x in self.lines]


def _mj(m: ManualJournal) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "number": m.number,
        "entry_date": m.entry_date.isoformat(),
        "description": m.description,
        "lines": m.lines,
        "total": _m(m.total),
        "status": m.status,
        "request_id": str(m.request_id) if m.request_id else None,
        "journal_id": str(m.journal_id) if m.journal_id else None,
        "reject_reason": m.reject_reason,
    }


@router.get("/manual-journals")
async def list_mj(_: Viewer, session: Session) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(ManualJournal).order_by(ManualJournal.created_at.desc()).limit(200)
    )
    return [_mj(m) for m in rows.scalars()]


@router.post("/manual-journals", status_code=201)
async def create_mj(body: MjBody, actor: Creator, session: Session) -> dict[str, Any]:
    m = await js.create_manual(session, actor, body.entry_date, body.description, body.raw())
    await session.commit()
    return _mj(m)


async def _get_mj(session: AsyncSession, mid: uuid.UUID) -> ManualJournal:
    m = await session.get(ManualJournal, mid, with_for_update=True)
    if m is None:
        raise NotFoundError("NOT_FOUND", "Jurnal manual tidak ditemukan.")
    return m


@router.put("/manual-journals/{mid}")
async def update_mj(
    mid: uuid.UUID, body: MjBody, actor: Creator, session: Session
) -> dict[str, Any]:
    m = await js.update_manual(
        session, actor, await _get_mj(session, mid), body.entry_date, body.description, body.raw()
    )
    await session.commit()
    return _mj(m)


@router.post("/manual-journals/{mid}/submit")
async def submit_mj(mid: uuid.UUID, actor: Creator, session: Session) -> dict[str, Any]:
    m = await _get_mj(session, mid)
    await js.submit_manual(session, actor, m)
    await session.commit()
    return _mj(m)


# ---------------------------------------------------------------- opening balance


@router.get("/opening")
async def opening_status(_: Viewer, session: Session) -> dict[str, Any]:
    return {"opening_date": await settings_store.get(session, js.OPENING_KEY, None)}


@router.get("/opening/template")
async def opening_template(_: Approver, session: Session) -> StreamingResponse:
    """The go-live workbook: one sheet per source with the expected columns, plus the
    postable accounts and master codes to copy from (10f)."""
    data = await js.opening_template(session)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="saldo-awal.xlsx"'},
    )


@router.post("/opening")
async def opening_import(
    actor: Approver,
    session: Session,
    file: Annotated[UploadFile, File()],
    as_of: Annotated[date, Form()],
    dry_run: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    """Import the opening balance. With dry_run the workbook is checked and the journal is
    built, then everything is rolled back: the wizard shows the preview before posting."""
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", "Berkas maksimal 10 MB.", status_code=413)
    res = await js.import_opening(session, actor, data, as_of)
    if res.errors:
        await session.rollback()
        raise AppError(
            "OPENING_INVALID",
            f"{len(res.errors)} masalah; tidak ada yang disimpan.",
            status_code=422,
            details={"errors": res.errors[:200]},
        )
    if dry_run:
        await session.rollback()
        return {**{k: _json(v) for k, v in res.__dict__.items()}, "journal": None, "dry_run": True}
    await session.commit()
    return {**{k: _json(v) for k, v in res.__dict__.items()}, "dry_run": False}


# ---------------------------------------------------------------- posting rules


@router.get("/posting-rules")
async def get_rules(_: Viewer, session: Session) -> list[dict[str, Any]]:
    names = dict((await session.execute(select(Account.code, Account.name))).tuples().all())
    return [
        {
            "event": r.event,
            "label": r.label,
            "used_by": r.used_by,
            "legs": [
                {
                    "role": leg.role,
                    "side": leg.side,
                    "account": leg.account,
                    "account_name": names.get(leg.account),
                    "default": next(
                        x.account
                        for x in posting_rules.RULES[r.event].legs
                        if x.role == leg.role and x.side == leg.side
                    ),
                    "dims": list(leg.dims),
                }
                for leg in r.legs
            ],
        }
        for r in (await ledger.rules(session)).values()
    ]


class OverrideBody(BaseModel):
    event: str
    role: str
    account: str = Field(min_length=3, max_length=12)


@router.put("/posting-rules")
async def override_rule(
    body: OverrideBody, actor: Approver, session: Session
) -> list[dict[str, Any]]:
    rule = posting_rules.RULES.get(body.event)
    if rule is None or body.role not in {leg.role for leg in rule.legs}:
        raise AppError("RULE_INVALID", "Aturan atau peran tidak dikenal.", status_code=422)
    if not body.account.startswith("@"):
        acc = (
            await session.execute(select(Account).where(Account.code == body.account))
        ).scalar_one_or_none()
        if acc is None or not acc.is_postable or not acc.is_active:
            raise AppError(
                "ACCOUNT_NOT_POSTABLE",
                f"Akun {body.account} bukan akun posting aktif.",
                status_code=422,
            )
    current = dict(await settings_store.get(session, ledger.OVERRIDES_KEY, {}) or {})
    before = dict(current.get(body.event) or {})
    current[body.event] = {**before, body.role: body.account}
    await settings_store.put(session, ledger.OVERRIDES_KEY, current, actor.id)
    await audit.record(
        session,
        action="update",
        entity_type="posting_rule",
        entity_id=body.event,
        actor_id=actor.id,
        before=before,
        after=current[body.event],
    )
    await session.commit()
    return await get_rules(actor, session)


# ---------------------------------------------------------------- reports


REPORTS = (
    "trial-balance",
    "general-ledger",
    "profit-loss",
    "profit-loss-projects",
    "balance-sheet",
    "cash-flow",
    "dimensions",
    "project-pnl",
)


async def _build(
    session: AsyncSession,
    name: str,
    *,
    as_of: date | None,
    date_from: date | None,
    date_to: date | None,
    account: str | None,
    project_id: uuid.UUID | None,
    dimension: str | None,
    account_prefix: str | None,
) -> rep.Report:
    today = today_jakarta()
    to = date_to or as_of or today
    frm = date_from or to.replace(day=1)
    if name == "trial-balance":
        return await rep.trial_balance(session, as_of or today)
    if name == "general-ledger":
        if not account:
            raise AppError("ACCOUNT_REQUIRED", "Pilih akun.", status_code=422)
        return await rep.general_ledger(session, account, frm, to, project_id)
    if name == "profit-loss":
        return await rep.profit_loss(session, to, project_id)
    if name == "profit-loss-projects":
        return await rep.profit_loss_by_project(
            session, date_from or to.replace(month=1, day=1), to
        )
    if name == "balance-sheet":
        return await rep.balance_sheet(session, as_of or today)
    if name == "cash-flow":
        return await rep.cash_flow(session, frm, to)
    if name == "dimensions":
        return await rep.dimension_report(session, dimension or "project", frm, to, account_prefix)
    if name == "project-pnl":
        return await rep.project_pnl(session)
    raise NotFoundError("NOT_FOUND", "Laporan tidak dikenal.")


@router.get("/reports/{name}")
async def report(
    name: str,
    _: Reader,
    session: Session,
    format: str = "json",
    as_of: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    account: str | None = None,
    project_id: uuid.UUID | None = None,
    dimension: str | None = None,
    account_prefix: str | None = None,
) -> Any:
    r = await _build(
        session,
        name,
        as_of=as_of,
        date_from=date_from,
        date_to=date_to,
        account=account,
        project_id=project_id,
        dimension=dimension,
        account_prefix=account_prefix,
    )
    stamp = f"{name}-{today_jakarta():%Y%m%d}"
    if format == "xlsx":
        data = build_xlsx(name[:31], r.columns, r.rows)
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{stamp}.xlsx"'},
        )
    if format == "pdf":
        company = {
            **settings_store.DEFAULT_COMPANY,
            **(await settings_store.get(session, settings_store.COMPANY, {}) or {}),
        }
        return StreamingResponse(
            io.BytesIO(rep.to_pdf(r, str(company.get("legal_name")))),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{stamp}.pdf"'},
        )
    return {
        "title": r.title,
        "columns": [{"header": c.header, "key": c.key, "kind": c.kind} for c in r.columns],
        "rows": [{k: _json(v) for k, v in row.items()} for row in r.rows],
        "summary": {k: _json(v) for k, v in r.summary.items()},
    }


@router.get("/accounts")
async def accounts(_: Reader, session: Session) -> list[dict[str, Any]]:
    rows = await session.execute(select(Account).where(Account.is_active).order_by(Account.code))
    return [
        {"code": a.code, "name": a.name, "type": a.account_type, "postable": a.is_postable}
        for a in rows.scalars()
    ]
