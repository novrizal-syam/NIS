"""Service tickets from approved DORs (prompt 06 · 1).

A ticket covers one project's approved, not-yet-ticketed DORs (one day or a period). The client
signs on a tablet (signature pad) or through a 7-day link opened by a Client Representative
account. Lines the client disputes (with a reason) leave the ticket value; their revenue, accrued
when the DOR was approved, is reversed (Dr 4100 / Cr 1220) and listed in the Dispute Register.
The signed PDF goes to the DMS through the PSrE adapter (internal mode for now).
"""

import base64
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.billing import documents, psre
from app.billing.models import ServiceTicket, TicketDor, TicketLine
from app.contract.models import Contract, ContractRate
from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.dms import service as dms
from app.master.models import Client, Employee, Item
from app.operations.models import Dor, DorConsumable, DorCrew, DorEquipment
from app.project.models import Project
from app.services import audit, email, ledger, letterhead, numbering
from app.services.audit import AuditAction
from app.services.money import format_idr
from app.services.storage import Storage
from app.setup import service as settings_store

DOC = "service_ticket"
LINK_DAYS = 7
ZERO = Decimal(0)
STATUS_LABELS = {
    "awaiting_signature": "Menunggu tanda tangan klien",
    "signed": "Ditandatangani",
    "invoiced": "Sudah ditagih",
    "cancelled": "Dibatalkan",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def lines_of(session: AsyncSession, ticket_id: uuid.UUID) -> list[TicketLine]:
    rows = await session.execute(
        select(TicketLine).where(TicketLine.ticket_id == ticket_id).order_by(TicketLine.seq)
    )
    return list(rows.scalars())


def _h(v: Decimal) -> str:
    return format(v.normalize(), "f")


async def create(
    session: AsyncSession,
    actor: Principal,
    project: Project,
    *,
    date_from: date,
    date_to: date,
    dor_ids: list[uuid.UUID] | None = None,
) -> ServiceTicket:
    if project.contract_id is None:
        raise AppError("NO_CONTRACT", f"{project.number} tidak punya kontrak.", status_code=422)
    if date_to < date_from:
        raise AppError("PERIOD_INVALID", "Periode tidak valid.", status_code=422)
    ticketed = select(TicketDor.dor_id)
    stmt = select(Dor).where(
        Dor.project_id == project.id,
        Dor.status == "approved",
        Dor.report_date.between(date_from, date_to),
        Dor.id.not_in(ticketed),
    )
    if dor_ids:
        stmt = stmt.where(Dor.id.in_(dor_ids))
    dors = list((await session.execute(stmt.order_by(Dor.report_date))).scalars())
    if dor_ids and len(dors) != len(set(dor_ids)):
        raise ConflictError(
            "DOR_NOT_BILLABLE",
            "Sebagian DOR belum disetujui, di luar periode, atau sudah masuk service ticket lain.",
        )
    if not dors:
        raise AppError(
            "NO_DORS",
            "Tidak ada DOR disetujui yang belum ditagih pada periode ini.",
            status_code=422,
        )
    rates = {
        r.id: r
        for r in (
            await session.execute(
                select(ContractRate).where(ContractRate.contract_id == project.contract_id)
            )
        ).scalars()
    }
    people = dict((await session.execute(select(Employee.code, Employee.full_name))).tuples().all())
    items = {i.code: i for i in (await session.execute(select(Item))).scalars()}
    t = ServiceTicket(
        number=await numbering.next(session, "TK"),
        contract_id=project.contract_id,
        project_id=project.id,
        period_from=min(d.report_date for d in dors),
        period_to=max(d.report_date for d in dors),
        status="awaiting_signature",
        created_by=actor.id,
        is_demo=project.is_demo,
    )
    session.add(t)
    await session.flush()
    seq = 0
    gross = ZERO

    def add(dor: Dor, kind: str, desc: str, qty: Decimal, unit: str, amount: Decimal) -> None:
        nonlocal seq, gross
        if amount <= 0:
            return
        seq += 1
        gross += amount
        session.add(
            TicketLine(
                ticket_id=t.id,
                seq=seq,
                dor_id=dor.id,
                work_date=dor.report_date,
                kind=kind,
                description=desc[:300],
                qty=qty,
                unit=unit,
                amount=amount,
            )
        )

    for dor in dors:
        session.add(TicketDor(ticket_id=t.id, dor_id=dor.id))
        for e in (
            await session.execute(select(DorEquipment).where(DorEquipment.dor_id == dor.id))
        ).scalars():
            r = rates.get(e.rate_id) if e.rate_id else None
            hours = (
                f"op {_h(e.operating)}/sb {_h(e.standby)}/bd {_h(e.breakdown)}/rig {_h(e.rig)} jam"
            )
            add(
                dor,
                "equipment",
                f"{r.description if r else 'Peralatan'} {e.asset_code} ({hours})",
                Decimal(1),
                r.unit if r else "hari",
                e.revenue,
            )
        for c in (await session.execute(select(DorCrew).where(DorCrew.dor_id == dor.id))).scalars():
            r = rates.get(c.rate_id) if c.rate_id else None
            add(
                dor,
                "personnel",
                f"{r.description if r else 'Personel'} - "
                f"{people.get(c.employee_code, c.employee_code)}",
                Decimal(1),
                r.unit if r else "hari",
                c.revenue,
            )
        for k in (
            await session.execute(select(DorConsumable).where(DorConsumable.dor_id == dor.id))
        ).scalars():
            r = rates.get(k.rate_id) if k.rate_id else None
            it = items.get(k.item_code)
            add(
                dor,
                "consumable",
                f"{r.description if r else (it.name if it else k.item_code)}",
                k.qty,
                it.uom if it else "unit",
                k.revenue,
            )
    if gross <= 0:
        raise AppError(
            "NOTHING_BILLABLE", "DOR terpilih tidak punya nilai yang ditagih.", status_code=422
        )
    t.gross_value = t.value = gross
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=t.id,
        actor_id=actor.id,
        after={"number": t.number, "dors": [d.number for d in dors], "value": gross},
    )
    return t


