import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import admin
from app.auth.models import Role, User, UserRole
from app.auth.principal import CurrentUser, Principal, require
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError
from app.core.pagination import PageParams, page_params
from app.master.models import Department
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta
from app.setup import service as setup_service

router = APIRouter(prefix="/users", tags=["users"])
access.register("user", access.module_checker("users", "users"))
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("users", "view"))]
Creator = Annotated[Principal, Depends(require("users", "create"))]
Editor = Annotated[Principal, Depends(require("users", "edit"))]
Admin = Annotated[Principal, Depends(require("users", "admin"))]

# Called with (session, actor, user, old_roles, new_roles) before roles change (SoD checks).
ROLE_CHANGE_HOOKS: list[Any] = []


class UserLookup(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


@router.get("/lookup")
async def lookup(
    _: CurrentUser, session: Session, q: Annotated[str, Query(min_length=2, max_length=100)]
) -> list[UserLookup]:
    """Name/email search of active users (for pickers such as delegation)."""
    like = f"%{q.strip()}%"
    rows = await session.execute(
        select(User)
        .where(User.is_active.is_(True), or_(User.full_name.ilike(like), User.email.ilike(like)))
        .order_by(User.full_name)
        .limit(20)
    )
    return [UserLookup(id=u.id, full_name=u.full_name, email=u.email) for u in rows.scalars()]


class UserRow(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    roles: list[str]
    role_names: list[str]
    department_code: str | None
    employee_code: str | None
    status: admin.Status
    totp_enabled: bool
    last_login_at: datetime | None
    is_demo: bool


async def _rows(session: AsyncSession, users: list[User]) -> list[UserRow]:
    ids = [u.id for u in users]
    role_rows = await session.execute(
        select(UserRole.user_id, Role.code, Role.name)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(ids))
    )
    roles: dict[uuid.UUID, list[tuple[str, str]]] = {}
    for uid, code, name in role_rows.all():
        roles.setdefault(uid, []).append((code, name))
    depts = dict((await session.execute(select(Department.id, Department.code))).tuples().all())
    invited = await admin.open_invite_users(session, ids)
    return [
        UserRow(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            roles=sorted(c for c, _ in roles.get(u.id, [])),
            role_names=sorted(n for _, n in roles.get(u.id, [])),
            department_code=depts.get(u.department_id) if u.department_id else None,
            employee_code=u.employee_code,
            status=admin.status_of(u, u.id in invited),
            totp_enabled=u.totp_enabled,
            last_login_at=u.last_login_at,
            is_demo=u.is_demo,
        )
        for u in users
    ]


@router.get("")
async def list_users(
    _: Viewer,
    session: Session,
    pages: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    role: str | None = None,
    status: Literal["invited", "active", "locked", "inactive"] | None = None,
) -> dict[str, Any]:
    stmt = select(User)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like)))
    if role:
        stmt = stmt.where(
            User.id.in_(
                select(UserRole.user_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.code == role)
            )
        )
    users = list((await session.execute(stmt.order_by(User.full_name))).scalars())
    rows = await _rows(session, users)
    counts: dict[str, int] = {"invited": 0, "active": 0, "locked": 0, "inactive": 0}
    for r in rows:
        counts[r.status] += 1
    if status:
        rows = [r for r in rows if r.status == status]
    return {
        "items": rows[pages.offset : pages.offset + pages.page_size],
        "total": len(rows),
        "page": pages.page,
        "page_size": pages.page_size,
        "counts": counts,
        "active_super_admins": len(await setup_service.active_super_admins(session)),
    }


STATUS_LABEL = {
    "invited": "Diundang",
    "active": "Aktif",
    "locked": "Terkunci",
    "inactive": "Nonaktif",
}


@router.get("/export")
async def export(
    _: Annotated[Principal, Depends(require("users", "export"))], session: Session
) -> StreamingResponse:
    rows = await _rows(
        session, list((await session.execute(select(User).order_by(User.full_name))).scalars())
    )
    data = [
        {
            **r.model_dump(),
            "roles": ", ".join(r.role_names),
            "status": STATUS_LABEL[r.status],
            "totp": "Ya" if r.totp_enabled else "Tidak",
        }
        for r in rows
    ]
    cols = [
        Column("Nama", "full_name", width=28),
        Column("Email", "email", width=32),
        Column("Peran", "roles", width=40),
        Column("Departemen", "department_code", width=12),
        Column("Status", "status", width=12),
        Column("2FA", "totp", width=8),
        Column("Login terakhir", "last_login_at", "datetime"),
        Column("Karyawan", "employee_code", width=12),
    ]
    return xlsx_response(f"pengguna-{today_jakarta():%Y%m%d}.xlsx", "Pengguna", cols, data)


class CreateIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=3, max_length=120)
    roles: list[str] = Field(min_length=1)
    department_code: str | None = None
    employee_code: str | None = None
    mode: Literal["invite", "password"] = "invite"


@router.post("", status_code=201)
async def create_user(body: CreateIn, actor: Creator, session: Session) -> dict[str, Any]:
    user, temp = await admin.create(
        session,
        actor,
        email=body.email,
        full_name=body.full_name,
        role_codes_=body.roles,
        department_code=body.department_code,
        employee_code=body.employee_code,
        mode=body.mode,
    )
    await session.commit()
    # The temporary password is returned once and never stored in plain text.
    return {"id": str(user.id), "temporary_password": temp}


