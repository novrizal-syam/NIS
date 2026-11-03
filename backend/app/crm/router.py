import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import ColumnElement, Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import Principal, require, scope_filter
from app.contract.models import Contract
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.core.types import IDR
from app.crm import service, won_service
from app.crm.models import BidDecision, Lead, Opportunity
from app.master.models import Client
from app.project.models import Project
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta
from app.services.storage import Storage, get_storage

router = APIRouter(prefix="/crm", tags=["crm"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("crm", "view"))]
Creator = Annotated[Principal, Depends(require("crm", "create"))]
Editor = Annotated[Principal, Depends(require("crm", "edit"))]
Submitter = Annotated[Principal, Depends(require("crm", "submit"))]
Exporter = Annotated[Principal, Depends(require("crm", "export"))]
Store = Annotated[Storage, Depends(get_storage)]

Source = Literal["civd", "eproc", "invitation", "visit", "referral", "website", "exhibition"]


def _record_checker(model: Any) -> access.Checker:
    async def check(
        session: AsyncSession, principal: Principal, entity_id: str, mode: access.Mode
    ) -> bool:
        try:
            row = await session.get(model, uuid.UUID(entity_id))
        except ValueError:
            return False
        if row is None:
            return False
        return service.may(principal, "view" if mode == "read" else "edit", row.owner_id)

    return check


access.register("lead", _record_checker(Lead))
access.register("opportunity", _record_checker(Opportunity))


# ---------------------------------------------------------------- helpers


async def _names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return dict(rows.tuples().all())


async def _company(
    session: AsyncSession, client_code: str | None, company_name: str | None
) -> tuple[str | None, str]:
    if client_code:
        client = (
            await session.execute(select(Client).where(Client.code == client_code))
        ).scalar_one_or_none()
        if client is None or not client.is_active:
            raise AppError(
                "CLIENT_INVALID", "Klien tidak ditemukan atau tidak aktif.", status_code=422
            )
        return client.code, (company_name or "").strip() or client.name
    name = (company_name or "").strip()
    if len(name) < 2:
        raise AppError(
            "COMPANY_REQUIRED",
            "Pilih klien dari data master atau isi nama perusahaan.",
            status_code=422,
        )
    return None, name


def _search(q: str | None, *cols: Any) -> ColumnElement[bool] | None:
    if not q or not q.strip():
        return None
    like = f"%{q.strip()}%"
    return or_(*(c.ilike(like) for c in cols))


async def _get_lead(session: AsyncSession, principal: Principal, lead_id: uuid.UUID) -> Lead:
    lead = await session.get(Lead, lead_id, with_for_update=True)
    if lead is None:
        raise NotFoundError("NOT_FOUND", "Lead tidak ditemukan.")
    service.ensure(principal, "view", lead.owner_id, "lead")
    return lead


async def _get_opp(session: AsyncSession, principal: Principal, opp_id: uuid.UUID) -> Opportunity:
    opp = await session.get(Opportunity, opp_id, with_for_update=True)
    if opp is None:
        raise NotFoundError("NOT_FOUND", "Opportunity tidak ditemukan.")
    service.ensure(principal, "view", opp.owner_id, "opportunity")
    return opp


# ---------------------------------------------------------------- schemas


class LeadOut(BaseModel):
    id: uuid.UUID
    number: str
    client_code: str | None
    company_name: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    source: str
    need: str
    estimated_value: IDR | None
    status: str
    disqualify_reason: str | None
    qualification: dict[str, bool]
    qualification_count: int
    owner_id: uuid.UUID
    owner_name: str | None
    opportunity_id: uuid.UUID | None
    opportunity_number: str | None
    created_at: datetime
    status_changed_at: datetime | None
    is_demo: bool


class OpportunityOut(BaseModel):
    id: uuid.UUID
    number: str
    lead_id: uuid.UUID | None
    lead_number: str | None
    client_code: str | None
    company_name: str
    title: str
    owner_id: uuid.UUID
    owner_name: str | None
    value: IDR
    weighted_value: IDR
    probability: int
    expected_close: date | None
    is_tender: bool
    stage: str
    bid_status: str
    lost_reason: str | None
    winner_price: IDR | None
    stage_changed_at: datetime | None
    won_at: date | None
    lost_at: date | None
    created_at: datetime
    is_demo: bool


