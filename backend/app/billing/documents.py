"""PDFs on the GEK letterhead: signed service ticket and the invoice pack (invoice, faktur
summary, signed tickets, DOR summary, BAST/SES reference)."""

import io
from datetime import date
from typing import Any

from fpdf import FontFace

from app.billing.models import CustomerInvoice, ServiceTicket, TicketLine
from app.crm.quotation_pdf import Letterhead, _Pdf, _t, id_date
from app.services.money import format_idr, format_number


def _start(head: Letterhead) -> _Pdf:
    pdf = _Pdf(unit="mm", format="A4")
    pdf.head = head
    pdf.set_margins(15, 12, 15)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    return pdf


def _kv(pdf: _Pdf, rows: list[tuple[str, str]]) -> None:
    pdf.set_font("Helvetica", "", 9)
    for k, v in rows:
        pdf.cell(34, 5, k)
        pdf.cell(4, 5, ":")
        pdf.multi_cell(0, 5, _t(v), new_x="LMARGIN", new_y="NEXT")


def _qty(v: Any) -> str:
    return format_number(v, 0 if v == v.to_integral() else 2)


def _ticket_page(
    pdf: _Pdf,
    t: ServiceTicket,
    lines: list[TicketLine],
    *,
    project_label: str,
    contract_label: str,
    client: str,
    signature_png: bytes | None,
) -> None:
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "SERVICE TICKET", new_x="LMARGIN", new_y="NEXT")
    _kv(
        pdf,
        [
            ("Nomor", t.number),
            ("Klien", client),
            ("Kontrak", contract_label),
            ("Proyek", project_label),
            ("Periode", f"{id_date(t.period_from)} - {id_date(t.period_to)}"),
            ("No. BAST/SES", t.acceptance_no or "-"),
        ],
    )
    pdf.ln(2)
    widths = (20, 82, 16, 16, 46)
    pdf.set_font("Helvetica", "", 8)
    with pdf.table(
        col_widths=widths,
        width=sum(widths),
        line_height=4.5,
        text_align=("LEFT", "LEFT", "RIGHT", "LEFT", "RIGHT"),
        headings_style=FontFace(emphasis="BOLD", fill_color=(241, 242, 242)),
    ) as table:
        table.row(("Tanggal", "Uraian", "Qty", "Satuan", "Jumlah"))
        for x in lines:
            desc = x.description + (f" [DISPUTE: {x.dispute_reason}]" if x.disputed else "")
            table.row(
                (
                    id_date(x.work_date),
                    _t(desc),
                    _qty(x.qty),
                    _t(x.unit),
                    ("(" + format_idr(x.amount) + ")") if x.disputed else format_idr(x.amount),
                )
            )
    pdf.ln(1)
    for i, (caption, amount) in enumerate(
        (
            ("Nilai kotor", t.gross_value),
            ("Dispute", t.disputed_value),
            ("Nilai disetujui", t.value),
        )
    ):
        pdf.set_font("Helvetica", "B" if i == 2 else "", 9)
        pdf.cell(sum(widths) - 46, 6, caption, align="R")
        pdf.cell(46, 6, format_idr(amount), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, "Disetujui oleh klien:", new_x="LMARGIN", new_y="NEXT")
    if signature_png:
        try:
            pdf.image(io.BytesIO(signature_png), w=50, h=20)
        except Exception:
            pdf.ln(20)
    else:
        pdf.ln(20)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, _t(t.signer_name or "-"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    if t.signed_at:
        pdf.cell(
            0,
            5,
            _t(f"Ditandatangani {t.signed_at:%d/%m/%Y %H:%M} UTC via {t.sign_method or '-'}"),
            new_x="LMARGIN",
            new_y="NEXT",
        )


def render_ticket(
    head: Letterhead,
    t: ServiceTicket,
    lines: list[TicketLine],
    *,
    project_label: str,
    contract_label: str,
    client: str,
    signature_png: bytes | None,
) -> bytes:
    pdf = _start(head)
    _ticket_page(
        pdf,
        t,
        lines,
        project_label=project_label,
        contract_label=contract_label,
        client=client,
        signature_png=signature_png,
    )
    return bytes(pdf.output())


def render_invoice_pack(
    head: Letterhead,
    inv: CustomerInvoice,
    *,
    client: dict[str, Any],
    contract_label: str,
    tickets: list[tuple[ServiceTicket, list[TicketLine], str, bytes | None]],
    dor_summary: list[tuple[str, date, str]],
) -> bytes:
    pdf = _start(head)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "INVOICE", new_x="LMARGIN", new_y="NEXT")
    _kv(
        pdf,
        [
            ("Nomor", inv.number),
            ("Tanggal", id_date(inv.invoice_date, long=True)),
            ("Jatuh tempo", id_date(inv.due_date, long=True)),
            ("Kontrak", contract_label),
            ("No. faktur pajak", inv.faktur_number or "-"),
        ],
    )
    pdf.ln(2)
    pdf.cell(0, 5, "Kepada:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, _t(client.get("name")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for line in (client.get("address"), f"NPWP {client['npwp']}" if client.get("npwp") else None):
        if line:
            pdf.multi_cell(0, 5, _t(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    widths = (40, 90, 50)
    pdf.set_font("Helvetica", "", 8)
    with pdf.table(
        col_widths=widths,
        width=sum(widths),
        line_height=4.5,
        text_align=("LEFT", "LEFT", "RIGHT"),
        headings_style=FontFace(emphasis="BOLD", fill_color=(241, 242, 242)),
    ) as table:
        table.row(("Service ticket", "Periode / BAST", "Nilai"))
        for t, _lines, _client, _sig in tickets:
            table.row(
                (
                    t.number,
                    _t(
                        f"{id_date(t.period_from)} - {id_date(t.period_to)}"
                        f" / {t.acceptance_no or '-'}"
                    ),
                    format_idr(t.value),
                )
            )
    pdf.ln(1)
    rows = [
        ("Subtotal", inv.subtotal, False),
        ("DPP nilai lain (11/12)", inv.dpp_other, False),
        (f"PPN {format_number(inv.ppn_rate, 0)}%", inv.ppn, False),
        ("Total tagihan", inv.total, True),
        (
            f"Perkiraan PPh 23 dipotong ({format_number(inv.pph23_rate, 0)}%)",
            inv.pph23_expected,
            False,
        ),
        ("Perkiraan diterima", inv.net_cash, True),
    ]
    for caption, amount, bold in rows:
        pdf.set_font("Helvetica", "B" if bold else "", 9)
        pdf.cell(sum(widths) - 50, 6, _t(caption), align="R")
        pdf.cell(50, 6, format_idr(amount), align="R", new_x="LMARGIN", new_y="NEXT")
    if inv.stamp_duty:
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(
            0,
            5,
            _t(f"Bea meterai {format_idr(inv.stamp_duty)} (e-Meterai)."),
            new_x="LMARGIN",
            new_y="NEXT",
        )
    company = head.company
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(
        0,
        5,
        _t(
            f"Pembayaran ke {company.get('legal_name')}"
            + (f", {company.get('bank_account')}" if company.get("bank_account") else "")
            + "."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )

    # Faktur summary
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "RINGKASAN FAKTUR PAJAK", new_x="LMARGIN", new_y="NEXT")
    _kv(
        pdf,
        [
            ("Nomor faktur", inv.faktur_number or "-"),
            ("Tanggal faktur", id_date(inv.faktur_date) if inv.faktur_date else "-"),
            ("Penjual", f"{company.get('legal_name')} / NPWP {company.get('npwp') or '-'}"),
            ("Pembeli", f"{client.get('name')} / NPWP {client.get('npwp') or '-'}"),
            ("Harga jual", format_idr(inv.subtotal)),
            ("DPP nilai lain", format_idr(inv.dpp_other)),
            ("PPN", format_idr(inv.ppn)),
        ],
    )
    # DOR summary
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "RINGKASAN DOR", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    with pdf.table(col_widths=(40, 40, 100), width=180, line_height=4.5) as table:
        table.row(("DOR", "Tanggal", "Aktivitas"))
        for number, day, activity in dor_summary:
            table.row((number, id_date(day), _t((activity or "-")[:180])))
    # Signed tickets
    for t, lines, client_name, sig in tickets:
        _ticket_page(
            pdf,
            t,
            lines,
            project_label="",
            contract_label=contract_label,
            client=client_name,
            signature_png=sig,
        )
    return bytes(pdf.output())
