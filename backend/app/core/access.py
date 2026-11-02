"""Record-level access for cross-cutting features (history, attachments).

Each module registers how to decide whether a user may read or write records of an
entity type; features such as the "Riwayat" tab and DMS attachments ask here instead
of knowing every module's rules.
"""

from collections.abc import Awaitable, Callable
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import ForbiddenError, NotFoundError

Mode = Literal["read", "write"]
Checker = Callable[[AsyncSession, Principal, str, Mode], Awaitable[bool]]

_checkers: dict[str, Checker] = {}


def register(entity_type: str, checker: Checker) -> None:
    _checkers[entity_type] = checker


def known(entity_type: str) -> bool:
    return entity_type in _checkers


async def require(
    session: AsyncSession, principal: Principal, entity_type: str, entity_id: str, mode: Mode
) -> None:
    checker = _checkers.get(entity_type)
    if checker is None:
        raise NotFoundError("UNKNOWN_ENTITY", "Jenis dokumen tidak dikenal.")
    if not await checker(session, principal, entity_id, mode):
        if mode == "read":
            raise NotFoundError("NOT_FOUND", "Dokumen tidak ditemukan atau Anda tidak berizin.")
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin mengubah dokumen ini.")


def module_checker(read_module: str, write_module: str, write_action: str = "edit") -> Checker:
    async def check(_: AsyncSession, principal: Principal, __: str, mode: Mode) -> bool:
        if mode == "read":
            return principal.can(read_module, "view")
        return principal.can(write_module, write_action)

    return check