def _weighted(value: Decimal, probability: int) -> Decimal:
    return (value * probability / 100).quantize(Decimal(1))


async def _lead_rows(session: AsyncSession, leads: list[Lead]) -> list[LeadOut]:
    names = await _names(session, {x.owner_id for x in leads})
    opps: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    if leads:
        rows = await session.execute(
            select(Opportunity.lead_id, Opportunity.id, Opportunity.number).where(
                Opportunity.lead_id.in_([x.id for x in leads])
            )
        )
        opps = {lid: (oid, num) for lid, oid, num in rows.tuples().all() if lid}
    out = []
    for x in leads:
        opp = opps.get(x.id)
        out.append(
            LeadOut(
                id=x.id,
                number=x.number,
                client_code=x.client_code,
                company_name=x.company_name,
                contact_name=x.contact_name,
                contact_email=x.contact_email,
                contact_phone=x.contact_phone,
                source=x.source,
                need=x.need,
                estimated_value=x.estimated_value,
                status=x.status,
                disqualify_reason=x.disqualify_reason,
                qualification={k: bool(x.qualification.get(k)) for k in service.QUALIFICATION},
                qualification_count=service.qualification_count(x.qualification),
                owner_id=x.owner_id,
                owner_name=names.get(x.owner_id),
                opportunity_id=opp[0] if opp else None,
                opportunity_number=opp[1] if opp else None,
                created_at=x.created_at,
                status_changed_at=x.status_changed_at,
                is_demo=x.is_demo,
            )
        )
    return out


async def _opp_rows(session: AsyncSession, opps: list[Opportunity]) -> list[OpportunityOut]:
    names = await _names(session, {x.owner_id for x in opps})
    lead_ids = [x.lead_id for x in opps if x.lead_id]
    leads: dict[uuid.UUID, str] = {}
    if lead_ids:
        rows = await session.execute(select(Lead.id, Lead.number).where(Lead.id.in_(lead_ids)))
        leads = dict(rows.tuples().all())
    return [
        OpportunityOut(
            id=x.id,
            number=x.number,
            lead_id=x.lead_id,
            lead_number=leads.get(x.lead_id) if x.lead_id else None,
            client_code=x.client_code,
            company_name=x.company_name,
            title=x.title,
            owner_id=x.owner_id,
            owner_name=names.get(x.owner_id),
            value=x.value,
            weighted_value=_weighted(x.value, x.probability),
            probability=x.probability,
            expected_close=x.expected_close,
            is_tender=x.is_tender,
            stage=x.stage,
            bid_status=x.bid_status,
            lost_reason=x.lost_reason,
            winner_price=x.winner_price,
            stage_changed_at=x.stage_changed_at,
            won_at=x.won_at,
            lost_at=x.lost_at,
            created_at=x.created_at,
            is_demo=x.is_demo,
        )
        for x in opps
    ]


# ---------------------------------------------------------------- reference data


@router.get("/config")
async def crm_config(_: Viewer, session: Session) -> dict[str, Any]:
    cfg = await service.config(session)
    return {
        "sources": list(service.SOURCES),
        "qualification": list(service.QUALIFICATION),
        "min_qualified": service.MIN_QUALIFIED,
        "scores": list(service.SCORES),
        "bid_threshold": str(cfg.bid_threshold),
        "win_rate_target": str(cfg.win_rate_target),
        "contract_target": format(cfg.contract_target, "f"),
    }


@router.get("/owners")
async def owners(_: Viewer, session: Session) -> list[dict[str, Any]]:
    return [
        {"id": str(u["id"]), "full_name": u["full_name"]} for u in await service.owners(session)
    ]


# ---------------------------------------------------------------- leads


def _lead_query(
    principal: Principal,
    action: str,
    status: str | None,
    source: str | None,
    q: str | None,
    mine: bool,
) -> Select[tuple[Lead]]:
    stmt = select(Lead).where(scope_filter(principal, "crm", action, owner_col=Lead.owner_id))
    if status:
        stmt = stmt.where(Lead.status == status)
    if source:
        stmt = stmt.where(Lead.source == source)
    if mine:
        stmt = stmt.where(Lead.owner_id == principal.id)
    cond = _search(q, Lead.number, Lead.company_name, Lead.contact_name, Lead.need)
    if cond is not None:
        stmt = stmt.where(cond)
    return stmt


