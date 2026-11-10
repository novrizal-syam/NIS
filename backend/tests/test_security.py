"""Phase 10d: every endpoint behind authentication (explicit public allowlist), personal data
encrypted at rest and stripped without permission, security headers, hardened configuration,
key rotation, PDP breach log and consent register."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.core import crypto
from app.core.config import Settings, get_settings
from app.main import app as main_app

MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
AUTH = {"get_principal", "get_principal_allow_pending"}
PUBLIC = {
    ("GET", "/api/health"),
    ("GET", "/api/setup/status"),
    ("POST", "/api/setup/admin"),
    ("POST", "/api/setup/verify-token"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/forgot-password"),
    ("POST", "/api/auth/reset-password"),
    ("POST", "/api/auth/invite/accept"),
    ("GET", "/api/public/share/{token}"),
}


def _routes() -> list[Any]:
    out: list[Any] = []

    def walk(x: Any) -> None:
        ec = getattr(x, "effective_candidates", None)
        if ec is not None:
            for c in ec() if callable(ec) else ec:
                walk(c)
        elif getattr(x, "dependant", None) is not None and getattr(x, "path", None):
            out.append(x)

    for r in main_app.routes:
        walk(r)
    return out


def _calls(dep: Any, acc: set[str]) -> set[str]:
    for sub in dep.dependencies:
        acc.add(getattr(sub.call, "__name__", str(sub.call)))
        _calls(sub, acc)
    return acc


def test_every_endpoint_requires_a_signed_in_user_except_the_public_list() -> None:
    routes = [
        r for r in _routes() if r.path.startswith("/api/") and not r.path.startswith("/api/_")
    ]
    assert len(routes) > 350
    open_ = {
        (m, r.path)
        for r in routes
        for m in (r.methods or [])
        if not (_calls(r.dependant, set()) & AUTH)
    }
    assert open_ == PUBLIC


async def test_anonymous_requests_are_rejected(client: AsyncClient) -> None:
    for path in (
        "/api/ledger/journals",
        "/api/payroll/runs",
        "/api/dms/library",
        "/api/portal/me",
        "/api/dashboard/okr",
    ):
        r = await client.get(path)
        assert r.status_code == 401, (path, r.status_code)


async def test_personal_data_encrypted_at_rest_and_stripped(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    hcbp = await login(await make_user("hcbp_officer"))
    r = await client.post(
        "/api/master/employees",
        json={
            "code": "E-SEC",
            "full_name": "Sari Aman",
            "position": "Engineer",
            "nik": "3171010101900001",
            "npwp": "0123456789012000",
            "bank_name": "Mandiri",
            "bank_account_no": "1230009998887",
        },
        headers=hcbp,
    )
    assert r.status_code in (200, 201), r.text
    eid = r.json()["id"]
    async with sessionmaker() as s:
        raw = (
            await s.execute(
                text("SELECT nik, npwp, bank_account_no FROM employees WHERE code = 'E-SEC'")
            )
        ).one()
    assert all(v.startswith("enc:") for v in raw) and "3171010101900001" not in "".join(raw)
    got = (await client.get(f"/api/master/employees/{eid}", headers=hcbp)).json()
    assert got["nik"] == "3171010101900001" and got["bank_account_no"] == "1230009998887"
    other = await login(await make_user("procurement_officer"))
    plain = (await client.get(f"/api/master/employees/{eid}", headers=other)).json()
    assert "nik" not in plain and "bank_account_no" not in plain and "npwp" not in plain


def test_key_rotation_keeps_old_data_readable() -> None:
    s = get_settings()
    old_keys = s.data_encryption_keys
    a, b = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    try:
        s.data_encryption_keys = a
        crypto.reset_keys()
        token = crypto.encrypt("3171010101900001")
        s.data_encryption_keys = f"{b},{a}"  # new key first, old key still decrypts
        crypto.reset_keys()
        assert crypto.decrypt(token) == "3171010101900001"
        assert crypto.decrypt(crypto.encrypt("x")) == "x"
        s.data_encryption_keys = b
        crypto.reset_keys()
        with pytest.raises(ValueError):
            crypto.decrypt(token)
        assert crypto.decrypt("legacy-plaintext") == "legacy-plaintext"
    finally:
        s.data_encryption_keys = old_keys
        crypto.reset_keys()


async def test_security_headers(client: AsyncClient) -> None:
    r = await client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_hardened_environments_refuse_insecure_configuration() -> None:
    with pytest.raises(ValueError) as exc:
        Settings(app_env="production", _env_file=None)  # type: ignore[call-arg]
    msg = str(exc.value)
    assert "SECRET_KEY" in msg and "DATA_ENCRYPTION_KEYS" in msg and "https" in msg
    ok = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="staging",
        secret_key="x" * 40,
        data_encryption_keys=Fernet.generate_key().decode(),
        app_base_url="https://erp-staging.gek.co.id",
        cors_origins=["https://erp-staging.gek.co.id"],
        s3_secret_key="real-secret",
    )
    assert ok.is_hardened and not ok.is_production


async def test_breach_log_and_consents(
    client: AsyncClient, make_user: MakeUser, login: Login
) -> None:
    fe = await login(await make_user("field_engineer"))
    director = await login(await make_user("director"))
    r = await client.post(
        "/api/pdp/breaches",
        json={
            "detected_at": (datetime.now(UTC) - timedelta(hours=80)).isoformat(),
            "description": "Laptop berisi daftar gaji tertinggal di bandara",
            "data_categories": ["salary", "nik"],
            "affected_count": 34,
            "severity": "high",
        },
        headers=fe,
    )
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["overdue"] is True  # detected 80 h ago, nobody notified yet
    assert (await client.get("/api/pdp/breaches", headers=fe)).status_code == 403
    url = f"/api/pdp/breaches/{b['id']}"
    r = await client.put(url, json={"status": "closed"}, headers=director)
    assert r.status_code == 422 and r.json()["code"] == "CLOSE_INCOMPLETE"
    r = await client.put(
        url,
        json={
            "subjects_notified": True,
            "authority_notified": True,
            "authority_reference": "KOMINFO/PDP/2026/123",
            "containment": "Akun dikunci, perangkat di-wipe jarak jauh",
            "lessons": "Enkripsi disk wajib untuk laptop keuangan",
            "status": "closed",
        },
        headers=director,
    )
    assert r.status_code == 200 and r.json()["status"] == "closed" and r.json()["overdue"] is False
    consents = (await client.get("/api/pdp/consents", headers=director)).json()
    assert consents["current_version"] and len(consents["users"]) >= 2
