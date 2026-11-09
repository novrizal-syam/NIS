"""PSrE (Penyelenggara Sertifikasi Elektronik) e-signature adapter.

`internal` mode (now): the signed ticket PDF carries the client's drawn signature and an audit
reference; nothing leaves the system. A certified provider (e.g. Privy, VIDA, PERURI) plugs in
later by implementing `SignatureProvider` and selecting it with the setting `psre.provider`.
"""

import hashlib
import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SignedDocument:
    provider: str
    reference: str
    pdf: bytes


class SignatureProvider(Protocol):
    name: str

    async def sign(
        self, pdf: bytes, *, signer_name: str, signer_email: str | None
    ) -> SignedDocument: ...


class InternalProvider:
    name = "internal"

    async def sign(
        self, pdf: bytes, *, signer_name: str, signer_email: str | None
    ) -> SignedDocument:
        digest = hashlib.sha256(pdf).hexdigest()[:16]
        return SignedDocument(self.name, f"INT-{uuid.uuid4().hex[:8]}-{digest}", pdf)


_PROVIDERS: dict[str, SignatureProvider] = {"internal": InternalProvider()}


def register(provider: SignatureProvider) -> None:
    _PROVIDERS[provider.name] = provider


def get(name: str | None) -> SignatureProvider:
    return _PROVIDERS.get(name or "internal", _PROVIDERS["internal"])
