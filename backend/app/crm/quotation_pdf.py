"""Quotation PDF on the GEK letterhead. Shows selling prices only (never cost or margin)."""

import io
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fpdf import FPDF, FontFace

from app.crm.models import Opportunity, Quotation, QuotationLine
from app.services.money import format_idr, format_number

log = logging.getLogger("app.crm.pdf")

MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
MONTHS_LONG = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)
INK = (26, 26, 26)
GOLD = (255, 189, 82)
MUTED = (90, 90, 90)


def id_date(d: date, long: bool = False) -> str:
    """`7 Okt 2026` (or `7 Oktober 2026` for the letter date)."""
    return f"{d.day} {(MONTHS_LONG if long else MONTHS)[d.month - 1]} {d.year}"


def _t(text: str | None) -> str:
    # Core PDF fonts are Latin-1 only.
    return (
        (text or "")
        .replace("≥", ">=")
        .replace("\u2013", "-")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


@dataclass(frozen=True)
class Letterhead:
    company: dict[str, Any]
    logo: bytes | None  # PNG/JPEG from the company profile


@dataclass(frozen=True)
class Recipient:
    company: str
    contact: str | None


class _Pdf(FPDF):
    head: Letterhead
    draft: bool = False

    def header(self) -> None:
        c = self.head.company
        top = self.get_y()
        if self.head.logo:
            try:
                self.image(io.BytesIO(self.head.logo), x=15, y=top, h=16)
            except Exception:  # a broken logo must not stop the letter
                log.warning("letterhead_logo_unreadable")
        self.set_xy(15, top)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*INK)
        self.cell(0, 6, _t(c.get("legal_name")), align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        for line in (
            c.get("address"),
            " - ".join(x for x in (c.get("phone"), c.get("email")) if x),
            f"NPWP {c['npwp']}" if c.get("npwp") else None,
        ):
            if line:
                self.cell(0, 4, _t(line), align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_y(max(self.get_y(), top + 18))
        self.set_draw_color(*GOLD)
        self.set_line_width(0.8)
        self.line(15, self.get_y() + 1, 195, self.get_y() + 1)
        self.set_line_width(0.2)
        self.ln(5)
        if self.draft:
            self.set_font("Helvetica", "B", 48)
            self.set_text_color(230, 230, 230)
            with self.rotation(30, 105, 150):
                self.text(45, 160, "DRAF")
        self.set_text_color(*INK)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"Halaman {self.page_no()}/{{nb}}", align="C")


def render(
    head: Letterhead,
    q: Quotation,
    lines: list[QuotationLine],
    opp: Opportunity,
    to: Recipient,
    *,
    letter_number: str | None,
    letter_date: date,
    signer: str,
) -> bytes:
    pdf = _Pdf(unit="mm", format="A4")
    pdf.head = head
    pdf.draft = letter_number is None
    pdf.set_margins(15, 12, 15)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "", 9)
    meta = (
        ("Nomor", letter_number or "(belum bernomor - draf)"),
        ("Tanggal", id_date(letter_date, long=True)),
        ("Perihal", f"Penawaran Harga - {opp.title}"),
        ("Referensi", f"{q.number} Rev.{q.revision}"),
    )
    for k, v in meta:
        pdf.cell(24, 5, k)
        pdf.cell(4, 5, ":")
        pdf.multi_cell(0, 5, _t(v), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.cell(0, 5, "Kepada Yth.", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, _t(to.company), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    if to.contact:
        pdf.cell(0, 5, _t(f"Up. {to.contact}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.multi_cell(
        0,
        5,
        _t(
            "Dengan hormat,\nBersama ini kami sampaikan penawaran harga untuk "
            f"{opp.title} dengan rincian sebagai berikut:"
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    widths = (9, 77, 18, 16, 30, 30)
    pdf.set_font("Helvetica", "", 8)
    with pdf.table(
        col_widths=widths,
        width=sum(widths),
        line_height=4.5,
        text_align=("CENTER", "LEFT", "RIGHT", "LEFT", "RIGHT", "RIGHT"),
        headings_style=FontFace(emphasis="BOLD", fill_color=(241, 242, 242)),
    ) as table:
        table.row(("No", "Uraian", "Qty", "Satuan", "Harga satuan", "Jumlah"))
        for i, x in enumerate(lines, start=1):
            qty = format_number(x.qty, 0 if x.qty == x.qty.to_integral() else 2)
            table.row(
                (
                    str(i),
                    _t(x.description),
                    qty,
                    _t(x.unit),
                    format_idr(x.unit_price),
                    format_idr(x.line_price),
                )
            )
    pdf.ln(1)
    totals: list[tuple[str, Decimal]] = [("Subtotal", q.subtotal)]
    if q.discount_amount:
        pct = format_number(q.discount_pct, 0 if q.discount_pct == int(q.discount_pct) else 2)
        totals.append((f"Diskon {pct}%", -q.discount_amount))
    totals.append(("Total (belum termasuk PPN)", q.total_price))
    for i, (caption, amount) in enumerate(totals):
        pdf.set_font("Helvetica", "B" if i == len(totals) - 1 else "", 9)
        pdf.cell(sum(widths) - 30, 6, _t(caption), align="R")
        pdf.cell(30, 6, format_idr(amount), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 9)
    if q.valid_until:
        pdf.multi_cell(
            0,
            5,
            _t(f"Penawaran ini berlaku sampai {id_date(q.valid_until, long=True)}."),
            new_x="LMARGIN",
            new_y="NEXT",
        )
    if q.terms:
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, "Syarat dan ketentuan", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _t(q.terms), new_x="LMARGIN", new_y="NEXT")
    if q.notes:
        pdf.ln(1)
        pdf.multi_cell(0, 5, _t(q.notes), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.multi_cell(
        0,
        5,
        "Demikian penawaran ini kami sampaikan. Atas perhatian dan kerja samanya kami ucapkan "
        "terima kasih.",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)
    pdf.cell(0, 5, "Hormat kami,", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _t(head.company.get("legal_name")), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(16)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, _t(signer), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
