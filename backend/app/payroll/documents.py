"""Payslip and 1721-A1 PDFs (07c). Callers enforce who may see them."""

from decimal import Decimal
from typing import Any

from app.billing.documents import _kv, _start
from app.crm.quotation_pdf import Letterhead, _t
from app.payroll.models import PayrollRun, Payslip
from app.services.money import format_idr

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


def _rows(pdf: Any, title: str, rows: list[tuple[str, Decimal]], total: str) -> None:
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, _t(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    s = Decimal(0)
    for label, v in rows:
        if v == 0:
            continue
        pdf.cell(120, 5, _t(label))
        pdf.cell(0, 5, _t(format_idr(v)), align="R", new_x="LMARGIN", new_y="NEXT")
        s += v
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(120, 6, _t(total), border="T")
    pdf.cell(0, 6, _t(format_idr(s)), border="T", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def payslip_pdf(
    head: Letterhead, run: PayrollRun, ps: Payslip, items: list[tuple[str, str, Decimal]]
) -> bytes:
    pdf = _start(head)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(
        0,
        8,
        _t(f"SLIP GAJI {MONTHS[run.month - 1].upper()} {run.year}"),
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(
        0, 5, _t("RAHASIA - hanya untuk karyawan ybs."), align="C", new_x="LMARGIN", new_y="NEXT"
    )
    pdf.ln(2)
    _kv(
        pdf,
        [
            ("NIP", ps.employee_code),
            ("Nama", ps.employee_name),
            ("Jabatan", ps.position or "-"),
            ("Status PTKP", f"{ps.ptkp_status} (TER {ps.ter_category})"),
            (
                "Periode",
                f"{run.period_start:%d/%m/%Y} - {run.period_end:%d/%m/%Y} · "
                f"hari di lokasi {ps.site_days}, lembur {ps.overtime_hours} jam",
            ),
        ],
    )
    pdf.ln(2)
    _rows(
        pdf,
        "Pendapatan",
        [
            ("Gaji pokok", ps.basic),
            ("Tunjangan tetap", ps.fixed_allowance),
            (f"Tunjangan lapangan ({ps.site_days} hari)", ps.field_allowance),
            (f"Lembur ({ps.overtime_factor_hours} jam faktor)", ps.overtime_pay),
            *[(n, a) for k, n, a in items if k == "allowance"],
        ],
        "Total pendapatan",
    )
    _rows(
        pdf,
        "Potongan",
        [
            ("BPJS Kesehatan (1%)", ps.kes_ee),
            ("BPJS JHT (2%)", ps.jht_ee),
            ("BPJS JP (1%)", ps.jp_ee),
            (
                "PPh 21 (perhitungan tahunan)" if ps.annual else f"PPh 21 (TER {ps.ter_rate}%)",
                ps.pph21,
            ),
            *[(n, a) for k, n, a in items if k == "deduction"],
        ],
        "Total potongan",
    )
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(120, 8, _t("GAJI BERSIH DITERIMA"))
    pdf.cell(0, 8, _t(format_idr(ps.net)), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(
        0,
        4,
        _t(
            "Ditanggung perusahaan (bukan potongan): BPJS Kesehatan "
            f"{format_idr(ps.kes_er)}, JHT {format_idr(ps.jht_er)}, JP {format_idr(ps.jp_er)}, "
            f"JKK {format_idr(ps.jkk_er)}, JKM {format_idr(ps.jkm_er)}. Penghasilan bruto PPh 21 "
            f"{format_idr(ps.taxable)}."
        ),
    )
    return bytes(pdf.output())


def a1_pdf(head: Letterhead, year: int, emp: dict[str, Any], a: dict[str, Decimal]) -> bytes:
    """Ringkasan bukti potong 1721-A1 (official form via Coretax)."""
    pdf = _start(head)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(
        0,
        8,
        _t(f"BUKTI PEMOTONGAN PPh 21 (1721-A1) TAHUN {year}"),
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)
    company = head.company
    _kv(
        pdf,
        [
            ("Pemotong", str(company.get("legal_name") or "-")),
            ("NPWP pemotong", str(company.get("npwp") or "-")),
            ("NIP / Nama", f"{emp['code']} / {emp['name']}"),
            ("NPWP / NIK", emp.get("tax_id") or "-"),
            ("Status PTKP", emp["ptkp_status"]),
            ("Masa", f"{a['first_month']:02d}-{a['last_month']:02d} {year}"),
        ],
    )
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 9)
    lines = [
        ("1. Gaji / pensiun", a["salary"]),
        ("2. Tunjangan PPh / lainnya, lembur, lapangan", a["allowances"]),
        ("3. Premi asuransi dibayar pemberi kerja (JKK, JKM, BPJS Kes)", a["insurance"]),
        ("4. Jumlah penghasilan bruto", a["gross"]),
        ("5. Biaya jabatan", a["position_cost"]),
        ("6. Iuran pensiun / JHT / JP", a["pension"]),
        ("7. Penghasilan neto setahun", a["net"]),
        ("8. PTKP", a["ptkp"]),
        ("9. PKP setahun (dibulatkan)", a["pkp"]),
        ("10. PPh 21 terutang setahun", a["tax"]),
        ("11. PPh 21 telah dipotong", a["withheld"]),
    ]
    for label, v in lines:
        pdf.cell(130, 6, _t(label), border="B")
        pdf.cell(0, 6, _t(format_idr(v)), border="B", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(
        0,
        4,
        _t(
            "Ringkasan dari data penggajian. Bukti potong resmi diterbitkan di Coretax DJP "
            "oleh Tax Specialist."
        ),
    )
    return bytes(pdf.output())
