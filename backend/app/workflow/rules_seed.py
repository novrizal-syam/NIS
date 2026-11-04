"""DOA rules from docs/domain/DOA.md (proposals from GEK-BPM-001; editable in Settings,
changes need Director approval). Plain data, used by the data migration."""

from dataclasses import dataclass
from typing import Any

# doc_type -> (label, RBAC module whose `approve` permission approvers also need)
DOC_TYPES: dict[str, tuple[str, str]] = {
    "bid_decision": ("Keputusan bid/no-bid", "crm"),
    "quotation": ("Penawaran", "quotation"),
    "tender_package": ("Paket tender", "tender"),
    "project_budget": ("Anggaran proyek", "budget"),
    "bcr": ("Perubahan anggaran (BCR)", "budget"),
    "purchase_requisition": ("Purchase Requisition", "procurement"),
    "rfq_award": ("Penetapan pemenang RFQ", "procurement"),
    "po_revision": ("Revisi PO (nilai naik)", "procurement"),
    "dor": ("Daily Operation Report", "operations"),
    "cash_advance": ("Uang muka kerja", "treasury"),
    "manual_journal": ("Jurnal manual", "finance"),
    "payroll": ("Penggajian", "payroll"),
    "payment_run": ("Payment run", "treasury"),
    "capex": ("CAPEX", "capex"),
    "outgoing_letter": ("Surat keluar", "letters"),
    "sop_release": ("Rilis SOP", "dms"),
    "doa_change": ("Perubahan aturan DOA", "workflow"),
    "sod_exception": ("Pengecualian SoD", "users"),
}

M = 1_000_000


def le(field: str, value: int) -> dict[str, Any]:
    return {"field": field, "op": "<=", "value": value}


def gt(field: str, value: int) -> dict[str, Any]:
    return {"field": field, "op": ">", "value": value}


@dataclass(frozen=True)
class StepDef:
    seq: int
    role: str
    label: str = ""
    scope: str = "all"


@dataclass(frozen=True)
class RuleDef:
    doc_type: str
    name: str
    steps: tuple[StepDef, ...]
    condition: dict[str, Any] | None = None
    priority: int = 100
    escalation_hours: int = 48
    escalate_to_role: str | None = "director"


def single(doc_type: str, role: str, name: str, **kw: Any) -> RuleDef:
    return RuleDef(doc_type, name, (StepDef(1, role),), **kw)


RULES: tuple[RuleDef, ...] = (
    single("bid_decision", "director", "Semua bid/no-bid"),
    single(
        "quotation",
        "head_of_sales",
        "Margin ≥ 25%",
        condition={"field": "margin_pct", "op": ">=", "value": 25},
        priority=10,
        escalate_to_role="director",
    ),
    single(
        "quotation",
        "director",
        "Margin < 25%",
        condition={"field": "margin_pct", "op": "<", "value": 25},
        priority=20,
    ),
    RuleDef(
        "tender_package",
        "Teknis ‖ komersial paralel",
        (StepDef(1, "head_of_operation", "Teknis"), StepDef(1, "director", "Komersial")),
    ),
    RuleDef(
        "project_budget",
        "Biaya ≤ Rp 2 M",
        (StepDef(1, "lead_controller", "Review controller"), StepDef(2, "head_of_operation")),
        condition=le("total_cost", 2_000 * M),
        priority=10,
    ),
    RuleDef(
        "project_budget",
        "Biaya > Rp 2 M",
        (StepDef(1, "lead_controller", "Review controller"), StepDef(2, "director")),
        condition=gt("total_cost", 2_000 * M),
        priority=20,
    ),
    single(
        "bcr",
        "head_of_operation",
        "Kontinjensi, transfer, atau kenaikan ≤ 10%",
        condition={
            "all": [
                {"field": "revenue_change", "op": "!=", "value": True},
                {
                    "any": [
                        {
                            "field": "source",
                            "op": "in",
                            "value": ["contingency_release", "transfer"],
                        },
                        {"field": "increase_pct", "op": "<=", "value": 10},
                    ]
                },
            ]
        },
        priority=10,
    ),
    single("bcr", "director", "Kenaikan > 10% atau perubahan pendapatan", priority=20),
    single(
        "purchase_requisition",
        "head_of_operation",
        "≤ Rp 50 jt",
        condition=le("amount", 50 * M),
        priority=10,
    ),
    single(
        "purchase_requisition",
        "head_of_finance",
        "≤ Rp 500 jt",
        condition=le("amount", 500 * M),
        priority=20,
    ),
    single("purchase_requisition", "director", "> Rp 500 jt", priority=30),
    # PO revision with a higher value: same thresholds as the PR, on the new PO value.
    single(
        "po_revision",
        "head_of_operation",
        "≤ Rp 50 jt",
        condition=le("amount", 50 * M),
        priority=10,
    ),
    single(
        "po_revision",
        "head_of_finance",
        "≤ Rp 500 jt",
        condition=le("amount", 500 * M),
        priority=20,
    ),
    single("po_revision", "director", "> Rp 500 jt", priority=30),
    single(
        "rfq_award",
        "head_of_finance",
        "Vendor bukan skor terbaik (alasan tertulis)",
        condition={"field": "non_best_score", "op": "==", "value": True},
    ),
    RuleDef(
        "dor",
        "Proyek EPCOM",
        (StepDef(1, "epcom_superintendent", scope="project"),),
        condition={"field": "service_line", "op": "==", "value": "epcom"},
        priority=10,
        escalation_hours=16,
        escalate_to_role="head_of_operation",
    ),
    RuleDef(
        "dor",
        "Proyek OFS",
        (StepDef(1, "ofs_superintendent", scope="project"),),
        priority=20,
        escalation_hours=16,
        escalate_to_role="head_of_operation",
    ),
    single("cash_advance", "head_of_operation", "Semua uang muka"),
    single("manual_journal", "lead_controller", "Semua jurnal manual"),
    single("payroll", "head_of_finance", "Semua penggajian"),
    single(
        "payment_run",
        "head_of_finance",
        "≤ Rp 1 M (lalu dirilis Kasir)",
        condition=le("amount", 1_000 * M),
        priority=10,
    ),
    single("payment_run", "director", "> Rp 1 M (lalu dirilis Kasir)", priority=20),
    RuleDef(
        "capex",
        "> Rp 5 M: Direktur lalu RUPS",
        (StepDef(1, "director"), StepDef(2, "shareholders", "RUPS")),
        condition=gt("amount", 5_000 * M),
        priority=10,
    ),
    single("capex", "director", "≤ Rp 5 M", priority=20),
    single("outgoing_letter", "director", "Semua surat keluar"),
    single("sop_release", "director", "Semua rilis SOP"),
    single("doa_change", "director", "Semua perubahan DOA", escalate_to_role=None),
    single("sod_exception", "director", "Semua pengecualian SoD", escalate_to_role=None),
)
