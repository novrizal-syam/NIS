import hashlib
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, NotFoundError
from app.dms.models import Attachment
from app.services import audit
from app.services.storage import Storage

MAX_BYTES = 20 * 1024 * 1024
# Checked against the file's own bytes, not the name the browser sends.
SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
EXTENSIONS = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}


def sniff(data: bytes) -> str:
    for content_type, magics in SIGNATURES.items():
        if any(data.startswith(m) for m in magics):
            return content_type
    raise AppError(
        "FILE_TYPE_NOT_ALLOWED",
        "Hanya file PDF, JPG, atau PNG yang dapat diunggah.",
        status_code=415,
    )


def safe_name(name: str, content_type: str) -> str:
    base = re.sub(r"[^\w.\- ]+", "_", name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip(" ._")
    base = base[:120] or "lampiran"
    ext = EXTENSIONS[content_type]
    if not base.lower().endswith((ext, ".jpeg") if ext == ".jpg" else (ext,)):
        base += ext
    return base


async def upload(
    session: AsyncSession,
    storage: Storage,
    principal: Principal,
    *,
    entity_type: str,
    entity_id: str,
    filename: str,
    data: bytes,
    replaces: uuid.UUID | None = None,
    note: str | None = None,
) -> Attachment:
    if len(data) == 0:
        raise AppError("FILE_EMPTY", "File kosong.", status_code=422)
    if len(data) > MAX_BYTES:
        raise AppError("FILE_TOO_LARGE", "Ukuran file maksimal 20 MB.", status_code=413)
    content_type = sniff(data)
    if replaces is not None:
        previous = (
            await session.execute(
                select(Attachment)
                .where(
                    Attachment.group_id == replaces,
                    Attachment.entity_type == entity_type,
                    Attachment.entity_id == entity_id,
                )
                .order_by(Attachment.version.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if previous is None:
            raise NotFoundError(
                "ATTACHMENT_NOT_FOUND", "Lampiran yang akan diganti tidak ditemukan."
            )
        group_id, version = replaces, previous.version + 1
    else:
        group_id, version = uuid.uuid4(), 1
    name = safe_name(filename, content_type)
    key = f"dms/{entity_type}/{entity_id}/{group_id}/v{version}-{uuid.uuid4().hex[:8]}-{name}"
    await storage.put(key, data, content_type)
    row = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        group_id=group_id,
        version=version,
        filename=name,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        note=(note or "").strip() or None,
        created_by=principal.id,
    )
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        action="upload",
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=principal.id,
        after={"file": name, "version": version, "size": len(data), "sha256": row.sha256},
    )
    return row


async def latest(
    session: AsyncSession, entity_type: str, entity_id: str
) -> list[tuple[Attachment, int]]:
    """Latest version of every non-archived file, with its version count."""
    counts = (
        select(
            Attachment.group_id, func.max(Attachment.version).label("v"), func.count().label("n")
        )
        .where(Attachment.entity_type == entity_type, Attachment.entity_id == entity_id)
        .group_by(Attachment.group_id)
        .subquery()
    )
    rows = await session.execute(
        select(Attachment, counts.c.n)
        .join(
            counts, (counts.c.group_id == Attachment.group_id) & (counts.c.v == Attachment.version)
        )
        .where(Attachment.archived_at.is_(None))
        .order_by(Attachment.uploaded_at.desc())
    )
    return [(a, int(n)) for a, n in rows.all()]


async def archive(session: AsyncSession, principal: Principal, att: Attachment) -> None:
    """Archive the whole file (all versions). Kept for retention, hidden from the list."""
    now = datetime.now(UTC)
    rows = (
        await session.execute(select(Attachment).where(Attachment.group_id == att.group_id))
    ).scalars()
    for r in rows:
        r.archived_at, r.archived_by = now, principal.id
    await audit.record(
        session,
        action="archive",
        entity_type=att.entity_type,
        entity_id=att.entity_id,
        actor_id=principal.id,
        before={"file": att.filename, "version": att.version},
    )
