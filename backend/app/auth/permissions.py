"""Permission vocabulary: module x action, data scope, sensitive fields.

A grant is (module, action, scope). Users can hold several roles; the effective
scope for (module, action) is the widest scope across their roles.
"""

from enum import StrEnum


class Action(StrEnum):
    VIEW = "view"
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    SUBMIT = "submit"
    APPROVE = "approve"
    POST = "post"
    EXPORT = "export"
    ADMIN = "admin"


class Scope(StrEnum):
    OWN = "own"
    DEPARTMENT = "department"
    PROJECT = "project"
    ALL = "all"


# Widest wins when a user's roles grant the same (module, action) twice.
SCOPE_RANK: dict[Scope, int] = {Scope.OWN: 0, Scope.DEPARTMENT: 1, Scope.PROJECT: 2, Scope.ALL: 3}

# module -> Bahasa Indonesia label (used in error messages and the permission matrix)
MODULES: dict[str, str] = {
    "crm": "Lead & Peluang",
    "quotation": "Penawaran",
    "tender": "Tender",
    "contract": "Kontrak",
    "project": "Proyek",
    "budget": "Anggaran",
    "procurement": "Pengadaan",
    "inventory": "Persediaan",
    "operations": "Operasi (DOR)",
    "maintenance": "Pemeliharaan",
    "qhse": "QHSE",
    "billing": "Penagihan",
    "finance": "Keuangan",
    "treasury": "Treasury",
    "payroll": "Penggajian",
    "tax": "Pajak",
    "capex": "CAPEX",
    "asset": "Aset",
    "dms": "Dokumen",
    "lms": "Pelatihan",
    "letters": "Surat",
    "master": "Data Master",
    "users": "Pengguna & Peran",
    "settings": "Pengaturan",
    "audit": "Jejak Audit",
    "workflow": "Persetujuan (DOA)",
    "reporting": "Laporan",
    "portal": "Portal klien & vendor",
}

ACTION_LABELS: dict[Action, str] = {
    Action.VIEW: "melihat",
    Action.CREATE: "membuat",
    Action.EDIT: "mengubah",
    Action.DELETE: "menghapus",
    Action.SUBMIT: "mengajukan",
    Action.APPROVE: "menyetujui",
    Action.POST: "memposting",
    Action.EXPORT: "mengekspor",
    Action.ADMIN: "mengelola",
}

# Sensitive personal data (UU 27/2022 PDP). Granted as module "sensitive", action = field.
SENSITIVE_MODULE = "sensitive"
SENSITIVE_FIELDS: dict[str, str] = {
    "salary": "Gaji",
    "nik": "NIK",
    "bank_account": "Rekening bank",
    "tax_id": "NPWP pribadi",
}


def is_valid_grant(module: str, action: str) -> bool:
    if module == SENSITIVE_MODULE:
        return action in SENSITIVE_FIELDS
    return module in MODULES and action in Action.__members__.values()
