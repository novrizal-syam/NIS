"""Posting-rule table (ACCOUNTING.md · Posting rules) as configuration.

Every financial event names its legs: which amount (role) goes to which account on which side,
and which dimensions the line carries. Accounts are fixed codes or placeholders resolved at
posting time:
  @expense   expense account of the cost element (cost_elements.account_code)
  @variance  inventory variance account (setting inventory.variance_account, default 6100)
Finance can re-point a leg to another postable account with the setting
`ledger.posting_rules` = {"event": {"role": "account"}} (audited; Lead Controller).

A negative amount on a leg flips its side (e.g. a price variance that is a gain).
Zero legs are skipped. `post_event()` (services/ledger.py) builds the journal and
`post_journal()` still checks balance, accounts and the period.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Side = Literal["debit", "credit"]
DIMS = ("project", "wbs", "cost_element", "partner", "asset")


@dataclass(frozen=True)
class Leg:
    role: str
    side: Side
    account: str
    dims: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    event: str
    label: str
    legs: tuple[Leg, ...]
    used_by: str
    example: dict[str, Decimal] = field(default_factory=dict)


def D(v: int) -> Decimal:  # noqa: N802 - short for the examples
    return Decimal(v)


PJ = ("project", "wbs")
PJP = ("project", "wbs", "partner")

RULES: dict[str, Rule] = {
    r.event: r
    for r in (
        Rule(
            "dor_revenue",
            "DOR disetujui (pendapatan akrual)",
            (Leg("revenue", "debit", "1220", PJP), Leg("revenue", "credit", "4100", PJP)),
            "operations.dor_service",
            {"revenue": D(1000)},
        ),
        Rule(
            "dor_consumables",
            "DOR disetujui (material dari stok site)",
            (
                Leg("consumables", "debit", "5300", (*PJ, "cost_element")),
                Leg("consumables", "credit", "1310"),
            ),
            "operations.dor_service",
            {"consumables": D(1000)},
        ),
        Rule(
            "ticket_dispute",
            "Service ticket: baris di-dispute (pembalikan pendapatan)",
            (
                Leg("disputed", "debit", "4100", ("project", "partner")),
                Leg("disputed", "credit", "1220", ("project", "partner")),
            ),
            "billing.ticket_service",
            {"disputed": D(1000)},
        ),
        Rule(
            "customer_invoice",
            "Invoice pelanggan (faktur terbit)",
            (
                Leg("total", "debit", "1210", ("project", "partner")),
                Leg("subtotal", "credit", "1220", ("project", "partner")),
                Leg("ppn", "credit", "2210", ("partner",)),
            ),
            "billing.invoice_service",
            {"total": D(1110), "subtotal": D(1000), "ppn": D(110)},
        ),
        Rule(
            "customer_receipt",
            "Penerimaan pelanggan",
            (
                Leg("cash", "debit", "1110", ("partner",)),
                Leg("pph23", "debit", "1410", ("partner",)),
                Leg("fx_loss", "debit", "7100", ("partner",)),
                Leg("receivable", "credit", "1210", ("partner",)),
            ),
            "billing.receipt_service",
            {"cash": D(1088), "pph23": D(20), "fx_loss": D(2), "receivable": D(1110)},
        ),
        Rule(
            "material_issue",
            "Pengeluaran material (MR)",
            (
                Leg("issued", "debit", "5300", (*PJ, "cost_element")),
                Leg("issued", "credit", "1310"),
            ),
            "inventory.mr_service",
            {"issued": D(1000)},
        ),
        Rule(
            "goods_receipt",
            "Penerimaan barang/jasa (langsung ke proyek atau stok)",
            (
                Leg("direct", "debit", "@expense", (*PJP, "cost_element")),
                Leg("to_stock", "debit", "1310", ("partner",)),
                Leg("grir", "credit", "2120", PJP),
            ),
            "inventory.gr_service",
            {"direct": D(600), "to_stock": D(400), "grir": D(1000)},
        ),
        Rule(
            "vendor_invoice",
            "Invoice vendor cocok (3-way match)",
            (
                Leg("grir", "debit", "2120", PJP),
                Leg("price_variance", "debit", "@expense", (*PJP, "cost_element")),
                Leg("ppn", "debit", "1420", ("partner",)),
                Leg("payable", "credit", "2110", ("partner",)),
                Leg("pph23", "credit", "2230", ("partner",)),
            ),
            "finance.ap_service",
            {
                "grir": D(1000),
                "price_variance": D(-10),
                "ppn": D(109),
                "payable": D(1079),
                "pph23": D(20),
            },
        ),
        Rule(
            "stock_opname",
            "Selisih stock opname",
            (
                Leg("loss", "debit", "@variance"),
                Leg("loss", "credit", "1310"),
                Leg("gain", "debit", "1310"),
                Leg("gain", "credit", "@variance"),
            ),
            "inventory.stock_service",
            {"loss": D(300), "gain": D(100)},
        ),
        Rule(
            "maintenance_parts",
            "Suku cadang work order",
            (Leg("parts", "debit", "5200", ("asset",)), Leg("parts", "credit", "1310")),
            "maintenance.service",
            {"parts": D(1000)},
        ),
        Rule(
            "payroll",
            "Penggajian disetujui",
            (
                Leg("field_cost", "debit", "5100", PJ),
                Leg("office_cost", "debit", "6100"),
                Leg("net_salary", "credit", "2310", ("partner",)),
                Leg("pph21", "credit", "2220"),
                Leg("bpjs", "credit", "2240"),
            ),
            "payroll (07c)",
            {
                "field_cost": D(700),
                "office_cost": D(300),
                "net_salary": D(850),
                "pph21": D(50),
                "bpjs": D(100),
            },
        ),
        Rule(
            "payment_run",
            "Payment run dirilis",
            (
                Leg("payable", "debit", "2110", ("partner",)),
                Leg("salaries", "debit", "2310"),
                Leg("bpjs", "debit", "2240"),
                Leg("pph21", "debit", "2220"),
                Leg("pph23", "debit", "2230"),
                Leg("fx_loss", "debit", "7100", ("partner",)),
                Leg("bank", "credit", "1110"),
            ),
            "treasury (07b)",
            {
                "payable": D(500),
                "salaries": D(300),
                "bpjs": D(100),
                "pph21": D(50),
                "pph23": D(50),
                "bank": D(1000),
            },
        ),
        Rule(
            "cash_advance_disbursed",
            "Uang muka kerja dicairkan",
            (Leg("advance", "debit", "1120", ("partner",)), Leg("bank", "credit", "1110")),
            "treasury (07b)",
            {"advance": D(1000), "bank": D(1000)},
        ),
        Rule(
            "cash_advance_settled",
            "Uang muka kerja dipertanggungjawabkan",
            (
                Leg("expense", "debit", "@expense", (*PJ, "cost_element")),
                Leg("refund", "debit", "1110"),
                Leg("advance", "credit", "1120", ("partner",)),
                Leg("reimbursement", "credit", "1110"),
            ),
            "treasury (07b)",
            {"expense": D(900), "refund": D(100), "advance": D(1000)},
        ),
        Rule(
            "tax_paid",
            "Setoran PPh",
            (
                Leg("pph21", "debit", "2220"),
                Leg("pph23", "debit", "2230"),
                Leg("bank", "credit", "1110"),
            ),
            "tax (07d)",
            {"pph21": D(600), "pph23": D(400), "bank": D(1000)},
        ),
        Rule(
            "ppn_settled",
            "Penyelesaian PPN",
            (
                Leg("output", "debit", "2210"),
                Leg("input", "credit", "1420"),
                Leg("bank", "credit", "1110"),
            ),
            "tax (07d)",
            {"output": D(1000), "input": D(700), "bank": D(300)},
        ),
        Rule(
            "capex_milestone",
            "Termin CAPEX dibayar",
            (
                Leg("auc", "debit", "1520", ("asset",)),
                Leg("bank", "credit", "1110"),
                Leg("payable", "credit", "2110", ("partner",)),
            ),
            "capex (08)",
            {"auc": D(1000), "bank": D(1000)},
        ),
        Rule(
            "asset_capitalised",
            "Aset dikapitalisasi",
            (Leg("cost", "debit", "1510", ("asset",)), Leg("cost", "credit", "1520", ("asset",))),
            "capex (08)",
            {"cost": D(1000)},
        ),
        Rule(
            "depreciation",
            "Penyusutan bulanan",
            (
                Leg("office", "debit", "6200", ("asset",)),
                Leg("project", "debit", "5200", ("asset", "project")),
                Leg("accumulated", "credit", "1590", ("asset",)),
            ),
            "asset (08)",
            {"office": D(400), "project": D(600), "accumulated": D(1000)},
        ),
        Rule(
            "fx_settlement",
            "Selisih kurs terealisasi",
            (
                Leg("loss", "debit", "7100", ("partner",)),
                Leg("loss", "credit", "1110"),
            ),
            "billing / treasury",
            {"loss": D(-25)},
        ),
    )
}
