from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.letters.models import OutgoingLetter
from app.services import audit, numbering


async def reserve(
    session: AsyncSession,
    actor: Principal,
    *,
    department: str,
    to: str,
    subject: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    on: date | None = None,
    is_demo: bool = False,
) -> OutgoingLetter:
    """Take the next letter number and register the letter (file attached by the caller)."""
    day = on or numbering.today_jakarta()
    letter = OutgoingLetter(
        number=await numbering.next_letter(session, department, on=day),
        department=department.strip().upper(),
        to=to[:300],
        subject=subject[:300],
        letter_date=day,
        entity_type=entity_type,
        entity_id=entity_id,
        created_by=actor.id,
        is_demo=is_demo,
    )
    session.add(letter)
    await session.flush()
    await audit.record(
        session,
        action="letter_issued",
        entity_type="outgoing_letter",
        entity_id=letter.id,
        actor_id=actor.id,
        after={"number": letter.number, "to": letter.to, "subject": letter.subject},
    )
    return letter
