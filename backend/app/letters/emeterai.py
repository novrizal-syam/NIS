"""e-Meterai (Peruri) adapter. `internal` records a reference only; the Peruri integration
implements `StampProvider` later and is selected with setting `emeterai.provider`."""

import hashlib
import uuid
from typing import Protocol


class StampProvider(Protocol):
    name: str

    async def stamp(self, pdf: bytes, *, document_no: str) -> tuple[str, bytes]: ...


class InternalStamp:
    name = "internal"

    async def stamp(self, pdf: bytes, *, document_no: str) -> tuple[str, bytes]:
        digest = hashlib.sha256(pdf).hexdigest()[:12]
        return f"EMT-INT-{uuid.uuid4().hex[:6]}-{digest}", pdf


_PROVIDERS: dict[str, StampProvider] = {"internal": InternalStamp()}


def register(provider: StampProvider) -> None:
    _PROVIDERS[provider.name] = provider


def get(name: str | None) -> StampProvider:
    return _PROVIDERS.get(name or "internal", _PROVIDERS["internal"])