@router.get("/leads")
async def list_leads(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    status: str | None = None,
    source: str | None = None,
    q: str | None = None,
    mine: bool = False,
) -> dict[str, Any]:
    base = _lead_query(principal, "view", None, source, q, mine).subquery()
    counts_rows = await session.execute(select(base.c.status, func.count()).group_by(base.c.status))
    counts = {s: 0 for s in service.LEAD_STATUSES}
    counts.update(dict(counts_rows.tuples().all()))
    stmt = _lead_query(principal, "view", status, source, q, mine)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Lead.created_at.desc()).offset(paging.offset).limit(paging.page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": await _lead_rows(session, list(rows)),
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
        "counts": counts,
    }


@router.get("/leads/export")
async def export_leads(
    principal: Exporter,
    session: Session,
    status: str | None = None,
    source: str | None = None,
    q: str | None = None,
    mine: bool = False,
) -> StreamingResponse:
    stmt = _lead_query(principal, "export", status, source, q, mine).order_by(
        Lead.created_at.desc()
    )
    rows = await _lead_rows(session, list((await session.execute(stmt)).scalars().all()))
    columns = [
        Column("Nomor", "number", width=14),
        Column("Perusahaan", "company_name", width=32),
        Column("Kontak", "contact_name", width=22),
        Column("Sumber", "source", width=14),
        Column("Kebutuhan", "need", width=40),
        Column("Estimasi nilai", "estimated_value", "idr"),
        Column("Status", "status_label", width=16),
        Column("Kriteria terpenuhi", "qualification_count", "number", width=10),
        Column("Pemilik", "owner_name", width=22),
        Column("Opportunity", "opportunity_number", width=14),
        Column("Dibuat", "created_at", "datetime"),
    ]
    return xlsx_response(
        f"lead-{today_jakarta():%Y%m%d}.xlsx",
        "Lead",
        columns,
        ({**r.model_dump(), "status_label": service.LEAD_LABELS[r.status]} for r in rows),
    )


class LeadIn(BaseModel):
    client_code: str | None = Field(default=None, max_length=20)
    company_name: str | None = Field(default=None, max_length=200)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=40)
    source: Source
    need: str = Field(min_length=5, max_length=4000)
    estimated_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    owner_id: uuid.UUID | None = None

    @field_validator("contact_email", mode="before")
    @classmethod
    def _blank_email(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


@router.post("/leads", status_code=201)
async def create_lead(body: LeadIn, actor: Creator, session: Session) -> LeadOut:
    client_code, company = await _company(session, body.client_code, body.company_name)
    owner = await service.check_owner(session, actor, body.owner_id)
    lead = await service.create_lead(
        session,
        actor,
        {
            "client_code": client_code,
            "company_name": company,
            "contact_name": body.contact_name,
            "contact_email": body.contact_email,
            "contact_phone": body.contact_phone,
            "source": body.source,
            "need": body.need.strip(),
            "estimated_value": body.estimated_value,
            "owner_id": owner,
        },
    )
    await session.commit()
    return (await _lead_rows(session, [lead]))[0]


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: uuid.UUID, principal: Viewer, session: Session) -> LeadOut:
    lead = await _get_lead(session, principal, lead_id)
    return (await _lead_rows(session, [lead]))[0]


