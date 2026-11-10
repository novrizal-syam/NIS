"""Go-live readiness (10f): one checklist of what must be true before real data goes in —
demo data removed, company and bank details, key role holders, DOA rules, periods, opening
balance, e-mail and a hardened production configuration."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import CurrentUser, Principal
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ForbiddenError
from app.demo import seed as demo
from app.finance import journal_service as js
from app.master.models import FiscalPeriod
from app.services.numbering import today_jakarta
from app.setup import service as settings_store
from app.treasury.models import BankAccount
from app.workflow import engine
from app.workflow.models import DoaRule

router = APIRouter(prefix="/go-live", tags=["admin"])
Session = Annotated[AsyncSession, Depends(get_session)]
READERS = {"super_admin", "admin", "director", "head_of_finance"}
KEY_ROLES = {
    "super_admin": "Super Admin",
    "director": "Direktur",
    "head_of_finance": "Head of Finance",
    "lead_controller": "Lead Controller",
    "ap_accountant": "AP Accountant",
    "cashier": "Kasir",
}


def _reader(principal: CurrentUser) -> Principal:
    if not (READERS & set(principal.role_codes)):
        raise ForbiddenError(
            "GO_LIVE_FORBIDDEN", "Daftar periksa go-live hanya untuk Admin, Direktur dan HoF."
        )
    return principal


Reader = Annotated[Principal, Depends(_reader)]


def _item(key: str, label: str, ok: bool | None, detail: str, link: str | None) -> dict[str, Any]:
    # ok None = manual check (outside the application, e.g. backups).
    return {"key": key, "label": label, "ok": ok, "detail": detail, "link": link}


@router.get("/checklist")
async def checklist(_: Reader, session: Session) -> dict[str, Any]:
    cfg = get_settings()
    items: list[dict[str, Any]] = []

    counts = await demo.demo_counts(session)
    left = sum(counts.values())
    items.append(
        _item(
            "demo",
            "Data demo dihapus",
            left == 0,
            "Tidak ada data demo." if left == 0 else f"Masih ada {left} baris data demo.",
            "/pengaturan",
        )
    )
    company = await settings_store.get(session, settings_store.COMPANY, {}) or {}
    missing = [f for f in ("legal_name", "npwp", "address") if not company.get(f)]
    items.append(
        _item(
            "company",
            "Profil perusahaan lengkap (nama, NPWP, alamat)",
            not missing,
            "Lengkap." if not missing else "Belum diisi: " + ", ".join(missing) + ".",
            "/pengaturan",
        )
    )
    banks = (
        await session.execute(
            select(func.count()).select_from(BankAccount).where(BankAccount.is_active)
        )
    ).scalar_one()
    items.append(
        _item(
            "banks",
            "Rekening bank aktif dan nomornya sudah dicek",
            banks > 0,
            f"{banks} rekening aktif." if banks else "Belum ada rekening bank aktif.",
            "/keuangan/treasury",
        )
    )
    empty = [
        label
        for code, label in KEY_ROLES.items()
        if not await engine.holders_of_role(session, code)
    ]
    items.append(
        _item(
            "roles",
            "Pemegang peran kunci sudah ada",
            not empty,
            "Semua peran kunci terisi." if not empty else "Belum ada: " + ", ".join(empty) + ".",
            "/pengguna",
        )
    )
    rules = (
        await session.execute(select(func.count()).select_from(DoaRule).where(DoaRule.is_active))
    ).scalar_one()
    items.append(
        _item(
            "doa",
            "Aturan DOA (matriks persetujuan) ditinjau",
            rules > 0,
            f"{rules} aturan aktif." if rules else "Belum ada aturan DOA aktif.",
            "/pengaturan/doa",
        )
    )
    year = today_jakarta().year
    periods = (
        await session.execute(
            select(func.count()).select_from(FiscalPeriod).where(FiscalPeriod.year == year)
        )
    ).scalar_one()
    items.append(
        _item(
            "periods",
            f"Periode akuntansi {year} tersedia",
            periods >= 12,
            f"{periods} dari 12 periode.",
            "/master/periods",
        )
    )
    opening = await settings_store.get(session, js.OPENING_KEY, None)
    items.append(
        _item(
            "opening",
            "Saldo awal diposting",
            bool(opening),
            f"Saldo awal per {opening}." if opening else "Belum ada saldo awal.",
            "/pengaturan/go-live",
        )
    )
    items.append(
        _item(
            "email",
            "Pengiriman e-mail aktif",
            bool(cfg.email_provider),
            f"Penyedia: {cfg.email_provider}." if cfg.email_provider else "EMAIL_PROVIDER kosong.",
            None,
        )
    )
    items.append(
        _item(
            "environment",
            "Konfigurasi produksi (APP_ENV=production, HTTPS, kunci enkripsi)",
            cfg.is_production,
            f"APP_ENV={cfg.app_env}.",
            None,
        )
    )
    items.append(
        _item(
            "backup",
            "Backup harian berjalan dan uji restore berhasil",
            None,
            "Periksa log deploy/backup dan jalankan verify_restore.sh sebelum go-live.",
            None,
        )
    )
    auto = [i for i in items if i["ok"] is not None]
    return {
        "ready": all(i["ok"] for i in auto),
        "done": sum(1 for i in auto if i["ok"]),
        "total": len(auto),
        "items": items,
    }
