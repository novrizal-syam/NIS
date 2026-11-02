"""System roles and their default permissions (from docs/domain/DOA.md).

Plain data so the Alembic data migration can use it. Editing this file does not
change an existing database: permissions are editable in Settings (phase 01a).
"""

from dataclasses import dataclass

from app.auth.permissions import MODULES, SENSITIVE_FIELDS, SENSITIVE_MODULE, Action, Scope

A = Action
ALL_ACTIONS = tuple(Action)
CRUD = (A.VIEW, A.CREATE, A.EDIT, A.DELETE, A.EXPORT)
WORK = (A.VIEW, A.CREATE, A.EDIT, A.SUBMIT, A.EXPORT)  # prepare and submit, no approval
READ = (A.VIEW, A.EXPORT)

Grant = tuple[str, str, str]  # module, action, scope


@dataclass(frozen=True)
class RoleDef:
    code: str
    name: str
    grants: tuple[Grant, ...] = ()
    requires_2fa: bool = False
    is_external: bool = False
    description: str = ""


def g(
    modules: str | tuple[str, ...], actions: tuple[Action, ...] | Action, scope: Scope
) -> list[Grant]:
    mods = (modules,) if isinstance(modules, str) else modules
    acts = (actions,) if isinstance(actions, Action) else actions
    return [(m, str(a), str(scope)) for m in mods for a in acts]


ALL_MODULES = tuple(MODULES)
SENSITIVE_ALL = [(SENSITIVE_MODULE, f, str(Scope.ALL)) for f in SENSITIVE_FIELDS]
# Every internal user can read master data, keep own documents and take training.
BASE = [
    *g("master", A.VIEW, Scope.ALL),
    *g("dms", (A.VIEW, A.CREATE), Scope.OWN),
    *g("lms", A.VIEW, Scope.OWN),
]


def _role(
    code: str, name: str, *grant_lists: list[Grant], base: bool = True, **kw: bool
) -> RoleDef:
    grants: list[Grant] = list(BASE) if base else []
    for lst in grant_lists:
        grants.extend(lst)
    # de-duplicate, keeping the widest scope per (module, action)
    rank = {"own": 0, "department": 1, "project": 2, "all": 3}
    best: dict[tuple[str, str], str] = {}
    for m, a, s in grants:
        if (m, a) not in best or rank[s] > rank[best[(m, a)]]:
            best[(m, a)] = s
    return RoleDef(
        code=code,
        name=name,
        grants=tuple(sorted((m, a, s) for (m, a), s in best.items())),
        **kw,  # type: ignore[arg-type]
    )


ALL = Scope.ALL
PRJ = Scope.PROJECT
OWN = Scope.OWN
OPS_MODULES = (
    "project",
    "budget",
    "operations",
    "maintenance",
    "qhse",
    "procurement",
    "inventory",
    "asset",
)

