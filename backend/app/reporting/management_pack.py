"""Monthly management pack PDF (10) in the Nustrad report style: ink cover with a gold rule,
section headers with a gold marker, Montserrat-like Helvetica body, tables on mist headers.

Sections: OKR, profit and loss (month / YTD), balance sheet, cash and 13-week forecast,
receivables, project P&L, operations and HSE."""

import calendar
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from fpdf import FPDF
from fpdf.fonts import FontFace
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.receipt_service import ar_aging, cash_kpis
from app.crm.quotation_pdf import _t
from app.reporting import dashboards
from app.reporting import ledger_reports as rep
from app.services.money import format_idr
from app.treasury import forecast

INK = (26, 26, 26)
GOLD = (255, 189, 82)
MIST = (241, 242, 242)
BODY = (51, 51, 51)
MONTHS = (
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
OKR_LABELS = {
    "revenue": "Pendapatan YTD vs RJPP",
    "new_contracts": "Kontrak baru",
    "win_rate_pct": "Win rate",
    "invoice_to_cash_days": "Invoice-to-cash (hari)",
    "cost_overrun_change_pct": "Perubahan cost overrun",
    "utilisation_pct": "Utilisasi peralatan",
    "downtime_pct": "Downtime",
    "net_margin_pct": "Margin bersih",
    "cash_months_opex": "Kas / opex bulanan",
    "tax_penalties": "Denda pajak",
    "accidents": "Kecelakaan (LTI)",
}


class _Pack(FPDF):
    title_text = ""

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_fill_color(*INK)
        self.rect(0, 0, 210, 12, "F")
        self.set_fill_color(*GOLD)
        self.rect(0, 12, 210, 1.2, "F")
        self.set_xy(12, 3.5)
        self.set_text_color(*MIST)
        self.set_font("Helvetica", "B", 9)
        self.cell(0, 5, _t(self.title_text))
        self.set_text_color(*BODY)
        self.set_y(18)

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(85, 85, 85)
        self.cell(0, 5, _t(f"Rahasia - laporan manajemen · halaman {self.page_no()}"), align="R")

    def section(self, title: str) -> None:
        if self.get_y() > 230:
            self.add_page()
        self.ln(3)
        self.set_fill_color(*GOLD)
        self.rect(12, self.get_y() + 1, 2.5, 6, "F")
        self.set_x(17)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*INK)
        self.cell(0, 8, _t(title), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*BODY)
        self.set_font("Helvetica", "", 8)

    def grid(
        self, headers: list[str], rows: list[list[str]], widths: Sequence[float], right: set[int]
    ) -> None:
        with self.table(
            col_widths=widths,
            width=186,
            line_height=4.5,
            text_align=tuple("RIGHT" if i in right else "LEFT" for i in range(len(headers))),
            headings_style=FontFace(emphasis="BOLD", fill_color=MIST),
            borders_layout="HORIZONTAL_LINES",
        ) as table:
            table.row(tuple(_t(h) for h in headers))
            for r in rows:
                table.row(tuple(_t(c) for c in r))


def _idr(v: Any) -> str:
    if v in (None, ""):
        return "-"
    return format_idr(Decimal(str(v))).replace("Rp ", "")


def _okr_value(r: dict[str, Any], key: str) -> str:
    v = r[key]
    if v is None:
        return "-"
    return {"idr": _idr(v), "pct": f"{v}%", "days": f"{v} hari", "x": f"{v}x"}.get(
        r["unit"], str(v)
    )


