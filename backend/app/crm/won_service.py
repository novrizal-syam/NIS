"""Won -> Contract + Draft project + project documents, in ONE database transaction
(PROCESS.md · Lead to contract). Nothing here commits: the endpoint commits once at the end,
so any failure leaves the opportunity Submitted and creates nothing."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.contract import service as contracts
from app.contract.models import Contract
from app.core.errors import AppError, ConflictError
from app.crm import quotation_service as quotations
from app.crm import service as crm
from app.crm.models import Opportunity, Quotation
from app.dms import service as dms
from app.dms.models import Attachment
from app.letters.models import OutgoingLetter
from app.project import service as projects
from app.project.models import Project
from app.services import audit
from app.services.storage import Storage


@dataclass(frozen=True)
class WonResult:
    contract: Contract
    project: Project
    documents: int


async def sent_quotation(session: AsyncSession, opp: Opportunity) -> Quotation:
    """The latest revision, which must have been sent to the client."""
    q = (
        await session.execute(
            select(Quotation)
            .where(Quotation.opportunity_id == opp.id)
            .order_by(Quotation.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if q is None or q.status != "sent":
        raise ConflictError(
            "QUOTATION_NOT_SENT",
            "Tandai menang hanya bila revisi penawaran terakhir sudah dikirim ke klien.",
        )
    return q


async def mark_won(
    session: AsyncSession,
    storage: Storage,
    actor: Principal,
    opp: Opportunity,
    *,
    po_number: str | None,
    start_date: date | None,
    end_date: date | None,
    payment_term_days: int | None,
) -> WonResult:
    if opp.stage != "submitted":
        raise ConflictError(
            "ILLEGAL_TRANSITION",
            "Tandai menang hanya dari tahap Submitted (penawaran sudah dikirim).",
        )
    if start_date and end_date and end_date < start_date:
        raise AppError(
            "PERIOD_INVALID", "Tanggal selesai kontrak sebelum tanggal mulai.", status_code=422
        )
    q = await sent_quotation(session, opp)
    lines = await quotations.lines_of(session, q.id)
    term = payment_term_days
    if term is None:
        term = 30
        if opp.client_code:
            from app.master.models import Client  # local: master imports nothing from crm

            client = (
                await session.execute(select(Client).where(Client.code == opp.client_code))
            ).scalar_one_or_none()
            term = client.payment_term_days if client else 30

    contract = await contracts.create_from_quotation(
        session,
        actor,
        opp,
        q,
        lines,
        po_number=po_number,
        start_date=start_date,
        end_date=end_date,
        payment_term_days=term,
    )
    project = await projects.create_draft(session, actor, contract, lines)

    # Project documents: the quotation as sent (letter PDF) is linked into the project.
    documents = 0
    letter = await session.get(OutgoingLetter, q.letter_id) if q.letter_id else None
    if letter and letter.file_id:
        att = await session.get(Attachment, letter.file_id)
        if att is not None:
            data = (await storage.get(att.storage_key)).data
            await dms.upload(
                session,
                storage,
                actor,
                entity_type="project",
                entity_id=str(project.id),
                filename=att.filename,
                data=data,
                note=f"Penawaran {q.number} Rev.{q.revision} · surat {letter.number}",
            )
            documents += 1

    opp.value = contract.value
    await crm.set_stage(
        session, opp, "won", actor_id=actor.id, note=f"{contract.number} · {project.number}"
    )
    await audit.record(
        session,
        action="won",
        entity_type="opportunity",
        entity_id=opp.id,
        actor_id=actor.id,
        after={"contract": contract.number, "project": project.number, "value": contract.value},
    )
    return WonResult(contract, project, documents)
