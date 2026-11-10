"""Integrations API (10b): status of every adapter, modes, WhatsApp outbox, Coretax via PJAP."""

import io
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal, require
from app.billing import invoice_service
from app.billing.models import CustomerInvoice
from app.core.db import get_session
from app.core.errors import AppError, NotFoundError
from app.integrations import pjap, whatsapp
from app.integrations.models import WhatsAppMessage
from app.services import audit, email
from app.setup import service as settings_store
from app.treasury import adapters as bank_adapters
from app.treasury.models import BankAccount

router = APIRouter(prefix="/integrations", tags=["integrations"])
Session = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[Principal, Depends(require("settings", "edit"))]
TaxUser = Annotated[Principal, Depends(require("tax", "post"))]


async def integration_status(session: AsyncSession) -> list[dict[str, Any]]:
    banks = list(
        (
            await session.execute(select(BankAccount).where(BankAccount.is_active.is_(True)))
        ).scalars()
    )
    psre = await settings_store.get(session, "psre.provider", None) or "internal"
    meterai = await settings_store.get(session, "emeterai.provider", None) or "internal"
    mail = email.provider()
    return [
        {
            "key": "coretax_pjap",
            "label": "Coretax DJP via PJAP (e-Faktur)",
            "mode": "live" if pjap.client() else "file",
            "detail": "Unggah XML lewat PJAP"
            if pjap.client()
            else "Unduh XML Coretax, impor manual di Coretax",
            "config": "PJAP_BASE_URL, PJAP_API_KEY",
        },
        {
            "key": "bank",
            "label": "Bank (file transfer & host-to-host)",
            "mode": "live"
            if any(bank_adapters.get(b.adapter).host_to_host for b in banks)
            else "file",
            "detail": ", ".join(f"{b.code}: {bank_adapters.get(b.adapter).label}" for b in banks)
            or "-",
            "config": "Adapter per rekening (Keuangan > Treasury)",
        },
        {
            "key": "psre",
            "label": "Tanda tangan elektronik (PSrE)",
            "mode": "live" if psre != "internal" else "manual",
            "detail": f"Penyedia: {psre}",
            "config": "Setelan psre.provider",
        },
        {
            "key": "emeterai",
            "label": "e-Meterai (Peruri)",
            "mode": "live" if meterai != "internal" else "manual",
            "detail": f"Penyedia: {meterai}",
            "config": "Setelan emeterai.provider",
        },
        {
            "key": "smtp",
            "label": "Email (SMTP / Resend)",
            "mode": "live" if mail else "manual",
            "detail": f"Penyedia: {mail}"
            if mail
            else "Belum diatur: email tercatat, tidak terkirim",
            "config": "EMAIL_PROVIDER, SMTP_HOST, SMTP_USER, SMTP_PASSWORD",
        },
        {
            "key": "whatsapp",
            "label": "WhatsApp Business API",
            "mode": "live" if whatsapp.live() else "manual",
            "detail": "Cloud API"
            if whatsapp.live()
            else "Outbox dengan tautan wa.me untuk dikirim manual",
            "config": "WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TOKEN; setelan whatsapp.notify_kinds",
        },
    ]


@router.get("")
async def get_status(_: Admin, session: Session) -> dict[str, Any]:
    return {
        "integrations": await integration_status(session),
        "settings": {
            "psre.provider": await settings_store.get(session, "psre.provider", None) or "internal",
            "emeterai.provider": await settings_store.get(session, "emeterai.provider", None)
            or "internal",
            "whatsapp.notify_kinds": sorted(await whatsapp.notify_kinds(session)),
        },
    }


class SettingsIn(BaseModel):
    psre_provider: str = Field(default="internal", max_length=30)
    emeterai_provider: str = Field(default="internal", max_length=30)
    whatsapp_notify_kinds: list[str] = Field(default_factory=list, max_length=50)


