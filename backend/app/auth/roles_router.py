"""Roles & permissions (Settings): system roles keep their code but their permissions are
editable; custom roles can be created, cloned and deactivated. Changes apply on the next
request because permissions are loaded per request."""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, RolePermission, UserRole
from app.auth.permissions import (
    ACTION_LABELS,
    MODULES,
    SENSITIVE_FIELDS,
    SENSITIVE_MODULE,
    Action,
    Scope,
    is_valid_grant,
)
from app.auth.principal import CurrentUser, Principal, require
from app.core.db import get_session
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.services import audit
from app.services.audit import AuditAction

router = APIRouter(prefix="/roles", tags=["roles"])
Session = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[Principal, Depends(require("users", "admin"))]
Viewer = Annotated[Principal, Depends(require("users", "view"))]
LOCKED_ROLES = {"super_admin"}  # full access by definition; not editable


def _role_out(r: Role, users: int) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "code": r.code,
        "name": r.name,
        "description": r.description,
        "is_system": r.is_system,
        "is_external": r.is_external,
        "requires_2fa": r.requires_2fa,
        "is_active": r.is_active,
        "user_count": users,
        "locked": r.code in LOCKED_ROLES,
    }


async def _counts(session: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(UserRole.role_id, func.count())
        .where(UserRole.active_now())
        .group_by(UserRole.role_id)
    )
    return dict(rows.tuples().all())


async def _get(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await session.get(Role, role_id)
    if role is None:
        raise NotFoundError("ROLE_NOT_FOUND", "Peran tidak ditemukan.")
    return role


async def _grants(session: AsyncSession, role_id: uuid.UUID) -> list[dict[str, str]]:
    rows = await session.execute(
        select(RolePermission)
        .where(RolePermission.role_id == role_id)
        .order_by(RolePermission.module, RolePermission.action)
    )
    return [{"module": p.module, "action": p.action, "scope": p.scope} for p in rows.scalars()]


@router.get("")
async def list_roles(_: CurrentUser, session: Session) -> list[dict[str, Any]]:
    counts = await _counts(session)
    rows = (
        await session.execute(select(Role).order_by(Role.is_system.desc(), Role.name))
    ).scalars()
    return [_role_out(r, counts.get(r.id, 0)) for r in rows]


@router.get("/catalog")
async def catalog(_: Viewer) -> dict[str, Any]:
    return {
        "modules": [{"code": c, "label": lbl} for c, lbl in MODULES.items()],
        "actions": [{"code": str(a), "label": ACTION_LABELS[a]} for a in Action],
        "scopes": [str(s) for s in Scope],
        "sensitive": [{"code": c, "label": lbl} for c, lbl in SENSITIVE_FIELDS.items()],
    }


@router.get("/{role_id}")
async def role_detail(role_id: uuid.UUID, _: Viewer, session: Session) -> dict[str, Any]:
    role = await _get(session, role_id)
    counts = await _counts(session)
    return {**_role_out(role, counts.get(role.id, 0)), "grants": await _grants(session, role.id)}


class RoleIn(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=500)
    requires_2fa: bool = False
    clone_from: uuid.UUID | None = None


@router.post("", status_code=201)
async def create_role(body: RoleIn, actor: Admin, session: Session) -> dict[str, Any]:
    code = body.code.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,49}", code):
        raise AppError(
            "INVALID_CODE",
            "Kode peran: huruf kecil, angka, dan garis bawah; diawali huruf.",
            status_code=422,
        )
    if (await session.execute(select(Role.id).where(Role.code == code))).first():
        raise ConflictError("ROLE_EXISTS", f"Peran dengan kode {code} sudah ada.")
    role = Role(
        code=code,
        name=body.name.strip(),
        description=body.description,
        requires_2fa=body.requires_2fa,
        is_system=False,
        created_by=actor.id,
    )
    session.add(role)
    await session.flush()
    if body.clone_from:
        source = await _get(session, body.clone_from)
        for g in await _grants(session, source.id):
            session.add(RolePermission(role_id=role.id, **g))
        await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type="role",
        entity_id=role.id,
        actor_id=actor.id,
        after={
            "code": code,
            "name": role.name,
            "cloned_from": str(body.clone_from) if body.clone_from else None,
        },
    )
    await session.commit()
    return _role_out(role, 0)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    requires_2fa: bool | None = None
    is_active: bool | None = None