class LeadUpdate(BaseModel):
    client_code: str | None = Field(default=None, max_length=20)
    company_name: str | None = Field(default=None, max_length=200)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=40)
    source: Source | None = None
    need: str | None = Field(default=None, min_length=5, max_length=4000)
    estimated_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    qualification: dict[str, bool] | None = None
    owner_id: uuid.UUID | None = None

    @field_validator("contact_email", mode="before")
    @classmethod
    def _blank_email(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v


@router.patch("/leads/{lead_id}")
async def update_lead(
    lead_id: uuid.UUID, body: LeadUpdate, actor: Editor, session: Session
) -> LeadOut:
    lead = await _get_lead(session, actor, lead_id)
    service.ensure(actor, "edit", lead.owner_id, "lead")
    changes = body.model_dump(exclude_unset=True)
    if "client_code" in changes or "company_name" in changes:
        changes["client_code"], changes["company_name"] = await _company(
            session,
            changes.get("client_code", lead.client_code),
            changes.get("company_name", lead.company_name),
        )
    if "qualification" in changes:
        changes["qualification"] = service.clean_qualification(changes["qualification"] or {})
    if "owner_id" in changes:
        changes["owner_id"] = await service.check_owner(session, actor, changes["owner_id"])
    if changes.get("source") is None:
        changes.pop("source", None)
    if changes.get("need") is None:
        changes.pop("need", None)
    else:
        changes["need"] = changes["need"].strip()
    await service.update_lead(session, actor, lead, changes)
    await session.commit()
    return (await _lead_rows(session, [lead]))[0]


class LeadStatusIn(BaseModel):
    to: Literal["contacted", "qualified", "disqualified"]
    reason: str | None = Field(default=None, max_length=500)


@router.post("/leads/{lead_id}/status")
async def lead_status(
    lead_id: uuid.UUID, body: LeadStatusIn, actor: Editor, session: Session
) -> LeadOut:
    lead = await _get_lead(session, actor, lead_id)
    service.ensure(actor, "edit", lead.owner_id, "lead")
    await service.transition_lead(session, actor, lead, body.to, body.reason)
    await session.commit()
    return (await _lead_rows(session, [lead]))[0]


class ConvertIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close: date | None = None
    is_tender: bool = False


@router.post("/leads/{lead_id}/convert", status_code=201)
async def convert_lead(
    lead_id: uuid.UUID, body: ConvertIn, actor: Creator, session: Session
) -> OpportunityOut:
    lead = await _get_lead(session, actor, lead_id)
    service.ensure(actor, "edit", lead.owner_id, "lead")
    opp = await service.convert(session, actor, lead, body.model_dump())
    await session.commit()
    return (await _opp_rows(session, [opp]))[0]


# ---------------------------------------------------------------- opportunities


def _opp_query(
    principal: Principal, action: str, stage: str | None, q: str | None, mine: bool
) -> Select[tuple[Opportunity]]:
    stmt = select(Opportunity).where(
        scope_filter(principal, "crm", action, owner_col=Opportunity.owner_id)
    )
    if stage == "open":
        stmt = stmt.where(Opportunity.stage.in_(service.OPEN_STAGES))
    elif stage:
        stmt = stmt.where(Opportunity.stage == stage)
    if mine:
        stmt = stmt.where(Opportunity.owner_id == principal.id)
    cond = _search(q, Opportunity.number, Opportunity.title, Opportunity.company_name)
    if cond is not None:
        stmt = stmt.where(cond)
    return stmt


@router.get("/opportunities")
async def list_opportunities(
    principal: Viewer,
    session: Session,
    paging: Annotated[PageParams, Depends(page_params)],
    stage: str | None = None,
    q: str | None = None,
    mine: bool = False,
) -> dict[str, Any]:
    base = _opp_query(principal, "view", None, q, mine).subquery()
    summary_rows = await session.execute(
        select(base.c.stage, func.count(), func.coalesce(func.sum(base.c.value), 0)).group_by(
            base.c.stage
        )
    )
    summary = {s: {"count": 0, "value": "0"} for s in service.STAGES}
    for st, n, v in summary_rows.tuples().all():
        summary[st] = {"count": n, "value": format(Decimal(v).quantize(Decimal(1)), "f")}
    stmt = _opp_query(principal, "view", stage, q, mine)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Opportunity.stage_changed_at.desc().nulls_last(), Opportunity.number)
                .offset(paging.offset)
                .limit(paging.page_size)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": await _opp_rows(session, list(rows)),
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
        "summary": summary,
    }


