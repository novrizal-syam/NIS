from httpx import AsyncClient


async def test_health_ok(client: AsyncClient) -> None:
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["db"] == "ok"
    assert res.headers["x-request-id"]


async def test_request_id_is_echoed(client: AsyncClient) -> None:
    res = await client.get("/api/health", headers={"x-request-id": "abc123"})
    assert res.headers["x-request-id"] == "abc123"


async def test_cors_allows_web_origin(client: AsyncClient) -> None:
    res = await client.options(
        "/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