@router.patch("/{role_id}")
async def update_role(
    role_id: uuid.UUID, body: RoleUpdate, actor: Admin, session: Session
) -> dict[str, Any]:
    role = await _get(session, role_id)
    if body.is_active is False and role.is_system:
        raise ForbiddenError("SYSTEM_ROLE", "Peran sistem tidak dapat dinonaktifkan atau dihapus.")
    before = _role_out(role, 0)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(role, k, v)
    await session.flush()
    after = _role_out(role, 0)
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="role",
        entity_id=role.id,
        actor_id=actor.id,
        before=before,
        after=after,
    )
    await session.commit()
    return _role_out(role, (await _counts(session)).get(role.id, 0))


class Grant(BaseModel):
    module: str
    action: str
    scope: Scope


class GrantsIn(BaseModel):
    grants: list[Grant]


@router.put("/{role_id}/permissions")
async def set_permissions(
    role_id: uuid.UUID, body: GrantsIn, actor: Admin, session: Session
) -> dict[str, Any]:
    role = await _get(session, role_id)
    if role.code in LOCKED_ROLES:
        raise ForbiddenError("ROLE_LOCKED", "Izin Super Admin tidak dapat diubah.")
    seen: set[tuple[str, str]] = set()
    for g in body.grants:
        if not is_valid_grant(g.module, g.action):
            raise AppError(
                "INVALID_GRANT", f"Izin tidak dikenal: {g.module}.{g.action}.", status_code=422
            )
        if (g.module, g.action) in seen:
            raise AppError(
                "DUPLICATE_GRANT", f"Izin ganda: {g.module}.{g.action}.", status_code=422
            )
        seen.add((g.module, g.action))
    before = await _grants(session, role.id)
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    session.add_all(
        RolePermission(role_id=role.id, module=g.module, action=g.action, scope=str(g.scope))
        for g in body.grants
    )
    await session.flush()
    after = await _grants(session, role.id)
    b = {f"{g['module']}.{g['action']}": g["scope"] for g in before}
    a = {f"{g['module']}.{g['action']}": g["scope"] for g in after}
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="role",
        entity_id=role.id,
        actor_id=actor.id,
        before={k: b[k] for k in sorted(set(b) | set(a)) if b.get(k) != a.get(k) and k in b},
        after={k: a[k] for k in sorted(set(b) | set(a)) if b.get(k) != a.get(k) and k in a},
        note="Izin peran diubah",
    )
    await session.commit()
    return {"grants": after}


@router.get("/{role_id}/preview")
async def view_as(role_id: uuid.UUID, actor: Admin, session: Session) -> dict[str, Any]:
    """Read-only 'View as role': what this role can open and do. No session is created."""
    role = await _get(session, role_id)
    grants = await _grants(session, role.id)
    tree: dict[str, dict[str, str]] = {}
    for g in grants:
        tree.setdefault(g["module"], {})[g["action"]] = g["scope"]
    await audit.record(
        session,
        action="view_as",
        entity_type="role",
        entity_id=role.id,
        actor_id=actor.id,
        after={"role": role.code},
    )
    await session.commit()
    return {
        "role": _role_out(role, 0),
        "permissions": tree,
        "sensitive": sorted(
            a for (m, a) in ((g["module"], g["action"]) for g in grants) if m == SENSITIVE_MODULE
        ),
    }


# --- temporary assignments ---------------------------------------------------------------------


async def expire_temporary_roles(session: AsyncSession) -> int:
    """Job: remove assignments whose valid_until has passed (audited)."""
    rows = (
        await session.execute(
            select(UserRole, Role.code)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.valid_until.is_not(None), UserRole.valid_until <= func.now())
        )
    ).all()
    for ur, code in rows:
        await session.delete(ur)
        await audit.record(
            session,
            action="role_expired",
            entity_type="user",
            entity_id=ur.user_id,
            actor_id=None,
            before={"role": code, "valid_until": ur.valid_until},
        )
    await session.flush()
    return len(rows)


def now() -> datetime:
    return datetime.now(UTC)
