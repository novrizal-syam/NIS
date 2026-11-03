"""First-run wizard at /setup. Every call needs the one-time SETUP_TOKEN; after finish
every /api/setup endpoint answers 403 forever."""

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.models import User
from app.auth.principal import Principal, get_principal_allow_pending
from app.auth.router import _client, _token_out
from app.auth.schemas import RecoveryCodesOut, TokenOut, TotpSetupOut, TotpVerifyIn
from app.auth.security import validate_password_policy
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError, ConflictError, ForbiddenError
from app.demo import data as demo_data
from app.demo import seed as demo_seed
from app.master.models import CostCenter, Department
from app.services import audit
from app.setup import service

router = APIRouter(prefix="/setup", tags=["setup"])
Session = Annotated[AsyncSession, Depends(get_session)]
STEPS = ("admin", "totp", "company", "departments", "demo")


async def require_setup_token(
    session: Session, x_setup_token: Annotated[str | None, Header()] = None
) -> AsyncSession:
    if await service.is_completed(session):
        raise ForbiddenError("SETUP_DONE", "Penyiapan awal sudah selesai.")
    expected = get_settings().setup_token
    if not expected:
        raise ForbiddenError(
            "SETUP_TOKEN_MISSING", "SETUP_TOKEN belum diatur di server. Hubungi tim IT."
        )
    if not x_setup_token or not hmac.compare_digest(x_setup_token, expected):
        raise ForbiddenError("SETUP_TOKEN_INVALID", "Token penyiapan salah.")
    return session


SetupSession = Annotated[AsyncSession, Depends(require_setup_token)]


async def _progress(session: AsyncSession) -> dict[str, Any]:
    value: dict[str, Any] = await service.get(session, service.SETUP_PROGRESS, {})
    return value


async def _mark(
    session: AsyncSession, step: str, actor: Any, extra: dict[str, Any] | None = None
) -> None:
    progress = await _progress(session)
    progress[step] = True
    await service.put(session, service.SETUP_PROGRESS, progress, actor)
    await audit.record(
        session,
        action="setup_step",
        entity_type="system",
        entity_id="setup",
        actor_id=actor,
        after={"step": step, **(extra or {})},
    )


async def _need(session: AsyncSession, *steps: str) -> None:
    progress = await _progress(session)
    missing = [s for s in steps if not progress.get(s)]
    if missing:
        raise AppError(
            "SETUP_STEP_MISSING",
            f"Selesaikan langkah sebelumnya dulu: {', '.join(missing)}.",
            status_code=409,
        )


async def _setup_admin(
    session: SetupSession, principal: Annotated[Principal, Depends(get_principal_allow_pending)]
) -> Principal:
    if "super_admin" not in principal.role_codes:
        raise ForbiddenError("SUPER_ADMIN_ONLY", "Langkah ini hanya untuk Super Admin penyiapan.")
    return principal


SetupAdmin = Annotated[Principal, Depends(_setup_admin)]


@router.get("/status")
async def status(session: Session) -> dict[str, Any]:
    """Public: lets the web app decide whether to show the wizard."""
    completed = await service.is_completed(session)
    return {
        "setup_completed": completed,
        "token_configured": bool(get_settings().setup_token),
        "steps": {} if completed else await _progress(session),
    }


@router.post("/verify-token", status_code=204)
async def verify_token(_: SetupSession) -> Response:
    return Response(status_code=204)


class AdminIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)


@router.post("/admin")
async def create_admin(
    body: AdminIn, request: Request, response: Response, session: SetupSession
) -> TokenOut:
    if (await _progress(session)).get("admin"):
        raise ConflictError(
            "SETUP_ADMIN_EXISTS", "Super Admin penyiapan sudah dibuat. Masuk untuk melanjutkan."
        )
    validate_password_policy(body.password, email=body.email, strong=True)
    user, _ = await auth_service.create_user(
        session,
        email=body.email,
        full_name=body.full_name,
        role_codes=["super_admin"],
        actor_id=None,
        password=body.password,
    )
    user.must_change_password = False
    await _mark(session, "admin", user.id, {"email": user.email})
    await session.commit()
    _, tokens = await auth_service.login(
        session, email=body.email, password=body.password, totp_code=None, **_client(request)
    )
    return _token_out(response, tokens)


@router.post("/totp/setup")
async def totp_setup(admin: SetupAdmin, session: SetupSession) -> TotpSetupOut:
    await _need(session, "admin")
    return TotpSetupOut.model_validate(await auth_service.start_totp_setup(session, admin))


