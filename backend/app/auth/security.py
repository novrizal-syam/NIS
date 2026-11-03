"""Password hashing (argon2id), JWT access tokens, refresh tokens, TOTP, secret encryption."""

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
import segno
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.errors import AppError

_hasher = PasswordHasher()  # argon2id with library defaults
# Verified against when the email is unknown, so response time does not reveal accounts.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")
JWT_ALG = "HS256"
ACCESS_TYPE = "access"


# --- passwords ------------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def validate_password_policy(password: str, *, email: str, strong: bool = False) -> None:
    """Default: 10+ chars, letters and digits. `strong` (Super Admin): 12+ chars with upper,
    lower, digit and symbol."""
    problems = []
    min_len = 12 if strong else 10
    if len(password) < min_len:
        problems.append(f"Kata sandi minimal {min_len} karakter.")
    if strong and not (
        re.search(r"\d", password)
        and re.search(r"[a-z]", password)
        and re.search(r"[A-Z]", password)
        and re.search(r"[^A-Za-z0-9]", password)
    ):
        problems.append("Kata sandi harus berisi huruf besar, huruf kecil, angka, dan simbol.")
    if not strong and (not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password)):
        problems.append("Kata sandi harus berisi huruf dan angka.")
    name = email.split("@")[0].lower() if email else ""
    if len(name) >= 3 and name in password.lower():
        problems.append("Kata sandi tidak boleh memuat nama email Anda.")
    if problems:
        raise AppError("WEAK_PASSWORD", " ".join(problems), status_code=422)


def generate_temp_password() -> str:
    # 14 chars, always has letters and digits; shown once to the admin.
    while True:
        pwd = secrets.token_urlsafe(10)
        if re.search(r"[A-Za-z]", pwd) and re.search(r"\d", pwd):
            return pwd


# --- recovery codes ---------------------------------------------------------------------------

RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion


def new_recovery_codes(count: int = 10) -> list[str]:
    return [
        "-".join("".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(4)) for _ in range(2))
        for _ in range(count)
    ]


def hash_recovery_code(code: str) -> str:
    normalized = code.strip().upper().replace(" ", "").replace("-", "")
    key = ("recovery:" + get_settings().secret_key).encode()
    return hmac.new(key, normalized.encode(), hashlib.sha256).hexdigest()


# --- access tokens --------------------------------------------------------------------------


def create_access_token(user_id: uuid.UUID, *, now: datetime | None = None) -> tuple[str, int]:
    s = get_settings()
    issued = now or datetime.now(UTC)
    ttl = timedelta(minutes=s.access_token_minutes)
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TYPE,
        "iat": issued,
        "exp": issued + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.secret_key, algorithm=JWT_ALG), int(ttl.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=[JWT_ALG],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            "TOKEN_EXPIRED", "Sesi berakhir. Silakan masuk lagi.", status_code=401
        ) from exc
    except jwt.PyJWTError as exc:
        raise AppError(
            "INVALID_TOKEN", "Sesi tidak valid. Silakan masuk lagi.", status_code=401
        ) from exc
    if payload.get("type") != ACCESS_TYPE:
        raise AppError("INVALID_TOKEN", "Sesi tidak valid. Silakan masuk lagi.", status_code=401)
    return payload


# --- refresh tokens (opaque, stored as SHA-256) ---------------------------------------------


def new_refresh_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- secrets at rest ------------------------------------------------------------------------


def _fernet() -> Fernet:
    key = hashlib.sha256(("totp:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise AppError(
            "TOTP_SECRET_INVALID",
            "Kunci 2FA tidak dapat dibaca. Hubungi admin untuk reset 2FA.",
            status_code=500,
        ) from exc


# --- TOTP -----------------------------------------------------------------------------------

TOTP_STEP = 30


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().totp_issuer)


def totp_qr_svg(uri: str) -> str:
    return str(segno.make(uri, error="m").svg_inline(scale=5, dark="#1A1A1A", light="#FFFFFF"))


def verify_totp(
    secret: str, code: str, *, last_step: int | None, now: datetime | None = None
) -> int | None:
    """Return the matched time step, or None. Accepts +-1 step of clock drift; a step at or
    before `last_step` is rejected so a code cannot be replayed."""
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return None
    ts = (now or datetime.now(UTC)).timestamp()
    totp = pyotp.TOTP(secret)
    current = int(ts // TOTP_STEP)
    for step in (current - 1, current, current + 1):
        if last_step is not None and step <= last_step:
            continue
        if secrets.compare_digest(totp.at(step * TOTP_STEP), code):
            return step
    return None
