from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.principal import CurrentUser, Principal, get_principal_allow_pending
from app.auth.schemas import (
    ChangePasswordIn,
    LoginIn,
    MeOut,
    TokenOut,
    TotpSetupOut,
    TotpVerifyIn,
)
from app.core.config import get_settings
from app.core.db import get_session

router = APIRouter(prefix="/auth", tags=["auth"])
Session = Annotated[AsyncSession, Depends(get_session)]
PendingUser = Annotated[Principal, Depends(get_principal_allow_pending)]
COOKIE_PATH = "/api/auth"


def _client(request: Request) -> dict[str, Any]:
    return {
        "user_agent": request.headers.get("user-agent"),
        "ip": request.client.host if request.client else None,
    }


def _set_refresh_cookie(response: Response, tokens: service.IssuedTokens) -> None:
    s = get_settings()
    response.set_cookie(
        s.refresh_cookie_name,
        tokens.refresh_token,
        expires=tokens.refresh_expires_at,
        path=COOKIE_PATH,
        httponly=True,
        secure=s.is_production,
        samesite="lax",
    )


def _token_out(response: Response, tokens: service.IssuedTokens) -> TokenOut:
    _set_refresh_cookie(response, tokens)
    response.headers["cache-control"] = "no-store"
    return TokenOut(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, session: Session) -> TokenOut:
    _, tokens = await service.login(
        session,
        email=body.email,
        password=body.password,
        totp_code=body.totp_code,
        **_client(request),
    )
    return _token_out(response, tokens)


@router.post("/refresh")
async def refresh(request: Request, response: Response, session: Session) -> TokenOut:
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    _, tokens = await service.refresh(session, raw, **_client(request))
    return _token_out(response, tokens)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, session: Session) -> Response:
    s = get_settings()
    await service.logout(session, request.cookies.get(s.refresh_cookie_name))
    response = Response(status_code=204)
    response.delete_cookie(s.refresh_cookie_name, path=COOKIE_PATH)
    return response


@router.get("/me")
async def me(principal: PendingUser, session: Session) -> MeOut:
    return MeOut.model_validate(await service.me(session, principal))


@router.post("/change-password")
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    principal: PendingUser,
    session: Session,
) -> TokenOut:
    tokens = await service.change_password(
        session, principal, current=body.current_password, new=body.new_password, **_client(request)
    )
    return _token_out(response, tokens)


@router.post("/totp/setup")
async def totp_setup(principal: PendingUser, session: Session) -> TotpSetupOut:
    return TotpSetupOut.model_validate(await service.start_totp_setup(session, principal))


@router.post("/totp/verify", status_code=204)
async def totp_verify(body: TotpVerifyIn, principal: PendingUser, session: Session) -> Response:
    await service.confirm_totp_setup(session, principal, body.code)
    return Response(status_code=204)


@router.get("/ping")
async def ping(principal: CurrentUser) -> dict[str, str]:
    """Cheap check that the session is fully usable (no pending steps)."""
    return {"user_id": str(principal.id)}