@router.post("/totp/verify")
async def totp_verify(
    body: TotpVerifyIn, admin: SetupAdmin, session: SetupSession
) -> RecoveryCodesOut:
    codes = await auth_service.confirm_totp_setup(session, admin, body.code)
    await _mark(session, "totp", admin.id)
    await session.commit()
    return RecoveryCodesOut(recovery_codes=codes)


class CompanyIn(BaseModel):
    legal_name: str = Field(min_length=3, max_length=200)
    npwp: str = Field(default="", max_length=25)
    address: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    currency: str = Field(default="IDR", pattern="^[A-Z]{3}$")
    timezone: str = Field(default="Asia/Jakarta", max_length=40)
    language: str = Field(default="id", pattern="^(id|en)$")


@router.get("/company")
async def get_company(_: SetupAdmin, session: SetupSession) -> dict[str, Any]:
    value: dict[str, Any] = await service.get(session, service.COMPANY, service.DEFAULT_COMPANY)
    return value


@router.put("/company")
async def save_company(body: CompanyIn, admin: SetupAdmin, session: SetupSession) -> dict[str, Any]:
    await _need(session, "admin", "totp")
    value = {
        **service.DEFAULT_COMPANY,
        **(await service.get(session, service.COMPANY, {})),
        **body.model_dump(),
    }
    await service.put(session, service.COMPANY, value, admin.id)
    await _mark(session, "company", admin.id, {"legal_name": body.legal_name})
    await session.commit()
    return value


class DeptIn(BaseModel):
    code: str = Field(min_length=2, max_length=10, pattern="^[A-Z0-9]+$")
    name: str = Field(min_length=2, max_length=120)


class DepartmentsIn(BaseModel):
    departments: list[DeptIn] = Field(min_length=1, max_length=50)


@router.get("/departments")
async def suggested_departments(_: SetupAdmin, session: SetupSession) -> list[dict[str, str]]:
    existing = (await session.execute(select(Department).order_by(Department.code))).scalars().all()
    if existing:
        return [{"code": d.code, "name": d.name} for d in existing]
    return [{"code": c, "name": n} for c, n in demo_data.DEPARTMENTS]


@router.put("/departments")
async def save_departments(
    body: DepartmentsIn, admin: SetupAdmin, session: SetupSession
) -> dict[str, int]:
    await _need(session, "admin", "totp", "company")
    codes = [d.code for d in body.departments]
    if len(set(codes)) != len(codes):
        raise AppError("DUPLICATE_CODE", "Kode departemen tidak boleh ganda.", status_code=422)
    created = 0
    for d in body.departments:
        row = (
            await session.execute(select(Department).where(Department.code == d.code))
        ).scalar_one_or_none()
        if row is None:
            session.add(Department(code=d.code, name=d.name, created_by=admin.id))
            await session.flush()  # department before its cost center (FK by code)
            session.add(
                CostCenter(
                    code=f"CC-{d.code}", name=d.name, department_code=d.code, created_by=admin.id
                )
            )
            created += 1
        else:
            row.name = d.name
    await session.flush()
    await _mark(session, "departments", admin.id, {"departments": codes})
    await session.commit()
    return {"created": created, "total": len(codes)}


class DemoIn(BaseModel):
    load_demo: bool


@router.post("/demo")
async def demo(body: DemoIn, admin: SetupAdmin, session: SetupSession) -> dict[str, Any]:
    await _need(session, "admin", "totp", "company", "departments")
    counts: dict[str, int] = {}
    if body.load_demo and not await demo_seed.demo_exists(session):
        counts = (
            await demo_seed.load(
                session, password=demo_data.DEMO_PASSWORD_DEFAULT, actor_id=admin.id
            )
        ).counts
    await _mark(session, "demo", admin.id, {"load_demo": body.load_demo})
    await session.commit()
    return {"loaded": counts}


@router.post("/finish")
async def finish(admin: SetupAdmin, session: SetupSession) -> dict[str, bool]:
    await _need(session, *STEPS)
    await service.put(session, service.SETUP_COMPLETED, True, admin.id)
    await audit.record(
        session,
        action="setup_completed",
        entity_type="system",
        entity_id="setup",
        actor_id=admin.id,
    )
    await session.commit()
    return {"setup_completed": True}


async def setup_admin_exists(session: AsyncSession) -> bool:
    return (await session.execute(select(User.id).limit(1))).first() is not None
