"""First-login onboarding: privacy notice (UU 27/2022 PDP), profile, role tour."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import PRIVACY_VERSION, Principal, get_principal_allow_pending
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError
from app.dms.models import Attachment
from app.services import audit
from app.setup import service as settings

router = APIRouter(prefix="/auth", tags=["auth"])
Session = Annotated[AsyncSession, Depends(get_session)]
PendingUser = Annotated[Principal, Depends(get_principal_allow_pending)]

PRIVACY_KEY = "privacy_notice"
DEFAULT_NOTICE = """PT Global Energi KITA ("GEK") memproses data pribadi Anda di Nustrad ERP \
sesuai Undang-Undang Nomor 27 Tahun 2022 tentang Pelindungan Data Pribadi.

Data yang diproses: nama, email kantor, nomor telepon, foto, tanda tangan, data kepegawaian \
(jabatan, departemen, sertifikat), dan catatan aktivitas di sistem (jejak audit).

Tujuan: menjalankan proses kerja GEK (persetujuan dokumen, operasi, keuangan, penggajian), \
keamanan akun, dan kepatuhan hukum (perpajakan, ketenagakerjaan, retensi 10 tahun untuk \
catatan keuangan).

Data sensitif (gaji, NIK, NPWP pribadi, rekening bank) hanya dapat dilihat oleh peran yang \
berwenang, dan setiap akses tercatat.

Hak Anda: mengakses, memperbaiki, dan meminta penjelasan atas pemrosesan data Anda melalui \
HCBP Officer GEK. Data tidak dibagikan ke pihak lain kecuali diwajibkan hukum atau untuk \
menjalankan kontrak dengan klien.

Dengan menekan "Saya setuju", Anda menyatakan telah membaca pemberitahuan ini."""


# A user's own photo and signature: readable by signed-in colleagues, writable by the owner.
async def _profile_access(
    _: AsyncSession, principal: Principal, entity_id: str, mode: access.Mode
) -> bool:
    return mode == "read" or entity_id == str(principal.id)


access.register("user_profile", _profile_access)


@router.get("/privacy")
async def privacy(_: PendingUser, session: Session) -> dict[str, str]:
    text = await settings.get(session, PRIVACY_KEY, DEFAULT_NOTICE)
    return {"version": PRIVACY_VERSION, "text": str(text)}


class AcceptIn(BaseModel):
    version: str


@router.post("/privacy/accept", status_code=204)
async def accept_privacy(body: AcceptIn, principal: PendingUser, session: Session) -> Response:
    if body.version != PRIVACY_VERSION:
        raise AppError(
            "PRIVACY_VERSION_CHANGED",
            "Pemberitahuan privasi telah diperbarui. Muat ulang dan baca versi terbaru.",
            status_code=409,
        )
    user = principal.user
    user.privacy_accepted_at, user.privacy_version = datetime.now(UTC), PRIVACY_VERSION
    await audit.record(
        session,
        action="privacy_accepted",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        after={"version": PRIVACY_VERSION},
    )
    await session.commit()
    return Response(status_code=204)


class ProfileIn(BaseModel):
    phone: str = Field(min_length=8, max_length=40, pattern=r"^[0-9+()\- ]+$")
    photo_attachment_id: uuid.UUID | None = None
    signature_attachment_id: uuid.UUID | None = None


async def _own_image(session: AsyncSession, user_id: uuid.UUID, att_id: uuid.UUID | None) -> None:
    if att_id is None:
        return
    att = await session.get(Attachment, att_id)
    if att is None or att.entity_type != "user_profile" or att.entity_id != str(user_id):
        raise AppError(
            "ATTACHMENT_NOT_OWNED", "Gunakan file yang Anda unggah sendiri.", status_code=422
        )
    if not att.content_type.startswith("image/"):
        raise AppError(
            "IMAGE_REQUIRED", "Foto dan tanda tangan harus berupa JPG atau PNG.", status_code=422
        )


@router.put("/profile")
async def save_profile(body: ProfileIn, principal: PendingUser, session: Session) -> dict[str, Any]:
    user = principal.user
    await _own_image(session, user.id, body.photo_attachment_id)
    await _own_image(session, user.id, body.signature_attachment_id)
    before = {
        "phone": user.phone,
        "photo": str(user.photo_attachment_id),
        "signature": str(user.signature_attachment_id),
    }
    user.phone = body.phone.strip()
    user.photo_attachment_id = body.photo_attachment_id
    user.signature_attachment_id = body.signature_attachment_id
    if user.profile_completed_at is None:
        user.profile_completed_at = datetime.now(UTC)
    await audit.record(
        session,
        action="profile_update",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        before=before,
        after={
            "phone": user.phone,
            "photo": str(user.photo_attachment_id),
            "signature": str(user.signature_attachment_id),
        },
    )
    await session.commit()
    return {"phone": user.phone}


@router.post("/tour/done", status_code=204)
async def tour_done(principal: PendingUser, session: Session) -> Response:
    if principal.user.tour_done_at is None:
        principal.user.tour_done_at = datetime.now(UTC)
        await session.commit()
    return Response(status_code=204)


async def has_attachment(session: AsyncSession, att_id: uuid.UUID) -> bool:
    return (
        await session.execute(select(Attachment.id).where(Attachment.id == att_id))
    ).first() is not None
