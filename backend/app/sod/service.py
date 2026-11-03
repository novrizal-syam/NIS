import uuid
from datetime import UTC, datetime
from itertools import combinations
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import admin
from app.auth.models import Role, User, UserRole
from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.services import audit
from app.sod.models import SodException, SodRule
from app.sod.seed import norm
from app.workflow import engine
from app.workflow.models import ApprovalRequest


class SodConflictError(ConflictError):
    """Raised when a role change needs an SoD exception (reason + Director approval)."""


async def active_rules(session: AsyncSession) -> dict[tuple[str, str], str]:
    rows = await session.execute(select(SodRule).where(SodRule.is_active.is_(True)))
    return {norm(r.role_a, r.role_b): r.description for r in rows.scalars()}


async def approved_pairs(session: AsyncSession, user_id: uuid.UUID) -> set[tuple[str, str]]:
    rows = await session.execute(
        select(SodException.pairs).where(
            SodException.user_id == user_id, SodException.status == "approved"
        )
    )
    return {norm(a, b) for pairs in rows.scalars() for a, b in pairs}


async def conflicts(
    session: AsyncSession, user_id: uuid.UUID, codes: list[str]
) -> list[tuple[str, str, str]]:
    """Conflicting pairs in `codes` that have no approved exception for this user."""
    rules = await active_rules(session)
    allowed = await approved_pairs(session, user_id)
    out = []
    for a, b in combinations(sorted(set(codes)), 2):
        pair = norm(a, b)
        if pair in rules and pair not in allowed:
            out.append((pair[0], pair[1], rules[pair]))
    return out


def make_hook(reason: str | None) -> Any:
    """Role-change hook used by user admin. Without a reason a conflict is refused; with a
    reason an exception request goes to the Director and the change waits for approval."""

    async def hook(
        session: AsyncSession, actor: Principal, user: User, before: list[str], after: list[str]
    ) -> None:
        found = await conflicts(session, user.id, after)
        new = [c for c in found if c[0] not in before or c[1] not in before]
        if not new:
            return
        names = dict((await session.execute(select(Role.code, Role.name))).tuples().all())
        text = "; ".join(f"{names.get(a, a)} + {names.get(b, b)} ({d})" for a, b, d in new)
        if not reason or len(reason.strip()) < 10:
            raise SodConflictError(
                "SOD_CONFLICT",
                f"Kombinasi peran melanggar pemisahan tugas: {text}. Isi alasan (min. 10 karakter) "
                "untuk mengajukan pengecualian ke Direktur.",
                details={"pairs": [[a, b] for a, b, _ in new]},
            )
        raise PendingException(new)

    return hook


class PendingException(Exception):  # noqa: N818 - control flow, not an error shown to users
    def __init__(self, pairs: list[tuple[str, str, str]]) -> None:
        self.pairs = pairs


async def request_exception(
    session: AsyncSession,
    actor: Principal,
    user: User,
    *,
    pairs: list[tuple[str, str, str]],
    reason: str,
    change: dict[str, Any],
) -> ApprovalRequest:
    exc = SodException(
        user_id=user.id,
        pairs=[[a, b] for a, b, _ in pairs],
        reason=reason.strip(),
        change=change,
        created_by=actor.id,
    )
    session.add(exc)
    await session.flush()
    req = await engine.submit(
        session,
        actor,
        doc_type="sod_exception",
        doc_id=exc.id,
        doc_number=f"SOD-{str(exc.id)[:8].upper()}",
        title=f"Pengecualian SoD untuk {user.full_name}: "
        + "; ".join(f"{a} + {b}" for a, b, _ in pairs),
        context={
            "user": user.email,
            "pairs": [[a, b] for a, b, _ in pairs],
            "reason": reason,
            "change": change,
        },
    )
    await audit.record(
        session,
        action="sod_exception_requested",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor.id,
        after={"pairs": exc.pairs, "reason": exc.reason, "request": req.doc_number},
    )
    return req


async def _apply(session: AsyncSession, request: ApprovalRequest) -> None:
    exc = await session.get(SodException, uuid.UUID(request.doc_id))
    assert exc is not None
    exc.status, exc.decided_at = "approved", datetime.now(UTC)
    user = await session.get(User, exc.user_id)
    approver_id = next((s.acted_by for s in reversed(request.steps) if s.acted_by), None)
    actor_user = await session.get(User, request.requester_id)
    assert user is not None and actor_user is not None
    from app.auth.principal import load_principal  # local: avoid import cycle at module load

    requester = await load_principal(session, actor_user)
    change = exc.change
    if change["kind"] == "set_roles":
        await admin.set_roles(session, requester, user, change["roles"], None)
    else:
        await admin.add_temporary_role(
            session,
            requester,
            user,
            code=change["role"],
            valid_from=datetime.fromisoformat(change["valid_from"])
            if change.get("valid_from")
            else None,
            valid_until=datetime.fromisoformat(change["valid_until"]),
            reason=change["reason"],
            hook=None,
        )
    await audit.record(
        session,
        action="sod_exception_approved",
        entity_type="user",
        entity_id=user.id,
        actor_id=approver_id,
        after={"pairs": exc.pairs, "request": request.doc_number},
    )


async def _reject(session: AsyncSession, request: ApprovalRequest) -> None:
    exc = await session.get(SodException, uuid.UUID(request.doc_id))
    if exc is not None:
        exc.status, exc.decided_at = (
            "rejected" if request.status == "rejected" else "revoked",
            datetime.now(UTC),
        )


engine.register_document("sod_exception", on_approved=_apply, on_rejected=_reject)


async def violations(session: AsyncSession) -> list[dict[str, Any]]:
    """Active users currently holding a conflicting pair without an approved exception."""
    rules = await active_rules(session)
    rows = await session.execute(
        select(User.id, User.full_name, User.email, Role.code)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.is_active.is_(True), UserRole.active_now())
    )
    by_user: dict[uuid.UUID, dict[str, Any]] = {}
    for uid, name, email, code in rows.all():
        by_user.setdefault(
            uid, {"user_id": str(uid), "full_name": name, "email": email, "roles": []}
        )["roles"].append(code)
    out = []
    for uid, info in by_user.items():
        allowed = await approved_pairs(session, uid)
        for a, b in combinations(sorted(info["roles"]), 2):
            pair = norm(a, b)
            if pair in rules and pair not in allowed:
                out.append({**info, "pair": list(pair), "description": rules[pair]})
    return out


def check_reason(reason: str | None) -> str:
    if not reason or len(reason.strip()) < 10:
        raise AppError("REASON_REQUIRED", "Alasan wajib diisi (min. 10 karakter).", status_code=422)
    return reason.strip()
