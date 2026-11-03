import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, User
from app.auth.principal import CurrentUser, Principal, require
from app.core.db import get_session
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.services import audit
from app.services.audit import AuditAction
from app.sod import service
from app.sod.models import SodException, SodRule
from app.sod.seed import norm
from app.workflow.models import ApprovalRequest

router = APIRouter(prefix="/sod", tags=["sod"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("users", "view"))]
Admin = Annotated[Principal, Depends(require("users", "admin"))]


def _register_reader(principal: CurrentUser) -> Principal:
    # User admins and auditors (Lead Controller reviews monthly) may read the register.
    if not (principal.can("users", "view") or principal.can("audit", "view")):
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak memiliki izin melihat register SoD.")
    return principal


Reader = Annotated[Principal, Depends(_register_reader)]


@router.get("/rules")
async def rules(_: Reader, session: Session) -> list[dict[str, Any]]:
    names = dict((await session.execute(select(Role.code, Role.name))).tuples().all())
    rows = (
        await session.execute(select(SodRule).order_by(SodRule.role_a, SodRule.role_b))
    ).scalars()
    return [
        {
            "id": str(r.id),
            "role_a": r.role_a,
            "role_b": r.role_b,
            "role_a_name": names.get(r.role_a, r.role_a),
            "role_b_name": names.get(r.role_b, r.role_b),
            "description": r.description,
            "is_active": r.is_active,
        }
        for r in rows
    ]


class RuleIn(BaseModel):
    role_a: str
    role_b: str
    description: str = Field(min_length=5, max_length=300)


@router.post("/rules", status_code=201)
async def add_rule(body: RuleIn, actor: Admin, session: Session) -> dict[str, str]:
    a, b = norm(body.role_a, body.role_b)
    if a == b:
        raise AppError("SAME_ROLE", "Pilih dua peran yang berbeda.", status_code=422)
    known = set((await session.execute(select(Role.code).where(Role.code.in_([a, b])))).scalars())
    if known != {a, b}:
        raise AppError("UNKNOWN_ROLE", "Peran tidak dikenal.", status_code=422)
    if (
        await session.execute(select(SodRule.id).where(SodRule.role_a == a, SodRule.role_b == b))
    ).first():
        raise ConflictError("RULE_EXISTS", "Aturan untuk pasangan peran ini sudah ada.")
    rule = SodRule(role_a=a, role_b=b, description=body.description, created_by=actor.id)
    session.add(rule)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="sod_rule",
        entity_id=rule.id,
        actor_id=actor.id,
        after={"pair": [a, b], "description": body.description},
    )
    await session.commit()
    return {"id": str(rule.id)}


class RuleUpdate(BaseModel):
    is_active: bool


@router.patch("/rules/{rule_id}", status_code=204)
async def update_rule(
    rule_id: uuid.UUID, body: RuleUpdate, actor: Admin, session: Session
) -> Response:
    rule = await session.get(SodRule, rule_id)
    if rule is None:
        raise NotFoundError("NOT_FOUND", "Aturan tidak ditemukan.")
    before = rule.is_active
    rule.is_active = body.is_active
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="sod_rule",
        entity_id=rule.id,
        actor_id=actor.id,
        before={"is_active": before},
        after={"is_active": body.is_active},
    )
    await session.commit()
    return Response(status_code=204)


@router.get("/register")
async def register(_: Reader, session: Session) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(
                SodException,
                User.full_name,
                User.email,
                ApprovalRequest.id,
                ApprovalRequest.doc_number,
            )
            .join(User, User.id == SodException.user_id)
            .outerjoin(
                ApprovalRequest,
                (ApprovalRequest.doc_type == "sod_exception")
                & (ApprovalRequest.doc_id == SodException.id.cast(ApprovalRequest.doc_id.type)),
            )
            .order_by(SodException.created_at.desc())
        )
    ).all()
    seen: set[uuid.UUID] = set()
    exceptions = []
    for e, name, email, rid, number in rows:
        if e.id in seen:
            continue
        seen.add(e.id)
        exceptions.append(
            {
                "id": str(e.id),
                "user_name": name,
                "email": email,
                "pairs": e.pairs,
                "reason": e.reason,
                "status": e.status,
                "created_at": e.created_at,
                "decided_at": e.decided_at,
                "last_reviewed_at": e.last_reviewed_at,
                "review_note": e.review_note,
                "request_id": str(rid) if rid else None,
                "doc_number": number,
            }
        )
    return {"exceptions": exceptions, "violations": await service.violations(session)}


class ReviewIn(BaseModel):
    note: str = Field(default="", max_length=500)


@router.post("/exceptions/{exc_id}/review", status_code=204)
async def review(
    exc_id: uuid.UUID, body: ReviewIn, principal: CurrentUser, session: Session
) -> Response:
    """Monthly review by the Lead Controller (DOA.md); IT admins cannot sign it off."""
    if "lead_controller" not in principal.role_codes:
        raise ForbiddenError(
            "PERMISSION_DENIED", "Peninjauan register SoD dilakukan oleh Lead Controller."
        )
    exc = await session.get(SodException, exc_id)
    if exc is None or exc.status != "approved":
        raise NotFoundError("NOT_FOUND", "Pengecualian aktif tidak ditemukan.")
    exc.last_reviewed_at, exc.last_reviewed_by = datetime.now(UTC), principal.id
    exc.review_note = body.note.strip() or None
    await audit.record(
        session,
        action="sod_review",
        entity_type="sod_exception",
        entity_id=exc.id,
        actor_id=principal.id,
        after={"note": exc.review_note},
    )
    await session.commit()
    return Response(status_code=204)


@router.post("/exceptions/{exc_id}/revoke", status_code=204)
async def revoke(exc_id: uuid.UUID, actor: Admin, session: Session) -> Response:
    """Withdraws the exception; the user then shows up as a violation until a role is removed."""
    exc = await session.get(SodException, exc_id)
    if exc is None or exc.status != "approved":
        raise NotFoundError("NOT_FOUND", "Pengecualian aktif tidak ditemukan.")
    exc.status = "revoked"
    await audit.record(
        session,
        action="revoke",
        entity_type="sod_exception",
        entity_id=exc.id,
        actor_id=actor.id,
        before={"pairs": exc.pairs},
    )
    await session.commit()
    return Response(status_code=204)
