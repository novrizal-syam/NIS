from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from app.core.errors import AppError, ConflictError, install_error_handlers


class Payload(BaseModel):
    name: str = Field(min_length=3)
    qty: int


def _app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/items")
    async def create(p: Payload) -> Payload:
        return p

    @app.get("/business")
    async def business() -> None:
        raise ConflictError("PR_ALREADY_APPROVED", "PR sudah disetujui dan tidak bisa diubah.")

    @app.get("/plain")
    async def plain() -> None:
        raise AppError("X", "Pesan.")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    return app


async def _client() -> AsyncClient:
    transport = ASGITransport(app=_app(), raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://t")


async def test_business_error_shape() -> None:
    async with await _client() as c:
        res = await c.get("/business")
    assert res.status_code == 409
    assert res.json() == {
        "code": "PR_ALREADY_APPROVED",
        "message": "PR sudah disetujui dan tidak bisa diubah.",
    }


async def test_app_error_defaults_to_400() -> None:
    async with await _client() as c:
        res = await c.get("/plain")
    assert res.status_code == 400
    assert res.json()["code"] == "X"


async def test_validation_error_in_indonesian() -> None:
    async with await _client() as c:
        res = await c.post("/items", json={"name": "ab"})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["message"].startswith("Data tidak valid:")
    fields = {d["field"]: d["message"] for d in body["details"]}
    assert fields == {"name": "terlalu pendek", "qty": "wajib diisi"}


async def test_not_found_route() -> None:
    async with await _client() as c:
        res = await c.get("/nope")
    assert res.status_code == 404
    assert res.json() == {"code": "NOT_FOUND", "message": "Data atau halaman tidak ditemukan."}


async def test_unhandled_error_hides_details() -> None:
    async with await _client() as c:
        res = await c.get("/boom")
    assert res.status_code == 500
    assert res.json()["code"] == "INTERNAL_ERROR"
    assert "secret" not in res.text
