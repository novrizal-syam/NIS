"""The authenticated user for one request, their effective permissions, and FastAPI deps."""

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy import ColumnElement, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, RolePermission, User, UserRole
from app.auth.permissions import (
    ACTION_LABELS,
    MODULES,
    SCOPE_RANK,
    SENSITIVE_MODULE,
    Action,
    Scope,
)
from app.auth.security import decode_access_token
from app.core.db import get_session
from app.core.errors import AppError, ForbiddenError

PENDING_PASSWORD = "change_password"  # noqa: S105 - a step name, not a secret
PENDING_TOTP = "setup_totp"
PENDING_PRIVACY = "accept_privacy"
PENDING_PROFILE = "complete_profile"
# Current privacy notice version; bump to ask everyone to accept again.
PRIVACY_VERSION = "2026-1"


@dataclass(frozen=True)
class RoleRef:
    code: str
    name: str
    requires_2fa: bool


@dataclass
class Principal:
    user: User
    roles: list[RoleRef]
    active_role: str | None
    grants: dict[tuple[str, str], Scope]
    # Filled by the project module (assignments) in a later phase; used by Scope.PROJECT.
    project_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    # Captured once so they stay readable after a rollback expires the ORM object.
    id: uuid.UUID = field(init=False)
    department_id: uuid.UUID | None = field(init=False)

    def __post_init__(self) -> None:
        self.id = self.user.id
        self.department_id = self.user.department_id

    @property
    def role_codes(self) -> set[str]:
        return {r.code for r in self.roles}

    @property
    def pending(self) -> list[str]:
        out = []
        # Order of the first-login steps: password, privacy notice, 2FA, profile.
        if self.user.must_change_password:
            out.append(PENDING_PASSWORD)
        if self.user.privacy_version != PRIVACY_VERSION:
            out.append(PENDING_PRIVACY)
        if not self.user.totp_enabled and any(r.requires_2fa for r in self.roles):
            out.append(PENDING_TOTP)
        if self.user.profile_completed_at is None:
            out.append(PENDING_PROFILE)
        return out

    def scope_for(self, module: str, action: str) -> Scope | None:
        return self.grants.get((module, str(action)))

    def can(self, module: str, action: str) -> bool:
        return (module, str(action)) in self.grants

    def can_see(self, sensitive_field: str) -> bool:
        return (SENSITIVE_MODULE, sensitive_field) in self.grants

    def permissions_tree(self) -> dict[str, dict[str, str]]:
        tree: dict[str, dict[str, str]] = {}
        for (module, action), scope in sorted(self.grants.items()):
            tree.setdefault(module, {})[action] = str(scope)
        return tree


async def load_principal(
    session: AsyncSession, user: User, active_role: str | None = None
) -> Principal:
    rows = (
        (
            await session.execute(
                select(Role)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id, Role.is_active.is_(True), UserRole.active_now())
                .order_by(Role.name)
            )
        )
        .scalars()
        .all()
    )
    roles = [RoleRef(r.code, r.name, r.requires_2fa) for r in rows]
    role_ids = [r.id for r in rows]
    if active_role:
        if active_role not in {r.code for r in rows}:
            raise ForbiddenError(
                "ROLE_NOT_ASSIGNED", "Peran yang dipilih tidak dimiliki akun Anda."
            )
        role_ids = [r.id for r in rows if r.code == active_role]

    grants: dict[tuple[str, str], Scope] = {}
    if role_ids:
        perms = (
            await session.execute(
                select(RolePermission).where(RolePermission.role_id.in_(role_ids))
            )
        ).scalars()
        for p in perms:
            key, scope = (p.module, p.action), Scope(p.scope)
            if key not in grants or SCOPE_RANK[scope] > SCOPE_RANK[grants[key]]:
                grants[key] = scope
    # Project-scoped grants: projects the user is assigned to (planner/manager for now).
    from app.project.models import Project  # local: project imports auth

    assigned = frozenset(
        (await session.execute(select(Project.id).where(Project.manager_id == user.id))).scalars()
    )
    return Principal(
        user=user, roles=roles, active_role=active_role, grants=grants, project_ids=assigned
    )


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError("UNAUTHENTICATED", "Silakan masuk terlebih dahulu.", status_code=401)
    return token


