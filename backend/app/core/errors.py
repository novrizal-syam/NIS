"""Uniform error responses: every error is `{code, message}` with a Bahasa Indonesia message."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")


class AppError(Exception):
    """Raise for any expected business error. `message` is shown to the user as-is."""

    status_code = 400

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class ForbiddenError(AppError):
    status_code = 403


_HTTP_MESSAGES: dict[int, tuple[str, str]] = {
    400: ("BAD_REQUEST", "Permintaan tidak valid."),
    401: ("UNAUTHENTICATED", "Silakan masuk terlebih dahulu."),
    403: ("FORBIDDEN", "Anda tidak memiliki akses untuk tindakan ini."),
    404: ("NOT_FOUND", "Data atau halaman tidak ditemukan."),
    405: ("METHOD_NOT_ALLOWED", "Metode tidak diizinkan untuk alamat ini."),
    409: ("CONFLICT", "Data bentrok dengan perubahan lain. Muat ulang lalu coba lagi."),
    429: ("TOO_MANY_REQUESTS", "Terlalu banyak permintaan. Tunggu sebentar lalu coba lagi."),
}

_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "wajib diisi",
    "string_too_short": "terlalu pendek",
    "string_too_long": "terlalu panjang",
    "int_parsing": "harus berupa angka bulat",
    "decimal_parsing": "harus berupa angka",
    "float_parsing": "harus berupa angka",
    "greater_than": "harus lebih besar",
    "greater_than_equal": "nilainya terlalu kecil",
    "less_than_equal": "nilainya terlalu besar",
    "date_from_datetime_parsing": "format tanggal tidak valid",
    "date_parsing": "format tanggal tidak valid",
    "uuid_parsing": "format ID tidak valid",
    "value_error": "nilai tidak valid",
    "enum": "pilihan tidak valid",
    "bool_parsing": "harus ya atau tidak",
    "json_invalid": "format JSON tidak valid",
}


def _field_name(loc: tuple[Any, ...]) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) or "data"


def _error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return body


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(_error_body(exc.code, exc.message, exc.details), exc.status_code)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields = [
        {
            "field": _field_name(tuple(err.get("loc", ()))),
            "message": _VALIDATION_MESSAGES.get(err.get("type", ""), "nilai tidak valid"),
        }
        for err in exc.errors()
    ]
    summary = "; ".join(f"{f['field']} {f['message']}" for f in fields[:3])
    return JSONResponse(
        _error_body("VALIDATION_ERROR", f"Data tidak valid: {summary}.", fields), 422
    )


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, message = _HTTP_MESSAGES.get(exc.status_code, ("HTTP_ERROR", "Permintaan gagal."))
    return JSONResponse(_error_body(code, message), exc.status_code, headers=exc.headers)


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", exc_info=exc)
    return JSONResponse(
        _error_body(
            "INTERNAL_ERROR",
            "Terjadi kesalahan pada server. Coba lagi; jika berulang, hubungi admin.",
        ),
        500,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)