@router.post("/import")
async def import_users(
    actor: Creator, session: Session, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", "File impor maksimal 5 MB.", status_code=413)
    report = await admin.import_users(session, actor, file.filename or "users.csv", content)
    if report.errors:
        await session.rollback()
        return {"ok": False, "created": 0, "errors": report.errors[:200]}
    await session.commit()
    return {"ok": True, "created": report.created, "errors": []}


@router.get("/{user_id}")
async def detail(user_id: uuid.UUID, _: Viewer, session: Session) -> dict[str, Any]:
    user = await admin.get_user(session, user_id)
    row = (await _rows(session, [user]))[0]
    assignments = await session.execute(
        select(Role.code, Role.name, UserRole.valid_from, UserRole.valid_until, UserRole.reason)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user.id)
        .order_by(Role.name)
    )
    return {
        **row.model_dump(),
        "sessions": await admin.sessions(session, user.id),
        "assignments": [
            {"code": c, "name": n, "valid_from": f, "valid_until": u, "reason": r}
            for c, n, f, u, r in assignments.all()
        ],
    }


class UpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=3, max_length=120)
    department_code: str | None = None
    employee_code: str | None = None
    roles: list[str] | None = Field(default=None, min_length=1)


@router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID, body: UpdateIn, actor: Editor, session: Session
) -> dict[str, Any]:
    user = await admin.get_user(session, user_id)
    fields = body.model_fields_set
    await admin.update_profile(
        session,
        actor,
        user,
        full_name=body.full_name,
        department_code=body.department_code,
        employee_code=body.employee_code,
        fields_set=fields,
    )
    if body.roles is not None:
        hook = ROLE_CHANGE_HOOKS[0] if ROLE_CHANGE_HOOKS else None
        await admin.set_roles(session, actor, user, body.roles, hook)
    await session.commit()
    return (await _rows(session, [user]))[0].model_dump(mode="json")


async def _action(
    session: AsyncSession, user_id: uuid.UUID, fn: Any, actor: Principal, *args: Any
) -> Any:
    user = await admin.get_user(session, user_id)
    result = await fn(session, actor, user, *args)
    await session.commit()
    return result


@router.post("/{user_id}/deactivate", status_code=204)
async def deactivate(user_id: uuid.UUID, actor: Admin, session: Session) -> Response:
    await _action(session, user_id, admin.set_active, actor, False)
    return Response(status_code=204)


@router.post("/{user_id}/activate", status_code=204)
async def activate(user_id: uuid.UUID, actor: Admin, session: Session) -> Response:
    await _action(session, user_id, admin.set_active, actor, True)
    return Response(status_code=204)


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: uuid.UUID, actor: Admin, session: Session) -> dict[str, str]:
    return {"temporary_password": await _action(session, user_id, admin.reset_password, actor)}


@router.post("/{user_id}/unlock", status_code=204)
async def unlock(user_id: uuid.UUID, actor: Admin, session: Session) -> Response:
    await _action(session, user_id, admin.unlock, actor)
    return Response(status_code=204)


@router.post("/{user_id}/reset-2fa", status_code=204)
async def reset_2fa(user_id: uuid.UUID, actor: Admin, session: Session) -> Response:
    await _action(session, user_id, admin.reset_2fa, actor)
    return Response(status_code=204)


@router.post("/{user_id}/force-logout", status_code=204)
async def force_logout(user_id: uuid.UUID, actor: Admin, session: Session) -> Response:
    await _action(session, user_id, admin.force_logout, actor)
    return Response(status_code=204)


@router.post("/{user_id}/invite", status_code=204)
async def resend_invite(user_id: uuid.UUID, actor: Creator, session: Session) -> Response:
    user = await admin.get_user(session, user_id)
    if user.last_login_at is not None:
        raise AppError(
            "ALREADY_ACTIVE",
            "Pengguna sudah pernah masuk; gunakan reset kata sandi.",
            status_code=409,
        )
    await admin.create_invite(session, actor.id, user)
    await session.commit()
    return Response(status_code=204)


class TemporaryRoleIn(BaseModel):
    role: str
    valid_from: datetime | None = None
    valid_until: datetime
    reason: str = Field(min_length=5, max_length=300)


@router.post("/{user_id}/roles/temporary", status_code=201)
async def add_temporary_role(
    user_id: uuid.UUID, body: TemporaryRoleIn, actor: Editor, session: Session
) -> dict[str, str]:
    user = await admin.get_user(session, user_id)
    hook = ROLE_CHANGE_HOOKS[0] if ROLE_CHANGE_HOOKS else None
    await admin.add_temporary_role(
        session,
        actor,
        user,
        code=body.role,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        reason=body.reason,
        hook=hook,
    )
    await session.commit()
    return {"status": "ok"}


@router.post("/{user_id}/sessions/{family_id}/revoke", status_code=204)
async def revoke_session(
    user_id: uuid.UUID, family_id: uuid.UUID, actor: Admin, session: Session
) -> Response:
    await _action(session, user_id, admin.revoke_session, actor, family_id)
    return Response(status_code=204)


@router.get("/-/count-by-role")
async def count_by_role(_: Viewer, session: Session) -> dict[str, int]:
    rows = await session.execute(
        select(Role.code, func.count(UserRole.user_id))
        .outerjoin(UserRole, UserRole.role_id == Role.id)
        .group_by(Role.code)
    )
    return dict(rows.tuples().all())