async def cancel(session: AsyncSession, actor: Principal, t: ServiceTicket, reason: str) -> None:
    if t.status != "awaiting_signature":
        raise ConflictError(
            "TICKET_SIGNED", f"{t.number} sudah ditandatangani; tidak dapat dibatalkan."
        )
    if len(reason.strip()) < 5:
        raise AppError("REASON_REQUIRED", "Tulis alasan pembatalan.", status_code=422)
    await session.execute(delete(TicketDor).where(TicketDor.ticket_id == t.id))
    t.status, t.link_token_hash = "cancelled", None
    await session.flush()
    await audit.record(
        session,
        action="status_change",
        entity_type=DOC,
        entity_id=t.id,
        actor_id=actor.id,
        after={"status": "cancelled"},
        note=reason.strip(),
    )


# ---------------------------------------------------------------- signing


@dataclass(frozen=True)
class Signature:
    signer_name: str
    png: bytes
    acceptance_no: str | None
    disputes: dict[uuid.UUID, str]


def decode_png(data_url: str) -> bytes:
    raw = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    try:
        png = base64.b64decode(raw, validate=True)
    except ValueError as exc:
        raise AppError("SIGNATURE_INVALID", "Tanda tangan tidak terbaca.", status_code=422) from exc
    if not png.startswith(b"\x89PNG") or len(png) > 500_000:
        raise AppError(
            "SIGNATURE_INVALID", "Tanda tangan harus gambar PNG (maks. 500 KB).", status_code=422
        )
    return png


