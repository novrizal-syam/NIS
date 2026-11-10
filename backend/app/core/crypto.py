"""Column encryption for personal data (10d; UU 27/2022 PDP).

`EncryptedString` stores Fernet ciphertext prefixed with `enc:` and returns plaintext to the
ORM. Keys come from DATA_ENCRYPTION_KEYS (newest first; older keys still decrypt, so keys can
be rotated by prepending a new one and re-saving rows). In development a key is derived from
SECRET_KEY. Plaintext values written before encryption was enabled are returned as they are
and encrypted on the next save (the 0036 migration encrypts all existing rows).
"""

import base64
import hashlib
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings

PREFIX = "enc:"


@lru_cache
def _fernet() -> MultiFernet:
    s = get_settings()
    keys = [k.strip() for k in s.data_encryption_keys.split(",") if k.strip()]
    if not keys:
        keys = [base64.urlsafe_b64encode(hashlib.sha256(s.secret_key.encode()).digest()).decode()]
    return MultiFernet([Fernet(k) for k in keys])


def reset_keys() -> None:
    _fernet.cache_clear()


def encrypt(value: str) -> str:
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value.startswith(PREFIX):
        return value  # legacy plaintext
    try:
        return _fernet().decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Data terenkripsi tidak dapat dibuka: kunci enkripsi tidak cocok."
        ) from exc


def generate_key() -> str:
    return Fernet.generate_key().decode()


class EncryptedString(TypeDecorator[str]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None or value == "":
            return None if value is None else ""
        return encrypt(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None or value == "":
            return None if value is None else ""
        return decrypt(str(value))