async def _principal(
    request: Request,
    session: AsyncSession,
    active_role: str | None,
) -> Principal:
    payload = decode_access_token(_bearer(request))
    user = await session.get(User, uuid.UUID(payload["sub"]))
    # Checked on every request so deactivation and locks take effect immediately.
    if user is None or not user.is_active:
        raise AppError("UNAUTHENTICATED", "Akun tidak aktif. Hubungi admin.", status_code=401)
    principal = await load_principal(session, user, active_role)
    request.state.principal = principal
    return principal


async def get_principal_allow_pending(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    x_active_role: Annotated[str | None, Header()] = None,
) -> Principal:
    """For auth endpoints that must work before password change / 2FA setup."""
    return await _principal(request, session, x_active_role)


async def get_principal(
    principal: Annotated[Principal, Depends(get_principal_allow_pending)],
) -> Principal:
    ensure_onboarded(principal)
    return principal


def ensure_onboarded(principal: Principal) -> None:
    """Raise when first-login steps (password, privacy, 2FA, profile) are still open."""
    pending = principal.pending
    if PENDING_PASSWORD in pending:
        raise ForbiddenError(
            "PASSWORD_CHANGE_REQUIRED", "Ganti kata sandi sementara Anda terlebih dahulu."
        )
    if PENDING_PRIVACY in pending:
        raise ForbiddenError(
            "PRIVACY_ACCEPTANCE_REQUIRED", "Baca dan setujui pemberitahuan privasi terlebih dahulu."
        )
    if PENDING_TOTP in pending:
        raise ForbiddenError(
            "TOTP_SETUP_REQUIRED", "Aktifkan verifikasi dua langkah (2FA) terlebih dahulu."
        )
    if PENDING_PROFILE in pending:
        raise ForbiddenError("PROFILE_REQUIRED", "Lengkapi profil Anda terlebih dahulu.")


CurrentUser = Annotated[Principal, Depends(get_principal)]


def require(module: str, action: Action | str) -> Callable[..., Awaitable[Principal]]:
    """FastAPI dependency: the current user must hold `action` on `module` (any scope)."""
    if module not in MODULES:
        raise ValueError(f"unknown module {module!r}")
    act = Action(action)

    async def dep(principal: CurrentUser) -> Principal:
        if not principal.can(module, act):
            raise ForbiddenError(
                "PERMISSION_DENIED",
                f"Anda tidak memiliki izin {ACTION_LABELS[act]} data {MODULES[module]}.",
            )
        return principal

    dep.__name__ = f"require_{module}_{act}"
    return dep


def scope_filter(
    principal: Principal,
    module: str,
    action: Action | str,
    *,
    owner_col: Any,
    department_col: Any | None = None,
    project_col: Any | None = None,
) -> ColumnElement[bool]:
    """SQL condition limiting rows to the user's data scope for (module, action).

    own -> owner_col = user; department -> same department (or own); project -> assigned
    projects (or own); all -> no limit. No grant at all -> no rows.
    """
    scope = principal.scope_for(module, action)
    own: ColumnElement[bool] = owner_col == principal.id
    if scope is None:
        return false()
    if scope == Scope.ALL:
        return true()
    if scope == Scope.DEPARTMENT and department_col is not None and principal.department_id:
        return or_(own, department_col == principal.department_id)
    if scope == Scope.PROJECT and project_col is not None and principal.project_ids:
        return or_(own, project_col.in_(principal.project_ids))
    return own


def strip_sensitive(
    principal: Principal, data: dict[str, Any], fields: dict[str, str] | Iterable[str]
) -> dict[str, Any]:
    """Remove sensitive keys the user may not see. `fields` maps response key -> sensitive
    field name (salary, nik, bank_account, tax_id); an iterable means key == field."""
    mapping = fields if isinstance(fields, dict) else {f: f for f in fields}
    return {k: v for k, v in data.items() if k not in mapping or principal.can_see(mapping[k])}