SYSTEM_ROLES: tuple[RoleDef, ...] = (
    _role(
        "super_admin",
        "Super Admin",
        g(ALL_MODULES, ALL_ACTIONS, ALL),
        SENSITIVE_ALL,
        requires_2fa=True,
    ),
    # IT administration only: no business approve/post (DOA.md).
    _role(
        "admin",
        "Admin",
        g(("users", "settings", "master", "workflow"), (*CRUD, A.ADMIN), ALL),
        g("audit", READ, ALL),
        requires_2fa=True,
    ),
    _role(
        "director",
        "Director",
        g(ALL_MODULES, (A.VIEW, A.EXPORT, A.APPROVE), ALL),
        g(("crm", "capex", "letters"), WORK, ALL),
        SENSITIVE_ALL,
        requires_2fa=True,
    ),
    _role(
        "shareholders",
        "Shareholders (RUPS)",
        g("capex", (A.VIEW, A.APPROVE), ALL),
        g("reporting", A.VIEW, ALL),
        base=False,
    ),
    _role(
        "head_of_sales",
        "Head of Sales & Ext. Comm.",
        g(("crm", "quotation", "tender", "contract"), (*WORK, A.DELETE, A.APPROVE), ALL),
        g("project", READ, ALL),
        g("reporting", READ, ALL),
    ),
    _role(
        "account_executive",
        "Account Executive",
        g(("crm", "quotation"), WORK, OWN),
        g(("contract", "tender"), A.VIEW, OWN),
    ),
    _role(
        "tender_specialist",
        "Tender Specialist",
        g("tender", (*WORK, A.DELETE), ALL),
        g(("crm", "quotation"), A.VIEW, ALL),
        g("dms", (A.VIEW, A.CREATE), ALL),
    ),
    _role(
        "billing_admin",
        "Billing Admin",
        g("billing", WORK, ALL),
        g(("operations", "contract"), A.VIEW, ALL),
    ),
    _role(
        "legal_liaison",
        "Legal & Liaison Officer",
        g("letters", WORK, ALL),
        g("contract", (A.VIEW, A.EDIT), ALL),
        g("dms", (*CRUD, A.SUBMIT), ALL),
    ),
    _role(
        "qhse_coordinator",
        "QHSE Coordinator",
        g("qhse", (*WORK, A.DELETE, A.APPROVE), ALL),
        g(("operations", "asset"), A.VIEW, ALL),
        g("lms", (A.VIEW, A.CREATE, A.EDIT), ALL),
    ),
    _role(
        "head_of_operation",
        "Head of Operation",
        g(OPS_MODULES, (A.VIEW, A.EXPORT, A.APPROVE), ALL),
        g(("project", "operations", "procurement"), WORK, ALL),
        g("treasury", (A.VIEW, A.APPROVE), ALL),  # cash advance approval
        g("tender", (A.VIEW, A.APPROVE), ALL),  # technical approval of tender packages
        g("reporting", READ, ALL),
    ),
    _role(
        "lead_engineer",
        "Lead Engineer (Planner)",
        g(("project", "budget"), WORK, PRJ),
        g("operations", A.VIEW, PRJ),
        g("procurement", WORK, PRJ),
    ),
    _role(
        "engineer",
        "Engineer",
        g("procurement", WORK, OWN),
        g("operations", (A.VIEW, A.CREATE), PRJ),
        g("project", A.VIEW, PRJ),
    ),
    *(
        _role(
            code,
            name,
            g("operations", (*WORK, A.APPROVE), PRJ),
            g("procurement", WORK, PRJ),
            g("project", A.VIEW, PRJ),
            g("inventory", A.VIEW, ALL),
            g("maintenance", (A.VIEW, A.CREATE), ALL),
        )
        for code, name in (
            ("ofs_superintendent", "OFS Superintendent"),
            ("epcom_superintendent", "EPCOM Superintendent"),
        )
    ),
    _role(
        "field_engineer",
        "Field Engineer",
        g("operations", WORK, PRJ),
        g("qhse", (A.VIEW, A.CREATE), PRJ),
        g("treasury", (A.VIEW, A.CREATE, A.SUBMIT), OWN),
    ),
    _role(
        "operation_staff",
        "Operation Staff",
        g("operations", WORK, PRJ),
        g("inventory", A.VIEW, ALL),
    ),
    _role(
        "asset_inventory_coordinator",
        "Asset & Inventory Coordinator",
        g(("asset", "inventory", "maintenance"), (*WORK, A.DELETE), ALL),
        g("procurement", A.VIEW, ALL),
    ),
    _role(
        "warehouse_head",
        "Warehouse Head",
        g("inventory", (*WORK, A.DELETE, A.APPROVE, A.POST), ALL),
        g(("procurement", "asset"), A.VIEW, ALL),
    ),
    _role(
        "lead_controller",
        "Lead Controller",
        g(("project", "budget"), (A.VIEW, A.EXPORT, A.APPROVE), ALL),
        g("finance", (*WORK, A.APPROVE, A.POST), ALL),
        g(("reporting", "audit"), READ, ALL),
        requires_2fa=True,
    ),
    _role(
        "head_of_finance",
        "Head of Finance & Support",
        g(
            ("finance", "treasury", "payroll", "tax", "billing", "procurement"),
            (A.VIEW, A.EXPORT, A.APPROVE),
            ALL,
        ),
        g(("reporting", "audit"), READ, ALL),
        SENSITIVE_ALL,
        requires_2fa=True,
    ),
    _role(
        "finance_officer",
        "Finance Officer",
        g("finance", (*WORK, A.POST), ALL),
        g("billing", WORK, ALL),
        g("treasury", A.VIEW, ALL),
    ),
    _role(
        "ap_accountant",
        "AP Accountant",
        g("procurement", A.VIEW, ALL),
        g("finance", (*WORK, A.POST), ALL),
        g("treasury", WORK, ALL),
        requires_2fa=True,
    ),
    # Cashier releases payment runs ("post"); never approves them.
    _role(
        "cashier",
        "Cashier",
        g("treasury", (A.VIEW, A.EXPORT, A.POST), ALL),
        g("finance", A.VIEW, ALL),
        requires_2fa=True,
    ),
    _role(
        "tax_specialist",
        "Tax Specialist",
        g("tax", (*WORK, A.POST), ALL),
        g(("finance", "billing"), A.VIEW, ALL),
    ),
    _role(
        "procurement_officer",
        "Procurement Officer",
        g("procurement", (*WORK, A.DELETE), ALL),
        g("master", (A.VIEW, A.CREATE, A.EDIT), ALL),
        g("inventory", A.VIEW, ALL),
    ),
    _role(
        "hcbp_officer",
        "HCBP Officer",
        g("payroll", WORK, ALL),
        g("master", (A.VIEW, A.CREATE, A.EDIT, A.EXPORT), ALL),
        g("lms", (*CRUD, A.SUBMIT), ALL),
        SENSITIVE_ALL,
        requires_2fa=True,
    ),
    _role(
        "client_rep",
        "Client Representative",
        g(("operations", "billing"), A.VIEW, PRJ),
        base=False,
        is_external=True,
    ),
    _role("vendor", "Vendor", base=False, is_external=True),
)

ROLE_CODES = frozenset(r.code for r in SYSTEM_ROLES)
