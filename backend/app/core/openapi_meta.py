"""OpenAPI metadata (10b): API description and one line per tag."""

DESCRIPTION = """
REST API of Nustrad ERP (PT Global Energi KITA). All endpoints live under `/api`.

**Authentication**: `POST /api/auth/login` returns a short-lived access token (Bearer) and sets a
refresh cookie; send `Authorization: Bearer <token>`. Every endpoint checks role, permission and
data scope; sensitive fields (salary, NIK, bank account, personal tax ID) are left out unless the
caller holds the matching permission.

**Errors**: JSON `{"code", "message", "details"}`; `message` is in Bahasa Indonesia.

**Money**: strings with whole rupiah (`"1250000"`); USD amounts carry two decimals.

**Dates**: ISO `YYYY-MM-DD`; timestamps in UTC; business dates in Asia/Jakarta.
"""

TAGS = [
    ("system", "Health and version"),
    ("setup", "First-run setup wizard"),
    ("auth", "Sign-in, tokens, 2FA, password"),
    ("users", "User administration"),
    ("roles", "Roles and permissions matrix"),
    ("sod", "Segregation of duties rules and exceptions"),
    ("admin", "Settings and administration"),
    ("workflow", "DOA engine: rules, approval inbox"),
    ("notifications", "In-app notifications"),
    ("audit", "Audit trail"),
    ("master", "Master data (clients, vendors, employees, assets, accounts ...)"),
    ("crm", "Leads and opportunities"),
    ("quotation", "Quotations"),
    ("tender", "Tenders"),
    ("contract", "Contracts"),
    ("project", "Projects and budgets"),
    ("budget", "Budget control and change requests"),
    ("procurement", "Purchase requisitions, RFQ, purchase orders"),
    ("inventory", "Goods receipts, material requests, stock"),
    ("operations", "Daily Operational Reports"),
    ("maintenance", "Equipment register and maintenance"),
    ("qhse", "QHSE: HIRADC, permits, inspections, incidents, CAPA"),
    ("billing", "Service tickets, invoices, receipts"),
    ("finance", "Vendor invoices and payables"),
    ("ledger", "General ledger, manual journals, financial reports"),
    ("treasury", "Bank accounts, reconciliation, payment runs, cash advances"),
    ("payroll", "Payroll, payslips, 1721-A1"),
    ("tax", "Monthly tax returns"),
    ("close", "Depreciation and period close"),
    ("capex", "CAPEX proposals and capitalisation"),
    ("letters", "Incoming and outgoing letters"),
    ("dms", "Documents, controlled documents, library, share links"),
    ("lms", "Training, competency matrix, certificates"),
    ("reporting", "Management reports and access review"),
    ("dashboard", "Process map, role dashboards, OKR, management pack"),
    ("integrations", "External adapters: Coretax/PJAP, bank, PSrE, e-Meterai, email, WhatsApp"),
    ("portal", "Client and vendor portals"),
]


def openapi_tags() -> list[dict[str, str]]:
    return [{"name": n, "description": d} for n, d in TAGS]
