"""Stamp every page of a PDF (controlled / uncontrolled copy, viewer and time)."""

import io

from fpdf import FPDF
from pypdf import PdfReader, PdfWriter


def stamp(pdf: bytes, headline: str, footer: str) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    for page in writer.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        mark = FPDF(unit="pt", format=(w, h))
        mark.add_page()
        mark.set_text_color(200, 30, 30)
        mark.set_font("Helvetica", "B", 28)
        with mark.rotation(35, x=w / 2, y=h / 2):
            mark.set_xy(0, h / 2 - 20)
            mark.cell(w, 40, headline, align="C")
        mark.set_font("Helvetica", "", 8)
        mark.set_text_color(90, 90, 90)
        mark.set_xy(20, h - 24)
        mark.cell(w - 40, 12, footer[:180])
        overlay = PdfReader(io.BytesIO(bytes(mark.output()))).pages[0]
        page.merge_page(overlay)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
