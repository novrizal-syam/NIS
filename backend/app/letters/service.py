import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.billing import psre
from app.core.errors import AppError, ConflictError, ForbiddenError
from app.dms import service as dms
from app.dms.models import Attachment
from app.letters import emeterai
from app.letters.models import IncomingLetter, LetterDisposition, LetterTemplate, OutgoingLetter
from app.notifications import service as notifications
from app.services import audit, numbering
from app.services.audit import AuditAction
from app.services.storage import Storage
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest


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


# ---------------------------------------------------------------- 09: incoming letters


IN_DOC = "incoming_letter"
OUT_DOC = "outgoing_letter"
METERAI_THRESHOLD = 5_000_000


async def register_incoming(
    session: AsyncSession, actor: Principal, data: dict[str, Any]
) -> IncomingLetter:
    letter = IncomingLetter(
        number=await numbering.next(session, "SM", on=data["received_on"]),
        received_on=data["received_on"],
        sender=data["sender"].strip(),
        sender_ref=data.get("sender_ref"),
        letter_date=data.get("letter_date"),
        subject=data["subject"].strip(),
        summary=data.get("summary"),
        confidential=bool(data.get("confidential")),
        project_id=data.get("project_id"),
        status="registered",
        created_by=actor.id,
    )
    session.add(letter)
    await session.flush()
    await audit.record(
        session,
        action="register",
        entity_type=IN_DOC,
        entity_id=letter.id,
        actor_id=actor.id,
        after={"number": letter.number, "sender": letter.sender, "subject": letter.subject},
    )
    return letter


async def attach_scan(
    session: AsyncSession, actor: Principal, letter: IncomingLetter, att: Attachment
) -> IncomingLetter:
    if att.entity_type != IN_DOC or att.entity_id != str(letter.id):
        raise AppError("FILE_INVALID", "File bukan milik surat ini.", status_code=422)
    letter.file_id = att.id
    await session.flush()
    return letter


async def dispositions(session: AsyncSession, letter_id: uuid.UUID) -> list[LetterDisposition]:
    return list(
        (
            await session.execute(
                select(LetterDisposition)
                .where(LetterDisposition.letter_id == letter_id)
                .order_by(LetterDisposition.created_at)
            )
        ).scalars()
    )


async def dispose(
    session: AsyncSession,
    actor: Principal,
    letter: IncomingLetter,
    *,
    pic_id: uuid.UUID,
    instruction: str,
    deadline: date,
) -> LetterDisposition:
    if letter.status == "closed":
        raise ConflictError("LETTER_CLOSED", f"Surat {letter.number} sudah ditutup.")
    if deadline < letter.received_on:
        raise AppError(
            "DEADLINE_INVALID", "Tenggat tidak boleh sebelum surat diterima.", status_code=422
        )
    d = LetterDisposition(
        letter_id=letter.id,
        pic_id=pic_id,
        instruction=instruction.strip(),
        deadline=deadline,
        status="open",
        created_by=actor.id,
    )
    session.add(d)
    letter.status = "routed"
    await session.flush()
    await notifications.notify(
        session,
        [pic_id],
        kind="disposition",
        title=f"Disposisi surat {letter.number}: {letter.subject[:80]}",
        body=f"{instruction.strip()[:200]} — tenggat {deadline:%d/%m/%Y}",
        link=f"/surat/masuk/{letter.id}",
    )
    await audit.record(
        session,
        action="dispose",
        entity_type=IN_DOC,
        entity_id=letter.id,
        actor_id=actor.id,
        after={"pic": str(pic_id), "deadline": deadline.isoformat()},
    )
    return d


async def complete_disposition(
    session: AsyncSession, actor: Principal, d: LetterDisposition, note: str
) -> LetterDisposition:
    if d.pic_id != actor.id:
        raise ForbiddenError("NOT_PIC", "Hanya PIC disposisi yang dapat menyelesaikannya.")
    if d.status != "open":
        raise ConflictError("DISPOSITION_DONE", "Disposisi sudah selesai.")
    d.status, d.done_at, d.done_note = "done", datetime.now(UTC), note.strip()
    await session.flush()
    await audit.record(
        session,
        action="disposition_done",
        entity_type=IN_DOC,
        entity_id=d.letter_id,
        actor_id=actor.id,
        after={"note": d.done_note},
    )
    return d


