"""Coretax via PJAP (10b).

File mode (no PJAP_BASE_URL/PJAP_API_KEY): the Tax Specialist downloads the Coretax e-Faktur
XML and imports it in Coretax. Live mode: the XML is posted to the PJAP partner's endpoint
(`POST {base}/efaktur`, bearer key), whose response carries the upload reference. Each PJAP has
its own API; `PjapClient` is the seam to implement it against."""

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings

_transport: httpx.AsyncBaseTransport | None = None


def use_transport(t: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = t


@dataclass(frozen=True)
class UploadResult:
    reference: str
    status: str
    message: str | None = None


class PjapClient(Protocol):
    async def upload_efaktur(self, xml: bytes, *, batch: str) -> UploadResult: ...


class HttpPjap:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url, self.api_key = base_url.rstrip("/"), api_key

    async def upload_efaktur(self, xml: bytes, *, batch: str) -> UploadResult:
        async with httpx.AsyncClient(timeout=30, transport=_transport) as client:
            r = await client.post(
                f"{self.base_url}/efaktur",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/xml",
                },
                params={"batch": batch},
                content=xml,
            )
        if r.status_code >= 400:
            raise RuntimeError(f"PJAP menolak unggahan (HTTP {r.status_code}): {r.text[:300]}")
        data = r.json()
        return UploadResult(
            str(data.get("reference") or data.get("id")),
            str(data.get("status", "accepted")),
            data.get("message"),
        )


def client() -> PjapClient | None:
    """None = file mode."""
    s = get_settings()
    if s.pjap_base_url and s.pjap_api_key:
        return HttpPjap(s.pjap_base_url, s.pjap_api_key)
    return None