@router.put("/settings")
async def put_settings(body: SettingsIn, actor: Admin, session: Session) -> dict[str, Any]:
    from app.billing import psre
    from app.letters import emeterai

    if (
        body.psre_provider not in psre._PROVIDERS
        or body.emeterai_provider not in emeterai._PROVIDERS
    ):
        raise AppError(
            "PROVIDER_UNKNOWN",
            "Penyedia belum terpasang di sistem; gunakan 'internal' sampai adaptornya tersedia.",
            status_code=422,
        )
    await settings_store.put(session, "psre.provider", body.psre_provider, actor.id)
    await settings_store.put(session, "emeterai.provider", body.emeterai_provider, actor.id)
    await settings_store.put(
        session, whatsapp.KINDS_KEY, sorted(set(body.whatsapp_notify_kinds)), actor.id
    )
    await audit.record(
        session,
        action="update",
        entity_type="integrations",
        entity_id="settings",
        actor_id=actor.id,
        after=body.model_dump(),
    )
    await session.commit()
    return await get_status(actor, session)


# ---------------------------------------------------------------- WhatsApp outbox


@router.get("/whatsapp/outbox")
async def outbox(_: Admin, session: Session, status: str | None = None) -> list[dict[str, Any]]:
    stmt = select(WhatsAppMessage).order_by(WhatsAppMessage.created_at.desc()).limit(200)
    rows = list((await session.execute(stmt)).scalars())
    return [
        {
            "id": str(m.id),
            "to": m.to_phone,
            "body": m.body,
            "kind": m.kind,
            "status": m.status,
            "error": m.error,
            "wa_link": whatsapp.wa_link(m) if m.status in ("manual", "failed") else None,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
        if status is None or m.status == status
    ]


@router.post("/whatsapp/{mid}/sent")
async def mark_sent(mid: uuid.UUID, actor: Admin, session: Session) -> dict[str, Any]:
    m = await whatsapp.mark_sent(session, mid)
    if m is None:
        raise NotFoundError("NOT_FOUND", "Pesan tidak ditemukan.")
    await session.commit()
    return {"id": str(m.id), "status": m.status}


# ---------------------------------------------------------------- Coretax via PJAP


class EfakturIn(BaseModel):
    invoice_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    mode: Literal["auto", "file"] = "auto"


@router.post("/pjap/efaktur", response_model=None)
async def efaktur(body: EfakturIn, actor: TaxUser, session: Session) -> Any:
    """Live: upload to the PJAP and return its reference. File mode: the Coretax XML."""
    invoices = list(
        (
            await session.execute(
                select(CustomerInvoice).where(CustomerInvoice.id.in_(body.invoice_ids))
            )
        ).scalars()
    )
    if len(invoices) != len(set(body.invoice_ids)):
        raise NotFoundError("INVOICE_NOT_FOUND", "Sebagian invoice tidak ditemukan.")
    missing = [i.number for i in invoices if not i.faktur_number]
    if missing:
        raise AppError(
            "FAKTUR_MISSING", f"Nomor faktur belum ada: {', '.join(missing)}.", status_code=422
        )
    xml = await invoice_service.coretax_xml(session, invoices)
    batch = f"EF-{datetime.now(UTC):%Y%m%d%H%M%S}"
    c = pjap.client()
    if c is None or body.mode == "file":
        await audit.record(
            session,
            action="export",
            entity_type="efaktur",
            entity_id=batch,
            actor_id=actor.id,
            after={"invoices": len(invoices), "mode": "file"},
        )
        await session.commit()
        return StreamingResponse(
            io.BytesIO(xml),
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{batch}.xml"'},
        )
    res = await c.upload_efaktur(xml, batch=batch)
    await audit.record(
        session,
        action="pjap_upload",
        entity_type="efaktur",
        entity_id=batch,
        actor_id=actor.id,
        after={
            "invoices": [i.number for i in invoices],
            "reference": res.reference,
            "status": res.status,
        },
    )
    await session.commit()
    return {
        "batch": batch,
        "reference": res.reference,
        "status": res.status,
        "message": res.message,
    }