async def close_incoming(
    session: AsyncSession,
    actor: Principal,
    letter: IncomingLetter,
    *,
    reply_id: uuid.UUID | None,
    note: str | None,
) -> IncomingLetter:
    if letter.status == "closed":
        raise ConflictError("LETTER_CLOSED", "Surat sudah ditutup.")
    if reply_id is not None:
        reply = await session.get(OutgoingLetter, reply_id)
        if reply is None or reply.status != "sent":
            raise AppError("REPLY_INVALID", "Surat balasan belum terkirim.", status_code=422)
        reply.in_reply_to = letter.id
    elif len((note or "").strip()) < 5:
        raise AppError(
            "CLOSE_NOTE", "Tautkan surat balasan atau tulis catatan penutupan.", status_code=422
        )
    open_d = [d for d in await dispositions(session, letter.id) if d.status == "open"]
    if open_d:
        raise ConflictError("DISPOSITION_OPEN", f"{len(open_d)} disposisi belum selesai.")
    letter.status, letter.closed_at, letter.close_note = "closed", datetime.now(UTC), note
    await session.flush()
    await audit.record(
        session,
        action="close",
        entity_type=IN_DOC,
        entity_id=letter.id,
        actor_id=actor.id,
        after={"reply": str(reply_id) if reply_id else None},
    )
    return letter


async def disposition_reminders(session: AsyncSession, today: date | None = None) -> int:
    """D-1 and overdue reminders to PICs of open dispositions."""
    today = today or numbering.today_jakarta()
    sent = 0
    rows = (
        await session.execute(
            select(LetterDisposition, IncomingLetter)
            .join(IncomingLetter, IncomingLetter.id == LetterDisposition.letter_id)
            .where(
                LetterDisposition.status == "open",
                LetterDisposition.deadline <= today + timedelta(days=1),
            )
        )
    ).tuples()
    for d, letter in rows:
        late = today > d.deadline
        sent += await notifications.notify(
            session,
            [d.pic_id],
            kind="disposition_reminder",
            title=("Lewat tenggat: " if late else "Tenggat besok: ") + f"disposisi {letter.number}",
            body=d.instruction[:200],
            link=f"/surat/masuk/{letter.id}",
            dedupe_key=f"disp-{d.id}-{'late' if late else 'd1'}",
        )
    return sent


# ---------------------------------------------------------------- 09: outgoing letters


_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def fill(template: str, values: dict[str, str]) -> str:
    missing = sorted({m for m in _PLACEHOLDER.findall(template) if not values.get(m)})
    if missing:
        raise AppError(
            "TEMPLATE_VALUES",
            f"Isi nilai: {', '.join(missing)}.",
            status_code=422,
            details={"missing": missing},
        )
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


async def draft_outgoing(
    session: AsyncSession, actor: Principal, data: dict[str, Any]
) -> OutgoingLetter:
    subject, body = data.get("subject"), data.get("body")
    code = data.get("template_code")
    if code:
        tpl = (
            await session.execute(select(LetterTemplate).where(LetterTemplate.code == code))
        ).scalar_one_or_none()
        if tpl is None or not tpl.is_active:
            raise AppError("TEMPLATE_INVALID", "Template surat tidak ditemukan.", status_code=422)
        values = {k: str(v) for k, v in (data.get("values") or {}).items()}
        subject = subject or fill(tpl.subject, values)
        body = body or fill(tpl.body, values)
    if not subject or not body:
        raise AppError("LETTER_EMPTY", "Isi perihal dan isi surat.", status_code=422)
    letter = OutgoingLetter(
        number=None,
        status="draft",
        department=data["department"].strip().upper(),
        to=data["to"][:300],
        subject=subject[:300],
        body=body,
        template_code=code,
        signer_name=data.get("signer_name"),
        needs_meterai=bool(data.get("needs_meterai")),
        letter_date=numbering.today_jakarta(),
        entity_type=data.get("entity_type"),
        entity_id=data.get("entity_id"),
        in_reply_to=data.get("in_reply_to"),
        created_by=actor.id,
    )
    session.add(letter)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=OUT_DOC,
        entity_id=letter.id,
        actor_id=actor.id,
        after={"to": letter.to, "subject": letter.subject},
    )
    return letter


