import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services import audit
from app.services.audit import AuditAction, AuditLog


async def test_record_stores_before_after_and_changed(session: AsyncSession) -> None:
    actor = uuid.uuid4()
    entity = uuid.uuid4()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type="purchase_requisition",
        entity_id=entity,
        actor_id=actor,
        before={"status": "Draft", "amount": Decimal("1250000"), "note": "a"},
        after={"status": "Submitted", "amount": Decimal("1250000"), "note": "a"},
    )
    await session.commit()

    row = (await session.execute(select(AuditLog))).scalar_one()
    assert row.actor_id == actor
    assert row.entity_id == str(entity)
    assert row.action == "update"
    assert row.before == {"status": "Draft", "amount": "1250000", "note": "a"}
    assert row.changed == ["status"]
    assert row.at is not None


async def test_audit_rolls_back_with_transaction(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as s:
        await audit.record(
            s, action="create", entity_type="x", entity_id="1", actor_id=None, after={"a": 1}
        )
        await s.rollback()
    async with sessionmaker() as s:
        assert (await s.execute(select(AuditLog))).first() is None


@pytest.mark.parametrize("stmt", ["UPDATE audit_log SET note = 'x'", "DELETE FROM audit_log"])
async def test_audit_log_is_append_only(
    sessionmaker: async_sessionmaker[AsyncSession], stmt: str
) -> None:
    async with sessionmaker() as s:
        await audit.record(s, action="create", entity_type="x", entity_id="1", actor_id=None)
        await s.commit()
    async with sessionmaker() as s:
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text(stmt))
