"""Text for full-text search: the PDF text layer now; scanned images go through an OCR
adapter (none configured by default - plug one in with `register_ocr`)."""

import io
import logging
from typing import Protocol

log = logging.getLogger("app.dms")
MAX_CHARS = 200_000


class OcrEngine(Protocol):
    name: str

    def image_text(self, data: bytes, content_type: str) -> str: ...


_ocr: OcrEngine | None = None


def register_ocr(engine: OcrEngine | None) -> None:
    global _ocr
    _ocr = engine


def extract(data: bytes, content_type: str) -> str | None:
    try:
        if content_type == "application/pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages[:200]:
                parts.append(page.extract_text() or "")
                if sum(map(len, parts)) > MAX_CHARS:
                    break
            text = "\n".join(parts).strip()
            if text:
                return text[:MAX_CHARS]
        if _ocr is not None and content_type.startswith(("image/", "application/pdf")):
            return _ocr.image_text(data, content_type)[:MAX_CHARS] or None
    except Exception:  # unreadable file: search falls back to name and note
        log.warning("text_extract_failed", extra={"content_type": content_type})
    return None