async def submit_outgoing(
    session: AsyncSession, actor: Principal, letter: OutgoingLetter
) -> ApprovalRequest:
    if letter.status != "draft":
        raise ConflictError("NOT_DRAFT", "Surat tidak lagi draf.")
    req = await engine.submit(
        session,
        actor,
        doc_type=OUT_DOC,
        doc_id=letter.id,
        doc_number=f"Draf surat {letter.department}",
        title=f"Surat keluar ke {letter.to[:60]}: {letter.subject[:80]}",
    )
    letter.status, letter.request_id, letter.reject_reason = "awaiting_approval", req.id, None
    await session.flush()
    return req


async def _out_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    letter = await session.get(OutgoingLetter, uuid.UUID(request.doc_id), with_for_update=True)
    if letter is None or letter.status != "awaiting_approval":
        return
    day = numbering.today_jakarta()
    # Gap-free: the number is taken only when the Director approves.
    letter.number = await numbering.next_letter(session, letter.department, on=day)
    letter.letter_date, letter.status = day, "approved"
    await session.flush()
    acted = [s.acted_by for s in request.steps if s.acted_by]
    await audit.record(
        session,
        action="letter_issued",
        entity_type="outgoing_letter",
        entity_id=letter.id,
        actor_id=acted[-1] if acted else None,
        after={"number": letter.number},
    )


async def _out_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    letter = await session.get(OutgoingLetter, uuid.UUID(request.doc_id), with_for_update=True)
    if letter is None or letter.status != "awaiting_approval":
        return
    acted = [s for s in request.steps if s.acted_by]
    letter.status, letter.request_id = "draft", None
    letter.reject_reason = (acted[-1].comment if acted else None) or None
    await session.flush()


engine.register_document(OUT_DOC, on_approved=_out_approved, on_rejected=_out_rejected)


def letter_pdf(head: Any, letter: OutgoingLetter) -> bytes:
    from app.billing.documents import _kv, _start
    from app.crm.quotation_pdf import _t, id_date

    pdf = _start(head)
    pdf.add_page()
    _kv(
        pdf,
        [
            ("Nomor", letter.number or "-"),
            ("Tanggal", id_date(letter.letter_date)),
            ("Kepada", letter.to),
            ("Perihal", letter.subject),
        ],
    )
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, _t(letter.body or ""))
    pdf.ln(10)
    pdf.cell(0, 5, _t("Hormat kami,"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(16)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, _t(letter.signer_name or "Direktur"), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


async def send_outgoing(
    session: AsyncSession,
    storage: Storage,
    actor: Principal,
    letter: OutgoingLetter,
    *,
    via: str,
    sent_to: str | None,
) -> OutgoingLetter:
    """PDF on letterhead -> e-signature (PSrE) -> e-Meterai when needed -> DMS -> sent log."""
    from app.services import letterhead

    if letter.status != "approved":
        raise ConflictError("NOT_APPROVED", "Surat belum disetujui Direktur.")
    pdf = letter_pdf(await letterhead.load(session, storage), letter)
    signed = await psre.get(await settings_store.get(session, "psre.provider", None)).sign(
        pdf, signer_name=letter.signer_name or "Direktur", signer_email=None
    )
    pdf, letter.esign_ref = signed.pdf, signed.reference
    if letter.needs_meterai:
        provider = emeterai.get(await settings_store.get(session, "emeterai.provider", None))
        letter.emeterai_ref, pdf = await provider.stamp(pdf, document_no=letter.number or "")
    att = await dms.upload(
        session,
        storage,
        actor,
        entity_type=OUT_DOC,
        entity_id=str(letter.id),
        filename=f"{(letter.number or 'surat').replace('/', '-')}.pdf",
        data=pdf,
        note="Surat keluar ditandatangani",
    )
    letter.file_id, letter.status = att.id, "sent"
    letter.sent_at, letter.sent_via, letter.sent_to = datetime.now(UTC), via, sent_to or letter.to
    await session.flush()
    await audit.record(
        session,
        action="send",
        entity_type=OUT_DOC,
        entity_id=letter.id,
        actor_id=actor.id,
        after={
            "number": letter.number,
            "via": via,
            "esign": letter.esign_ref,
            "emeterai": letter.emeterai_ref,
        },
    )
    return letter