@router.get("/opportunities/export")
async def export_opportunities(
    principal: Exporter,
    session: Session,
    stage: str | None = None,
    q: str | None = None,
    mine: bool = False,
) -> StreamingResponse:
    stmt = _opp_query(principal, "export", stage, q, mine).order_by(Opportunity.number)
    rows = await _opp_rows(session, list((await session.execute(stmt)).scalars().all()))
    columns = [
        Column("Nomor", "number", width=14),
        Column("Judul", "title", width=36),
        Column("Perusahaan", "company_name", width=30),
        Column("Tahap", "stage_label", width=12),
        Column("Nilai", "value", "idr"),
        Column("Probabilitas (%)", "probability", "number", width=10),
        Column("Nilai tertimbang", "weighted_value", "idr"),
        Column("Perkiraan closing", "expected_close", "date"),
        Column("Tender", "tender", width=8),
        Column("Pemilik", "owner_name", width=22),
        Column("Alasan kalah", "lost_reason", width=36),
    ]
    return xlsx_response(
        f"opportunity-{today_jakarta():%Y%m%d}.xlsx",
        "Opportunity",
        columns,
        (
            {
                **r.model_dump(),
                "stage_label": service.STAGE_LABELS[r.stage],
                "tender": "Ya" if r.is_tender else "Tidak",
            }
            for r in rows
        ),
    )