async def build(session: AsyncSession, company: str, year: int, month: int) -> bytes:
    end = date(year, month, calendar.monthrange(year, month)[1])
    pdf = _Pack(unit="mm", format="A4")
    pdf.title_text = f"{company} · Laporan Manajemen {MONTHS[month - 1]} {year}"
    pdf.set_margins(12, 18, 12)
    pdf.set_auto_page_break(auto=True, margin=16)

    # Cover
    pdf.add_page()
    pdf.set_fill_color(*INK)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_fill_color(*GOLD)
    pdf.rect(20, 120, 40, 2, "F")
    pdf.set_text_color(*GOLD)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(20, 100)
    pdf.cell(0, 6, _t("LAPORAN MANAJEMEN BULANAN"))
    pdf.set_text_color(*MIST)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_xy(20, 128)
    pdf.multi_cell(170, 12, _t(f"{MONTHS[month - 1]} {year}"))
    pdf.set_font("Helvetica", "", 12)
    pdf.set_x(20)
    pdf.multi_cell(170, 7, _t(company))
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(20, 270)
    pdf.cell(
        0, 5, _t("Disusun otomatis dari Nustrad ERP. Rahasia - untuk Direksi dan pemegang saham.")
    )
    pdf.set_text_color(*BODY)

    pdf.add_page()
    okr = await dashboards.okr(session, year, today=end)
    pdf.section(f"OKR {year} (s.d. {end:%d/%m/%Y})")
    pdf.grid(
        ["Sasaran", "Aktual", "Target", "Status"],
        [
            [
                OKR_LABELS.get(r["key"], r["key"]),
                _okr_value(r, "actual"),
                _okr_value(r, "target"),
                {"on_track": "Sesuai", "off_track": "Perlu tindakan"}.get(
                    r["status"], "Belum ada data"
                ),
            ]
            for r in okr["rows"]
        ],
        [70, 40, 40, 36],
        {1, 2},
    )

    pl = await rep.profit_loss(session, date(year, month, 1))
    pdf.section("Laba rugi (bulan dan YTD)")
    cols = [c for c in pl.columns if c.key != "section"]
    pdf.grid(
        [c.header for c in cols],
        [
            [_idr(r.get(c.key)) if c.kind == "idr" else str(r.get(c.key) or "") for c in cols]
            for r in pl.rows
        ],
        [22, 84, 40, 40][: len(cols)],
        {i for i, c in enumerate(cols) if c.kind == "idr"},
    )

    bs = await rep.balance_sheet(session, end)
    pdf.section(f"Neraca per {end:%d/%m/%Y}")
    cols = [c for c in bs.columns if c.key != "section"]
    pdf.grid(
        [c.header for c in cols],
        [
            [_idr(r.get(c.key)) if c.kind == "idr" else str(r.get(c.key) or "") for c in cols]
            for r in bs.rows
        ],
        [22, 114, 50][: len(cols)],
        {i for i, c in enumerate(cols) if c.kind == "idr"},
    )

    fc = await forecast.build(session, end)
    k = await cash_kpis(session, end)
    pdf.section("Kas dan proyeksi 13 minggu")
    pdf.grid(
        ["Indikator", "Nilai"],
        [
            ["Saldo bank", _idr(fc["opening"])],
            ["Saldo terendah 13 minggu", _idr(fc["lowest"])],
            ["Saldo akhir 13 minggu", _idr(fc["closing"])],
            ["Piutang terbuka", _idr(k.get("ar_balance"))],
            ["DSO (hari)", str(k.get("dso_days") or "-")],
            ["Invoice-to-cash (hari)", str(k.get("days_to_cash") or "-")],
        ],
        [120, 66],
        {1},
    )

    aging = await ar_aging(session, end)
    pdf.section("Umur piutang")
    totals = aging.get("totals") or {}
    pdf.grid(
        ["Belum jatuh tempo", "1-30", "31-60", "61-90", "> 90"],
        [[_idr(totals.get(b)) for b in ("not_due", "d1_30", "d31_60", "d61_90", "d90_plus")]],
        [38, 37, 37, 37, 37],
        {0, 1, 2, 3, 4},
    )

    pp = await rep.project_pnl(session)
    pdf.section("Proyek: pendapatan DOR vs biaya aktual")
    rows = sorted(pp.rows, key=lambda r: Decimal(str(r.get("dor_revenue") or 0)), reverse=True)[:12]
    pdf.grid(
        ["Proyek", "Pendapatan DOR", "Biaya aktual", "Margin %", "Sisa anggaran"],
        [
            [
                str(r.get("project") or ""),
                _idr(r.get("dor_revenue")),
                _idr(r.get("actual_cost")),
                str(r.get("margin_pct") or "-"),
                _idr(r.get("remaining")),
            ]
            for r in rows
        ],
        [36, 38, 38, 30, 44],
        {1, 2, 3, 4},
    )

    pdf.section("Operasi dan HSE")
    by = {r["key"]: r for r in okr["rows"]}
    pdf.grid(
        ["Indikator", "Nilai", "Target"],
        [
            [
                "Utilisasi peralatan",
                _okr_value(by["utilisation_pct"], "actual"),
                _okr_value(by["utilisation_pct"], "target"),
            ],
            [
                "Downtime",
                _okr_value(by["downtime_pct"], "actual"),
                _okr_value(by["downtime_pct"], "target"),
            ],
            ["Kecelakaan (LTI) tahun berjalan", _okr_value(by["accidents"], "actual"), "0"],
        ],
        [100, 43, 43],
        {1, 2},
    )
    return bytes(pdf.output())
