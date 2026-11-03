"""Quarterly access review: user x roles x sensitive permissions x last login.
Users inactive for more than 90 days are flagged."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from fpdf import FPDF, FontFace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role, RolePermission, User, UserRole
from app.auth.permissions import SENSITIVE_FIELDS, SENSITIVE_MODULE
from app.auth.principal import CurrentUser, Principal
from app.core.db import get_session
from app.core.errors import ForbiddenError
from app.services import audit
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta
from app.setup import service as settings
from app.sod.models import SodException

router = APIRouter(prefix="/reports", tags=["reporting"])
Session = Annotated[AsyncSession, Depends(get_session)]
JAKARTA = ZoneInfo("Asia/Jakarta")
INACTIVE_DAYS = 90


def _reader(principal: CurrentUser) -> Principal:
    if not (principal.can("users", "view") or principal.can("audit", "view")):
        raise ForbiddenError(
            "PERMISSION_DENIED", "Anda tidak memiliki izin melihat tinjauan akses."
        )
    return principal


Reader = Annotated[Principal, Depends(_reader)]


@dataclass
class Row:
    user_id: str
    full_name: str
    email: str
    active: bool
    roles: list[str] = field(default_factory=list)
    sensitive: list[str] = field(default_factory=list)
    totp_enabled: bool = False
    requires_2fa: bool = False
    last_login_at: datetime | None = None
    days_since_login: int | None = None
    inactive_90: bool = False
    sod_exceptions: int = 0

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


async def build(session: AsyncSession, now: datetime | None = None) -> list[Row]:
    now = now or datetime.now(UTC)
    users = (await session.execute(select(User).order_by(User.full_name))).scalars().all()
    role_rows = (
        await session.execute(
            select(UserRole.user_id, Role.id, Role.name, Role.requires_2fa, UserRole.valid_until)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.is_active.is_(True), UserRole.active_now())
        )
    ).all()
    sensitive_by_role: dict[uuid.UUID, set[str]] = {}
    for rid, action in (
        await session.execute(
            select(RolePermission.role_id, RolePermission.action).where(
                RolePermission.module == SENSITIVE_MODULE
            )
        )
    ).all():
        sensitive_by_role.setdefault(rid, set()).add(SENSITIVE_FIELDS.get(action, action))
    exceptions = dict(
        (
            await session.execute(
                select(SodException.user_id, func.count())
                .where(SodException.status == "approved")
                .group_by(SodException.user_id)
            )
        )
        .tuples()
        .all()
    )
    rows: dict[uuid.UUID, Row] = {
        u.id: Row(
            user_id=str(u.id),
            full_name=u.full_name,
            email=u.email,
            active=u.is_active,
            totp_enabled=u.totp_enabled,
            last_login_at=u.last_login_at,
            sod_exceptions=exceptions.get(u.id, 0),
        )
        for u in users
    }
    for uid, rid, name, req2fa, until in role_rows:
        row = rows.get(uid)
        if row is None:
            continue
        label = f"{name} (s.d. {until.astimezone(JAKARTA):%d/%m/%Y})" if until else name
        row.roles.append(label)
        row.sensitive = sorted(set(row.sensitive) | sensitive_by_role.get(rid, set()))
        row.requires_2fa = row.requires_2fa or req2fa
    created = {u.id: u.created_at for u in users}
    for uid, row in rows.items():
        reference = row.last_login_at or created[uid]
        row.days_since_login = (now - row.last_login_at).days if row.last_login_at else None
        row.inactive_90 = row.active and now - reference > timedelta(days=INACTIVE_DAYS)
        row.roles.sort()
    return list(rows.values())


def _summary(rows: list[Row]) -> dict[str, int]:
    active = [r for r in rows if r.active]
    return {
        "users": len(active),
        "inactive_90": sum(r.inactive_90 for r in active),
        "with_sensitive": sum(bool(r.sensitive) for r in active),
        "missing_2fa": sum(r.requires_2fa and not r.totp_enabled for r in active),
        "with_sod_exception": sum(r.sod_exceptions > 0 for r in active),
    }


@router.get("/access-review")
async def access_review(_: Reader, session: Session) -> dict[str, Any]:
    rows = await build(session)
    return {
        "generated_at": datetime.now(UTC),
        "inactive_days": INACTIVE_DAYS,
        "summary": _summary(rows),
        "rows": [r.as_dict() for r in rows],
    }


def _export_rows(rows: list[Row]) -> list[dict[str, Any]]:
    return [
        {
            **r.as_dict(),
            "roles": ", ".join(r.roles),
            "sensitive": ", ".join(r.sensitive) or "-",
            "status": "Aktif" if r.active else "Nonaktif",
            "totp": "Ya" if r.totp_enabled else "Tidak",
            "flag": "Tidak aktif > 90 hari" if r.inactive_90 else "",
        }
        for r in rows
    ]


@router.get("/access-review.xlsx")
async def access_review_xlsx(principal: Reader, session: Session) -> StreamingResponse:
    rows = await build(session)
    await audit.record(
        session,
        action="export",
        entity_type="report",
        entity_id="access_review",
        actor_id=principal.id,
        after={"format": "xlsx", "rows": len(rows)},
    )
    await session.commit()
    cols = [
        Column("Nama", "full_name", width=26),
        Column("Email", "email", width=30),
        Column("Status", "status", width=10),
        Column("Peran", "roles", width=40),
        Column("Akses data sensitif", "sensitive", width=30),
        Column("2FA", "totp", width=6),
        Column("Login terakhir", "last_login_at", "datetime"),
        Column("Hari sejak login", "days_since_login", "number", 10),
        Column("Pengecualian SoD", "sod_exceptions", "number", 10),
        Column("Catatan", "flag", width=22),
    ]
    return xlsx_response(
        f"tinjauan-akses-{today_jakarta():%Y%m%d}.xlsx", "Tinjauan akses", cols, _export_rows(rows)
    )


class _Pdf(FPDF):
    company = "PT Global Energi KITA"

    def header(self) -> None:
        self.set_font("Helvetica", "B", 13)
        self.cell(0, 7, "Tinjauan Akses Pengguna (triwulanan)", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 8)
        self.cell(
            0,
            5,
            f"{self.company} - dibuat {datetime.now(JAKARTA):%d/%m/%Y %H:%M} WIB",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.cell(0, 5, f"Generated by Nustrad ERP - halaman {self.page_no()}/{{nb}}", align="C")


def _latin1(text: str) -> str:
    # Core PDF fonts are Latin-1 only.
    return text.encode("latin-1", "replace").decode("latin-1")


def render_pdf(rows: list[Row], summary: dict[str, int], company: str) -> bytes:
    pdf = _Pdf(orientation="L", unit="mm", format="A4")
    pdf.company = company
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(
        0,
        4,
        _latin1(
            f"Pengguna aktif: {summary['users']} - "
            f"tidak aktif > {INACTIVE_DAYS} hari: {summary['inactive_90']} - "
            f"akses data sensitif: {summary['with_sensitive']} - "
            f"wajib 2FA tetapi belum aktif: {summary['missing_2fa']} - "
            f"dengan pengecualian SoD: {summary['with_sod_exception']}"
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)
    widths = (48, 92, 52, 12, 26, 18, 29)
    headers = ("Nama / email", "Peran", "Data sensitif", "2FA", "Login terakhir", "Hari", "Catatan")
    pdf.set_font("Helvetica", "", 7)
    with pdf.table(
        col_widths=widths,
        line_height=3.6,
        text_align="LEFT",
        width=sum(widths),
        headings_style=FontFace(emphasis="BOLD", fill_color=(241, 242, 242)),
        repeat_headings=1,
    ) as table:
        table.row(headers)
        for r in rows:
            if not r.active:
                continue
            values = (
                f"{r.full_name}\n{r.email}",
                ", ".join(r.roles) or "-",
                ", ".join(r.sensitive) or "-",
                "Ya" if r.totp_enabled else "Tidak",
                r.last_login_at.astimezone(JAKARTA).strftime("%d/%m/%Y")
                if r.last_login_at
                else "-",
                "-" if r.days_since_login is None else str(r.days_since_login),
                "TIDAK AKTIF > 90 HARI" if r.inactive_90 else "",
            )
            table.row([_latin1(v) for v in values])
    out = pdf.output()
    return bytes(out)


def _filename(ext: str) -> str:
    return f"tinjauan-akses-{today_jakarta():%Y%m%d}.{ext}"


@router.get("/access-review.pdf")
async def access_review_pdf(principal: Reader, session: Session) -> Response:
    rows = await build(session)
    company = (await settings.get(session, settings.COMPANY, settings.DEFAULT_COMPANY)).get(
        "legal_name", "PT Global Energi KITA"
    )
    data = render_pdf(rows, _summary(rows), company)
    await audit.record(
        session,
        action="export",
        entity_type="report",
        entity_id="access_review",
        actor_id=principal.id,
        after={"format": "pdf", "rows": len(rows)},
    )
    await session.commit()
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename("pdf")}"'},
    )
