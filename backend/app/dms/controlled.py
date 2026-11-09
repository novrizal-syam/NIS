"""Controlled documents (09; PROCESS.md · SOP).

A revision is drafted with its PDF, submitted to DOA `sop_release` (Director) and becomes
effective on approval: the previous effective revision turns `uncontrolled` (kept, watermarked
TIDAK TERKENDALI), the document's next review date is set, and listeners (LMS) assign
read-and-acknowledge training to the affected roles. Annual review reminders go to the owner.
"""

import io
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError
from app.dms.models import Attachment, ControlledDocument, DocumentRevision
from app.notifications import service as notifications
from app.services import audit
from app.services.audit import AuditAction
from app.services.numbering import today_jakarta
from app.workflow import engine
from app.workflow.models import ApprovalRequest

DOC = "controlled_doc"
KINDS = ("sop", "form", "manual", "policy")
REVIEW_ALERT_DAYS = 30

Listener = Callable[[AsyncSession, ControlledDocument, DocumentRevision], Awaitable[None]]
_listeners: list[Listener] = []


def on_revision_effective(listener: Listener) -> None:
    _listeners.append(listener)


def _add_months(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    y, m = k // 12, k % 12 + 1
    return date(y, m, min(d.day, 28))


async def create(
    session: AsyncSession, actor: Principal, data: dict[str, Any]
) -> ControlledDocument:
    code = data["code"].strip().upper()
    if data["kind"] not in KINDS:
        raise AppError(
            "KIND_INVALID", "Jenis dokumen: sop, form, manual atau policy.", status_code=422
        )
    if (
        await session.execute(select(ControlledDocument.id).where(ControlledDocument.code == code))
    ).first():
        raise ConflictError("DUPLICATE_CODE", f"Kode dokumen {code} sudah ada.")
    doc = ControlledDocument(
        code=code,
        title=data["title"].strip(),
        kind=data["kind"],
        system=data.get("system"),
        department=data.get("department"),
        owner_id=data.get("owner_id") or actor.id,
        review_months=int(data.get("review_months") or 12),
        affected_roles=list(data.get("affected_roles") or []),
        created_by=actor.id,
    )
    session.add(doc)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=doc.id,
        actor_id=actor.id,
        after={"code": code, "title": doc.title},
    )
    return doc


async def revisions(session: AsyncSession, doc_id: uuid.UUID) -> list[DocumentRevision]:
    return list(
        (
            await session.execute(
                select(DocumentRevision)
                .where(DocumentRevision.document_id == doc_id)
                .order_by(DocumentRevision.revision.desc())
            )
        ).scalars()
    )


async def draft_revision(
    session: AsyncSession,
    actor: Principal,
    doc: ControlledDocument,
    *,
    change_summary: str,
    attachment_id: uuid.UUID,
    effective_date: date | None,
) -> DocumentRevision:
    pending = [
        r for r in await revisions(session, doc.id) if r.status in ("draft", "awaiting_approval")
    ]
    if pending:
        raise ConflictError(
            "REVISION_OPEN", f"Revisi {pending[0].revision} masih {pending[0].status}."
        )
    att = await session.get(Attachment, attachment_id)
    if att is None or att.entity_type != DOC or att.entity_id != str(doc.id):
        raise AppError("FILE_REQUIRED", "Unggah file revisi pada dokumen ini.", status_code=422)
    if att.content_type != "application/pdf":
        raise AppError("PDF_REQUIRED", "Dokumen terkendali diunggah sebagai PDF.", status_code=422)
    n = (
        await session.execute(
            select(func.coalesce(func.max(DocumentRevision.revision), -1)).where(
                DocumentRevision.document_id == doc.id
            )
        )
    ).scalar_one() + 1
    rev = DocumentRevision(
        document_id=doc.id,
        revision=n,
        status="draft",
        change_summary=change_summary.strip(),
        attachment_id=att.id,
        effective_date=effective_date,
        created_by=actor.id,
    )
    session.add(rev)
    await session.flush()
    return rev


async def submit(
    session: AsyncSession, actor: Principal, doc: ControlledDocument, rev: DocumentRevision
) -> ApprovalRequest:
    if rev.status != "draft":
        raise ConflictError("NOT_DRAFT", f"Revisi {rev.revision} tidak lagi draf.")
    req = await engine.submit(
        session,
        actor,
        doc_type="sop_release",
        doc_id=rev.id,
        doc_number=f"{doc.code} Rev.{rev.revision}",
        title=f"Rilis {doc.code} Rev.{rev.revision}: {doc.title[:80]}",
        context={"code": doc.code, "kind": doc.kind},
    )
    rev.status, rev.request_id, rev.reject_reason = "awaiting_approval", req.id, None
    await session.flush()
    return req


