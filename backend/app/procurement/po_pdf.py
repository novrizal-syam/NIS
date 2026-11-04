"""Purchase order PDF on the GEK letterhead."""

from datetime import date

from fpdf import FontFace

from app.crm.quotation_pdf import Letterhead, _Pdf, _t, id_date
from app.master.models import Vendor
from app.procurement.models import PurchaseOrder, PurchaseOrderLine
from app.services.money import format_idr, format_number


def render(
    head: Letterhead,
    po: PurchaseOrder,
    lines: list[PurchaseOrderLine],
    vendor: Vendor,
    *,
    project_label: str,
    issued: date,
    signer: str,
) -> bytes:
    pdf = _Pdf(unit="mm", format="A4")
    pdf.head = head
    pdf.draft = po.status == "draft"
    pdf.set_margins(15, 12, 15)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "PURCHASE ORDER", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    rev = f" Rev.{po.revision}" if po.revision else ""
    for k, v in (
        ("Nomor", f"{po.number}{rev}"),
        ("Tanggal", id_date(issued, long=True)),
        ("Proyek", project_label),
        ("Kirim ke", po.delivery_location),
        ("Tanggal kirim", id_date(po.delivery_date, long=True) if po.delivery_date else "-"),
        ("Pembayaran", po.payment_terms or "-"),
    ):
        pdf.cell(28, 5, k)
        pdf.cell(4, 5, ":")
        pdf.multi_cell(0, 5, _t(v), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.cell(0, 5, "Kepada:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, _t(vendor.name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for line in (vendor.address, f"NPWP {vendor.npwp}" if vendor.npwp else None):
        if line:
            pdf.multi_cell(0, 5, _t(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

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
                    _t(x.uom),
                    format_idr(x.unit_price),
                    format_idr(x.amount),
                )
            )
    pdf.ln(1)
    pct = format_number(po.ppn_pct, 0 if po.ppn_pct == int(po.ppn_pct) else 2)
    for i, (caption, amount) in enumerate(
        (("Subtotal (DPP)", po.subtotal), (f"PPN {pct}%", po.ppn_amount), ("Total", po.total))
    ):
        pdf.set_font("Helvetica", "B" if i == 2 else "", 9)
        pdf.cell(sum(widths) - 30, 6, caption, align="R")
        pdf.cell(30, 6, format_idr(amount), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    if po.terms:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, "Syarat dan ketentuan", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _t(po.terms), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.cell(0, 5, "Hormat kami,", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _t(head.company.get("legal_name")), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(16)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, _t(signer), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