async def sign(
    session: AsyncSession,
    storage: Storage,
    actor: Principal,
    t: ServiceTicket,
    s: Signature,
    *,
    method: str,
) -> ServiceTicket:
    if t.status != "awaiting_signature":
        raise ConflictError("TICKET_NOT_OPEN", f"{t.number} tidak menunggu tanda tangan.")
    if len(s.signer_name.strip()) < 3:
        raise AppError("SIGNER_REQUIRED", "Tulis nama penanda tangan klien.", status_code=422)
    lines = await lines_of(session, t.id)
    known = {x.id for x in lines}
    for lid, reason in s.disputes.items():
        if lid not in known:
            raise AppError("LINE_INVALID", "Baris dispute tidak ada di tiket ini.", status_code=422)
        if len(reason.strip()) < 5:
            raise AppError(
                "DISPUTE_REASON",
                "Tulis alasan untuk setiap baris yang di-dispute.",
                status_code=422,
            )
    disputed = ZERO
    for x in lines:
        if x.id in s.disputes:
            x.disputed, x.dispute_reason, x.disputed_at = True, s.disputes[x.id].strip(), _now()
            disputed += x.amount
    t.disputed_value, t.value = disputed, t.gross_value - disputed
    t.signer_name, t.signer_user_id = s.signer_name.strip(), actor.id
    t.acceptance_no = (s.acceptance_no or "").strip() or None
    t.sign_method, t.signed_at, t.status = method, _now(), "signed"
    t.link_token_hash = None
    project = await session.get(Project, t.project_id)
    contract = await session.get(Contract, t.contract_id, with_for_update=True)
    assert project is not None and contract is not None
    if disputed > 0:
        # Revenue accrued at DOR approval is reversed for the disputed lines.
        entry = await ledger.post_event(
            session,
            "ticket_dispute",
            {"disputed": disputed},
            entry_date=numbering.today_jakarta(),
            description=f"{t.number} dispute klien (pembalikan pendapatan)",
            source_type=DOC,
            source_id=t.id,
            source_number=t.number,
            by=actor.id,
            dims=ledger.Dims(
                project_id=project.id, partner_type="client", partner_code=contract.client_code
            ),
            memo=t.number,
            is_demo=t.is_demo,
        )
        t.reversal_journal_id = entry.id
        contract.used_value = max(contract.used_value - disputed, ZERO)
    await session.flush()

    sig = await dms.upload(
        session,
        storage,
        actor,
        entity_type=DOC,
        entity_id=str(t.id),
        filename=f"{t.number}-tanda-tangan.png",
        data=s.png,
        note=f"Tanda tangan {t.signer_name}",
    )
    t.signature_attachment_id = sig.id
    client = (
        await session.execute(select(Client).where(Client.code == contract.client_code))
    ).scalar_one_or_none()
    pdf = documents.render_ticket(
        await letterhead.load(session, storage),
        t,
        lines,
        project_label=f"{project.number} {project.name}",
        contract_label=f"{contract.number} {contract.po_number or ''}".strip(),
        client=client.name if client else contract.company_name,
        signature_png=s.png,
    )
    provider = psre.get(str(await settings_store.get(session, "psre.provider", "internal")))
    signed = await provider.sign(pdf, signer_name=t.signer_name, signer_email=t.link_email)
    att = await dms.upload(
        session,
        storage,
        actor,
        entity_type=DOC,
        entity_id=str(t.id),
        filename=f"{t.number}-ditandatangani.pdf",
        data=signed.pdf,
        note=f"PSrE {signed.provider}",
    )
    t.signed_pdf_attachment_id, t.psre_provider, t.psre_ref = (
        att.id,
        signed.provider,
        signed.reference,
    )
    await session.flush()
    await audit.record(
        session,
        action="sign",
        entity_type=DOC,
        entity_id=t.id,
        actor_id=actor.id,
        after={
            "signer": t.signer_name,
            "method": method,
            "disputed": disputed,
            "value": t.value,
            "acceptance_no": t.acceptance_no,
            "psre_ref": t.psre_ref,
        },
    )
    return t


async def create_link(
    session: AsyncSession, actor: Principal, t: ServiceTicket, to_email: str
) -> str:
    """7-day signing link for a Client Representative account; e-mailed and returned."""
    if t.status != "awaiting_signature":
        raise ConflictError("TICKET_NOT_OPEN", f"{t.number} tidak menunggu tanda tangan.")
    token = secrets.token_urlsafe(32)
    t.link_token_hash, t.link_expires_at = _hash(token), _now() + timedelta(days=LINK_DAYS)
    t.link_email = to_email.strip().lower()
    await session.flush()
    url = f"{get_settings().app_base_url.rstrip('/')}/tanda-tangan/{token}"
    await email.send_email(
        t.link_email,
        f"Persetujuan service ticket {t.number}",
        f"<p>Mohon tinjau dan tandatangani service ticket <b>{t.number}</b> "
        f'(nilai {format_idr(t.value)}).</p><p><a href="{url}">Buka service ticket</a> '
        f"(berlaku {LINK_DAYS} hari; masuk dengan akun Client Representative).</p>",
        f"Service ticket {t.number}: {url} (berlaku {LINK_DAYS} hari)",
    )
    await audit.record(
        session,
        action="sign_link",
        entity_type=DOC,
        entity_id=t.id,
        actor_id=actor.id,
        after={"email": t.link_email, "expires": t.link_expires_at},
    )
    return url


async def by_token(
    session: AsyncSession, actor: Principal, token: str, lock: bool = False
) -> ServiceTicket:
    if "client_rep" not in actor.role_codes and not actor.can("billing", "edit"):
        raise ForbiddenError("CLIENT_REP_ONLY", "Tautan ini untuk akun Client Representative.")
    stmt = select(ServiceTicket).where(ServiceTicket.link_token_hash == _hash(token))
    if lock:
        stmt = stmt.with_for_update()
    t = (await session.execute(stmt)).scalar_one_or_none()
    if t is None or t.link_expires_at is None or t.link_expires_at < _now():
        raise NotFoundError(
            "LINK_INVALID", "Tautan tanda tangan tidak berlaku atau sudah kedaluwarsa."
        )
    return t