@router.get("/opportunities/{opp_id}")
async def get_opportunity(opp_id: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    opp = await _get_opp(session, principal, opp_id)
    decisions = (
        (
            await session.execute(
                select(BidDecision)
                .where(BidDecision.opportunity_id == opp.id)
                .order_by(BidDecision.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    names = await _names(session, {d.created_by for d in decisions if d.created_by})
    row = (await _opp_rows(session, [opp]))[0]
    return {
        **row.model_dump(mode="json"),
        "contract": await _linked(session, Contract, opp.id),
        "project": await _linked_project(session, opp.id),
        "can_edit": service.may(principal, "edit", opp.owner_id),
        "can_submit": service.may(principal, "submit", opp.owner_id),
        "bid_decisions": [
            {
                "id": str(d.id),
                "scores": d.scores,
                "percent": str(d.percent),
                "threshold": str(d.threshold),
                "recommendation": d.recommendation,
                "proposal": d.proposal,
                "note": d.note,
                "status": d.status,
                "request_id": str(d.request_id) if d.request_id else None,
                "decision_comment": d.decision_comment,
                "decided_at": d.decided_at.isoformat() if d.decided_at else None,
                "created_at": d.created_at.isoformat(),
                "created_by_name": names.get(d.created_by) if d.created_by else None,
            }
            for d in decisions
        ],
    }


class OpportunityUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close: date | None = None
    is_tender: bool | None = None
    owner_id: uuid.UUID | None = None


@router.patch("/opportunities/{opp_id}")
async def update_opportunity(
    opp_id: uuid.UUID, body: OpportunityUpdate, actor: Editor, session: Session
) -> OpportunityOut:
    opp = await _get_opp(session, actor, opp_id)
    service.ensure(actor, "edit", opp.owner_id, "opportunity")
    changes = body.model_dump(exclude_unset=True)
    for key in ("title", "value", "probability", "is_tender"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    if "owner_id" in changes:
        changes["owner_id"] = await service.check_owner(session, actor, changes["owner_id"])
    await service.update_opportunity(session, actor, opp, changes)
    await session.commit()
    return (await _opp_rows(session, [opp]))[0]


class StageIn(BaseModel):
    to: Literal["qualified", "quotation", "submitted", "won", "lost"]
    reason: str | None = Field(default=None, max_length=500)
    winner_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=0)


@router.post("/opportunities/{opp_id}/stage")
async def opportunity_stage(
    opp_id: uuid.UUID, body: StageIn, actor: Editor, session: Session
) -> OpportunityOut:
    opp = await _get_opp(session, actor, opp_id)
    service.ensure(actor, "edit", opp.owner_id, "opportunity")
    await service.move_stage(session, actor, opp, body.to, body.reason, body.winner_price)
    await session.commit()
    return (await _opp_rows(session, [opp]))[0]


class WonIn(BaseModel):
    po_number: str | None = Field(default=None, max_length=60)
    start_date: date | None = None
    end_date: date | None = None
    payment_term_days: int | None = Field(default=None, ge=0, le=365)


@router.post("/opportunities/{opp_id}/won")
async def opportunity_won(
    opp_id: uuid.UUID, body: WonIn, actor: Editor, session: Session, storage: Store
) -> dict[str, Any]:
    """'Tandai Menang': contract + draft project + project documents in one transaction."""
    opp = await _get_opp(session, actor, opp_id)
    service.ensure(actor, "edit", opp.owner_id, "opportunity")
    result = await won_service.mark_won(
        session,
        storage,
        actor,
        opp,
        po_number=(body.po_number or "").strip() or None,
        start_date=body.start_date,
        end_date=body.end_date,
        payment_term_days=body.payment_term_days,
    )
    await session.commit()
    return {
        "contract_id": str(result.contract.id),
        "contract_number": result.contract.number,
        "project_id": str(result.project.id),
        "project_number": result.project.number,
        "documents": result.documents,
    }


class BidDecisionIn(BaseModel):
    scores: dict[str, int]
    proposal: Literal["bid", "no_bid"]
    note: str | None = Field(default=None, max_length=1000)


@router.post("/opportunities/{opp_id}/bid-decision", status_code=201)
async def bid_decision(
    opp_id: uuid.UUID, body: BidDecisionIn, actor: Submitter, session: Session
) -> dict[str, Any]:
    opp = await _get_opp(session, actor, opp_id)
    service.ensure(actor, "submit", opp.owner_id, "opportunity")
    decision = await service.submit_bid_decision(
        session, actor, opp, scores=body.scores, proposal=body.proposal, note=body.note
    )
    await session.commit()
    return {
        "id": str(decision.id),
        "request_id": str(decision.request_id),
        "percent": str(decision.percent),
        "recommendation": decision.recommendation,
    }


async def _linked(session: AsyncSession, model: Any, opp_id: uuid.UUID) -> dict[str, str] | None:
    row = (
        await session.execute(select(model.id, model.number).where(model.opportunity_id == opp_id))
    ).first()
    return {"id": str(row[0]), "number": row[1]} if row else None


async def _linked_project(session: AsyncSession, opp_id: uuid.UUID) -> dict[str, str] | None:
    row = (
        await session.execute(
            select(Project.id, Project.number)
            .join(Contract, Contract.id == Project.contract_id)
            .where(Contract.opportunity_id == opp_id)
        )
    ).first()
    return {"id": str(row[0]), "number": row[1]} if row else None


# ---------------------------------------------------------------- dashboard


@router.get("/dashboard")
async def dashboard(principal: Viewer, session: Session) -> dict[str, Any]:
    """Sales tiles: open pipeline, weighted pipeline, win rate YTD vs target, new contract
    value YTD vs target. Limited to the user's data scope."""
    cfg = await service.config(session)
    today = today_jakarta()
    start = service.year_start(today)
    scope = scope_filter(principal, "crm", "view", owner_col=Opportunity.owner_id)
    is_open = Opportunity.stage.in_(service.OPEN_STAGES)
    won_ytd = and_(Opportunity.stage == "won", Opportunity.won_at >= start)
    lost_ytd = and_(Opportunity.stage == "lost", Opportunity.lost_at >= start)
    zero = Decimal(0)
    row = (
        await session.execute(
            select(
                func.count().filter(is_open),
                func.coalesce(func.sum(Opportunity.value).filter(is_open), zero),
                func.coalesce(
                    func.sum(Opportunity.value * Opportunity.probability / 100).filter(is_open),
                    zero,
                ),
                func.count().filter(won_ytd),
                func.count().filter(lost_ytd),
                func.coalesce(func.sum(case((won_ytd, Opportunity.value), else_=zero)), zero),
            ).where(scope)
        )
    ).one()
    open_n, open_value, weighted, won_n, lost_n, won_value = row
    decided = won_n + lost_n
    win_rate = (
        (Decimal(won_n) / Decimal(decided) * 100).quantize(Decimal("0.1")) if decided else None
    )

    def idr(v: Any) -> str:
        return format(Decimal(v).quantize(Decimal(1)), "f")

    return {
        "year": today.year,
        "open_count": open_n,
        "open_pipeline": idr(open_value),
        "weighted_pipeline": idr(weighted),
        "won_count": won_n,
        "lost_count": lost_n,
        "win_rate": str(win_rate) if win_rate is not None else None,
        "win_rate_target": str(cfg.win_rate_target),
        "new_contract_value": idr(won_value),
        "contract_target": idr(cfg.contract_target),
        "scope": "all" if principal.scope_for("crm", "view") == "all" else "own",
    }
