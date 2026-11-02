from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    totp_code: str | None = Field(default=None, max_length=10)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class TotpVerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class RoleOut(BaseModel):
    code: str
    name: str


class MeOut(BaseModel):
    id: str
    email: str
    full_name: str
    department_id: str | None
    roles: list[RoleOut]
    active_role: str | None
    permissions: dict[str, dict[str, str]]
    pending: list[str]
    totp_enabled: bool
    totp_required: bool
