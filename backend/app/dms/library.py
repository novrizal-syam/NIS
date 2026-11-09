"""Document library (09): categories, tags, folders, role/project restrictions, retention,
legal hold, expiring share links, full-text search, expiry alerts.

Access to a library document:
  read   dms view with scope ALL (or the creator, or a member of the document's project) AND,
         when `allowed_roles` is set, holding one of those roles (HR files default to HCBP and
         Director). Super Admin always.
  write  the creator or dms edit with scope ALL, within the same role restriction.
Retention: a document cannot be archived before `retention_until` (10 years for finance/tax,
setting `dms.retention_years`) or while on legal hold.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Scope
from app.auth.principal import Principal
from app.core import access
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.dms.models import AccessLog, Attachment, LibraryDocument, ShareLink
from app.notifications import service as notifications
from app.services import audit
from app.services.audit import AuditAction
from app.services.numbering import today_jakarta
from app.setup import service as settings_store
from app.workflow import engine

DOC = "library_doc"
CATEGORIES = {
    "legal": "Dokumen legal perusahaan",
    "contract": "Kontrak",
    "certificate": "Sertifikat aset",
    "manual": "Manual OEM",
    "msds": "MSDS",
    "project": "Folder proyek",
    "tender": "Dokumen tender (pakai ulang)",
    "hr": "Berkas SDM (terbatas)",
    "finance": "Keuangan",
    "tax": "Pajak",
    "other": "Lainnya",
}
RETENTION_KEY = "dms.retention_years"
DEFAULT_RETENTION = {"finance": 10, "tax": 10, "legal": 10, "contract": 10, "hr": 10, "*": 5}
HR_DEFAULT_ROLES = ["hcbp_officer", "director"]
EXPIRY_ALERT_DAYS = 60
MAX_SHARE_DAYS = 30


async def retention_years(session: AsyncSession, category: str) -> int:
    cfg = {**DEFAULT_RETENTION, **(await settings_store.get(session, RETENTION_KEY, {}) or {})}
    return int(cfg.get(category, cfg["*"]))


def _role_ok(p: Principal, doc: LibraryDocument) -> bool:
    return (
        not doc.allowed_roles
        or "super_admin" in p.role_codes
        or bool(p.role_codes & set(doc.allowed_roles))
    )


def can_read(p: Principal, doc: LibraryDocument) -> bool:
    if not p.can("dms", "view") or not _role_ok(p, doc):
        return False
    return (
        p.scope_for("dms", "view") == Scope.ALL
        or doc.created_by == p.id
        or (doc.project_id is not None and doc.project_id in p.project_ids)
    )


def can_write(p: Principal, doc: LibraryDocument) -> bool:
    return _role_ok(p, doc) and (doc.created_by == p.id or p.scope_for("dms", "edit") == Scope.ALL)


async def _access(session: AsyncSession, p: Principal, eid: str, mode: access.Mode) -> bool:
    try:
        doc = await session.get(LibraryDocument, uuid.UUID(eid))
    except ValueError:
        return False
    if doc is None:
        return False
    return can_read(p, doc) if mode == "read" else can_write(p, doc) and doc.archived_at is None


access.register(DOC, _access)


async def create(session: AsyncSession, actor: Principal, data: dict[str, Any]) -> LibraryDocument:
    if data["category"] not in CATEGORIES:
        raise AppError("CATEGORY_INVALID", "Kategori dokumen tidak dikenal.", status_code=422)
    roles = list(data.get("allowed_roles") or [])
    if data["category"] == "hr" and not roles:
        roles = HR_DEFAULT_ROLES
    years = await retention_years(session, data["category"])
    today = today_jakarta()
    doc = LibraryDocument(
        category=data["category"],
        title=data["title"].strip(),
        folder=(data.get("folder") or "").strip() or None,
        tags=sorted({t.strip().lower() for t in data.get("tags") or [] if t.strip()}),
        description=data.get("description"),
        project_id=data.get("project_id"),
        allowed_roles=roles,
        issued_on=data.get("issued_on"),
        expiry_date=data.get("expiry_date"),
        retention_until=date(today.year + years, today.month, min(today.day, 28)),
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
        after={
            "title": doc.title,
            "category": doc.category,
            "retention_until": doc.retention_until.isoformat(),
        },
    )
    return doc


async def update(
    session: AsyncSession, actor: Principal, doc: LibraryDocument, data: dict[str, Any]
) -> LibraryDocument:
    if not can_write(actor, doc):
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin mengubah dokumen ini.")
    before = {"title": doc.title, "tags": doc.tags, "expiry_date": str(doc.expiry_date)}
    for k in ("title", "folder", "description", "issued_on", "expiry_date", "project_id"):
        if k in data:
            setattr(doc, k, data[k])
    if "tags" in data:
        doc.tags = sorted({t.strip().lower() for t in data["tags"] or [] if t.strip()})
    if "allowed_roles" in data:
        doc.allowed_roles = list(data["allowed_roles"] or []) or (
            HR_DEFAULT_ROLES if doc.category == "hr" else []
        )
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=doc.id,
        actor_id=actor.id,
        before=before,
        after={"title": doc.title, "tags": doc.tags, "expiry_date": str(doc.expiry_date)},
    )
    return doc


async def set_legal_hold(
    session: AsyncSession, actor: Principal, doc: LibraryDocument, hold: bool, reason: str | None
) -> LibraryDocument:
    if not (p_is_legal(actor)):
        raise ForbiddenError(
            "PERMISSION_DENIED", "Legal hold diatur oleh Legal & Liaison Officer atau Direktur."
        )
    if hold and len((reason or "").strip()) < 5:
        raise AppError("REASON_REQUIRED", "Tulis alasan legal hold.", status_code=422)
    doc.legal_hold, doc.legal_hold_reason = hold, (reason or "").strip() or None
    await session.flush()
    await audit.record(
        session,
        action="legal_hold" if hold else "legal_hold_released",
        entity_type=DOC,
        entity_id=doc.id,
        actor_id=actor.id,
        after={"legal_hold": hold, "reason": doc.legal_hold_reason},
    )
    return doc


def p_is_legal(p: Principal) -> bool:
    return bool(p.role_codes & {"legal_liaison", "director", "super_admin"})


async def archive(session: AsyncSession, actor: Principal, doc: LibraryDocument) -> None:
    if not can_write(actor, doc):
        raise ForbiddenError("PERMISSION_DENIED", "Anda tidak berizin mengarsipkan dokumen ini.")
    if doc.legal_hold:
        raise ConflictError("LEGAL_HOLD", "Dokumen dalam legal hold; tidak boleh diarsipkan.")
    if today_jakarta() < doc.retention_until:
        raise ConflictError(
            "RETENTION_ACTIVE",
            f"Masa retensi berlaku sampai {doc.retention_until:%d/%m/%Y}; dokumen belum boleh "
            "diarsipkan.",
        )
    doc.archived_at = datetime.now(UTC)
    await session.flush()
    await audit.record(
        session, action="archive", entity_type=DOC, entity_id=doc.id, actor_id=actor.id
    )


def protected(doc: LibraryDocument | None) -> str | None:
    """Reason a file of this document may not be archived (attachments router guard)."""
    if doc is None:
        return None
    if doc.legal_hold:
        return "Dokumen dalam legal hold; file tidak boleh diarsipkan."
    if today_jakarta() < doc.retention_until:
        return f"Masa retensi berlaku sampai {doc.retention_until:%d/%m/%Y}."
    return None


# ---------------------------------------------------------------- share links


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def share(
    session: AsyncSession, actor: Principal, att: Attachment, days: int, note: str | None
) -> tuple[ShareLink, str]:
    if not 1 <= days <= MAX_SHARE_DAYS:
        raise AppError(
            "SHARE_DAYS", f"Masa berlaku tautan 1-{MAX_SHARE_DAYS} hari.", status_code=422
        )
    if att.entity_type == DOC:
        doc = await session.get(LibraryDocument, uuid.UUID(att.entity_id))
        if doc is not None and (doc.category == "hr" or doc.allowed_roles):
            raise ForbiddenError(
                "SHARE_RESTRICTED", "Dokumen terbatas tidak dapat dibagikan lewat tautan."
            )
    token = secrets.token_urlsafe(32)
    link = ShareLink(
        attachment_id=att.id,
        token_hash=_hash(token),
        expires_at=datetime.now(UTC) + timedelta(days=days),
        created_by=actor.id,
        note=(note or "").strip() or None,
    )
    session.add(link)
    session.add(
        AccessLog(attachment_id=att.id, user_id=actor.id, action="share", detail=f"{days} hari")
    )
    await session.flush()
    await audit.record(
        session,
        action="share",
        entity_type=att.entity_type,
        entity_id=att.entity_id,
        actor_id=actor.id,
        after={"file": att.filename, "expires_at": link.expires_at.isoformat()},
    )
    return link, token


async def resolve_share(session: AsyncSession, token: str) -> tuple[ShareLink, Attachment]:
    link = (
        await session.execute(
            select(ShareLink).where(ShareLink.token_hash == _hash(token)).with_for_update()
        )
    ).scalar_one_or_none()
    if link is None or link.revoked_at is not None or link.expires_at < datetime.now(UTC):
        raise NotFoundError("SHARE_EXPIRED", "Tautan tidak berlaku atau sudah kedaluwarsa.")
    att = await session.get(Attachment, link.attachment_id)
    if att is None or att.archived_at is not None:
        raise NotFoundError("SHARE_EXPIRED", "File tidak tersedia lagi.")
    link.downloads += 1
    session.add(
        AccessLog(attachment_id=att.id, user_id=None, action="download", detail="share link")
    )
    await session.flush()
    return link, att


async def revoke_share(session: AsyncSession, actor: Principal, link: ShareLink) -> None:
    link.revoked_at = datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        action="share_revoked",
        entity_type="attachment",
        entity_id=link.attachment_id,
        actor_id=actor.id,
    )


# ---------------------------------------------------------------- search


async def search(
    session: AsyncSession,
    p: Principal,
    q: str,
    *,
    category: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """Full text over library titles, tags, descriptions and file contents (PDF text layer),
    plus any other attachment the user may read; at most 50 hits."""
    q = q.strip()
    if len(q) < 2:
        raise AppError("QUERY_SHORT", "Ketik minimal 2 karakter.", status_code=422)
    tsq = func.plainto_tsquery("simple", q)
    like = f"%{q}%"
    doc_vec = func.to_tsvector(
        "simple",
        func.coalesce(LibraryDocument.title, "")
        + literal_column("' '")
        + func.coalesce(LibraryDocument.description, "")
        + literal_column("' '")
        + func.array_to_string(LibraryDocument.tags, " "),
    )
    stmt = select(LibraryDocument).where(
        LibraryDocument.archived_at.is_(None),
        or_(doc_vec.op("@@")(tsq), LibraryDocument.title.ilike(like)),
    )
    if category:
        stmt = stmt.where(LibraryDocument.category == category)
    if tag:
        stmt = stmt.where(LibraryDocument.tags.contains([tag.lower()]))
    hits: list[dict[str, Any]] = []
    for doc in (await session.execute(stmt.limit(200))).scalars():
        if can_read(p, doc):
            hits.append(
                {
                    "kind": "library",
                    "id": str(doc.id),
                    "title": doc.title,
                    "category": doc.category,
                    "snippet": doc.description,
                }
            )
    file_vec = func.to_tsvector(
        "simple",
        func.coalesce(Attachment.filename, "")
        + literal_column("' '")
        + func.coalesce(Attachment.note, "")
        + literal_column("' '")
        + func.coalesce(Attachment.text_content, ""),
    )
    rows = (
        await session.execute(
            select(
                Attachment,
                func.ts_headline(
                    "simple", func.coalesce(Attachment.text_content, Attachment.filename), tsq
                ).label("snip"),
            )
            .where(
                Attachment.archived_at.is_(None),
                or_(file_vec.op("@@")(tsq), Attachment.filename.ilike(like)),
            )
            .order_by(Attachment.uploaded_at.desc())
            .limit(300)
        )
    ).all()
    seen: set[uuid.UUID] = set()
    for att, snip in rows:
        if att.group_id in seen:
            continue
        seen.add(att.group_id)
        if category and att.entity_type == DOC:
            owner = await session.get(LibraryDocument, uuid.UUID(att.entity_id))
            if owner is None or owner.category != category:
                continue
        try:
            await access.require(session, p, att.entity_type, att.entity_id, "read")
        except (NotFoundError, ForbiddenError):
            continue  # not visible to this user
        hits.append(
            {
                "kind": "file",
                "id": str(att.id),
                "title": att.filename,
                "entity_type": att.entity_type,
                "entity_id": att.entity_id,
                "snippet": (snip or "")[:300],
            }
        )
        if len(hits) >= 50:
            break
    return hits[:50]


# ---------------------------------------------------------------- alerts


async def expiry_alerts(session: AsyncSession, today: date | None = None) -> int:
    """Library documents expiring within 60 days (and expired): Legal & creator."""
    today = today or today_jakarta()
    legal = await engine.holders_of_role(session, "legal_liaison")
    sent = 0
    rows = (
        await session.execute(
            select(LibraryDocument).where(
                LibraryDocument.archived_at.is_(None),
                LibraryDocument.expiry_date.is_not(None),
                LibraryDocument.expiry_date <= today + timedelta(days=EXPIRY_ALERT_DAYS),
            )
        )
    ).scalars()
    for doc in rows:
        assert doc.expiry_date is not None
        left = (doc.expiry_date - today).days
        stage = "expired" if left < 0 else "60"
        users = list({*legal, *([doc.created_by] if doc.created_by else [])})
        sent += await notifications.notify(
            session,
            users,
            kind="library_expiry",
            title=f"{doc.title} "
            + ("sudah kedaluwarsa" if left < 0 else f"berakhir dalam {left} hari"),
            body=(
                f"{CATEGORIES.get(doc.category, doc.category)} berlaku sampai "
                f"{doc.expiry_date:%d/%m/%Y}."
            ),
            link=f"/dokumen?doc={doc.id}",
            dedupe_key=f"library-expiry-{doc.id}-{doc.expiry_date}-{stage}",
        )
    return sent


async def access_log(session: AsyncSession, attachment_ids: list[uuid.UUID]) -> list[AccessLog]:
    if not attachment_ids:
        return []
    return list(
        (
            await session.execute(
                select(AccessLog)
                .where(AccessLog.attachment_id.in_(attachment_ids))
                .order_by(AccessLog.at.desc())
                .limit(200)
            )
        ).scalars()
    )
