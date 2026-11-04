"""GEK letterhead for documents GEK sends (company profile + logo from the DMS)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.crm.quotation_pdf import Letterhead
from app.dms.models import Attachment
from app.services.storage import Storage
from app.setup import service as settings_store


async def load(session: AsyncSession, storage: Storage) -> Letterhead:
    company = {
        **settings_store.DEFAULT_COMPANY,
        **(await settings_store.get(session, settings_store.COMPANY, {}) or {}),
    }
    logo = None
    logo_id = company.get("logo_attachment_id")
    if logo_id:
        att = await session.get(Attachment, uuid.UUID(str(logo_id)))
        if att is not None and att.content_type in ("image/png", "image/jpeg"):
            try:
                logo = (await storage.get(att.storage_key)).data
            except NotFoundError:
                logo = None
    return Letterhead(company=company, logo=logo)