async def release(
    session: AsyncSession, rev: DocumentRevision, by: uuid.UUID | None
) -> ControlledDocument:
    doc = await session.get(ControlledDocument, rev.document_id, with_for_update=True)
    assert doc is not None
    today = today_jakarta()
    for old in await revisions(session, doc.id):
        if old.status == "effective" and old.id != rev.id:
            old.status, old.superseded_at = "uncontrolled", datetime.now(UTC)
    rev.status, rev.approved_by = "effective", by
    rev.effective_date = (
        rev.effective_date if rev.effective_date and rev.effective_date >= today else today
    )
    doc.current_revision, doc.effective_date = rev.revision, rev.effective_date
    doc.next_review = _add_months(rev.effective_date, doc.review_months)
    await session.flush()
    await audit.record(
        session,
        action="release",
        entity_type=DOC,
        entity_id=doc.id,
        actor_id=by,
        after={"revision": rev.revision, "effective_date": rev.effective_date.isoformat()},
    )
    for listener in _listeners:
        await listener(session, doc, rev)
    return doc


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    rev = await session.get(DocumentRevision, uuid.UUID(request.doc_id), with_for_update=True)
    if rev is None or rev.status != "awaiting_approval":
        return
    acted = [s.acted_by for s in request.steps if s.acted_by]
    await release(session, rev, acted[-1] if acted else None)


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    rev = await session.get(DocumentRevision, uuid.UUID(request.doc_id), with_for_update=True)
    if rev is None or rev.status != "awaiting_approval":
        return
    acted = [s for s in request.steps if s.acted_by]
    rev.status, rev.request_id = "draft", None
    rev.reject_reason = (acted[-1].comment if acted else None) or None
    await session.flush()


engine.register_document("sop_release", on_approved=_on_approved, on_rejected=_on_rejected)


async def import_register(session: AsyncSession, actor: Principal, data: bytes) -> dict[str, Any]:
    """Register import (e.g. the SOPs and forms of GEK-BPM-001 and GEK-MNT-001):
    columns code, title, kind, system, department, owner_email, review_months, affected_roles."""
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    assert ws is not None
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise AppError("IMPORT_EMPTY", "File kosong.", status_code=422)
    head = [str(h or "").strip().lower() for h in rows[0]]
    need = {"code", "title", "kind"}
    if not need <= set(head):
        raise AppError("IMPORT_HEADER", "Kolom wajib: code, title, kind.", status_code=422)
    created = updated = 0
    errors: list[str] = []
    emails = {
        e.lower(): i for e, i in (await session.execute(select(User.email, User.id))).tuples().all()
    }
    for n, raw in enumerate(rows[1:], start=2):
        r = {head[i]: (raw[i] if i < len(raw) else None) for i in range(len(head))}
        if not r.get("code"):
            continue
        code = str(r["code"]).strip().upper()
        kind = str(r.get("kind") or "").strip().lower()
        if kind not in KINDS:
            errors.append(f"Baris {n}: jenis '{kind}' tidak dikenal.")
            continue
        owner = emails.get(str(r.get("owner_email") or "").strip().lower())
        roles = [x.strip() for x in str(r.get("affected_roles") or "").split(",") if x.strip()]
        existing = (
            await session.execute(select(ControlledDocument).where(ControlledDocument.code == code))
        ).scalar_one_or_none()
        values = {
            "title": str(r.get("title") or "").strip() or code,
            "kind": kind,
            "system": (str(r.get("system")).strip() if r.get("system") else None),
            "department": (str(r.get("department")).strip() if r.get("department") else None),
            "review_months": int(str(r.get("review_months") or 12)),
            "affected_roles": roles,
        }
        if existing is None:
            session.add(
                ControlledDocument(
                    code=code, owner_id=owner or actor.id, created_by=actor.id, **values
                )
            )
            created += 1
        else:
            for k, v in values.items():
                setattr(existing, k, v)
            if owner:
                existing.owner_id = owner
            updated += 1
    await session.flush()
    await audit.record(
        session,
        action="import",
        entity_type=DOC,
        entity_id="register",
        actor_id=actor.id,
        after={"created": created, "updated": updated, "errors": len(errors)},
    )
    return {"created": created, "updated": updated, "errors": errors}


async def review_alerts(session: AsyncSession, today: date | None = None) -> int:
    today = today or today_jakarta()
    sent = 0
    rows = (
        await session.execute(
            select(ControlledDocument).where(
                ControlledDocument.next_review.is_not(None),
                ControlledDocument.next_review <= today + timedelta(days=REVIEW_ALERT_DAYS),
            )
        )
    ).scalars()
    for doc in rows:
        if doc.owner_id is None or doc.next_review is None:
            continue
        sent += await notifications.notify(
            session,
            [doc.owner_id],
            kind="document_review",
            title=f"Tinjauan tahunan {doc.code} jatuh tempo {doc.next_review:%d/%m/%Y}",
            body=doc.title[:200],
            link=f"/dokumen/terkendali/{doc.id}",
            dedupe_key=f"doc-review-{doc.id}-{doc.next_review}",
        )
    return sent
