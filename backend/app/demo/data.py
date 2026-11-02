"""Demo content. All names are fictional; amounts are plausible examples, not GEK data."""

from datetime import date

DEMO_PASSWORD_DEFAULT = "Demo-GEK-2026"  # noqa: S105 - demo users only, overridable via DEMO_PASSWORD
EMAIL_DOMAIN = "demo.gek.co.id"

DEPARTMENTS = (
    ("DIR", "Direksi"),
    ("OPS", "Operasi"),
    ("ENG", "Engineering"),
    ("SALES", "Sales & Komunikasi Eksternal"),
    ("FIN", "Keuangan & Support"),
    ("HC", "Human Capital"),
    ("PROC", "Pengadaan"),
    ("QHSE", "QHSE"),
    ("WH", "Gudang & Aset"),
    ("IT", "Teknologi Informasi"),
)

COST_CENTERS = (
    ("CC-DIR", "Direksi", "DIR"),
    ("CC-OPS", "Operasi lapangan", "OPS"),
    ("CC-ENG", "Engineering", "ENG"),
    ("CC-SALES", "Sales", "SALES"),
    ("CC-FIN", "Keuangan", "FIN"),
    ("CC-HC", "Human Capital", "HC"),
    ("CC-PROC", "Pengadaan", "PROC"),
    ("CC-QHSE", "QHSE", "QHSE"),
    ("CC-WH", "Gudang Base Cilegon", "WH"),
)

# role code -> (full name, department)
USERS: dict[str, tuple[str, str]] = {
    "super_admin": ("Andi Pratama", "IT"),
    "admin": ("Yoga Saputra", "IT"),
    "director": ("Hendra Wijaksono", "DIR"),
    "shareholders": ("Ratna Kusumawardani", "DIR"),
    "head_of_sales": ("Bayu Nugroho", "SALES"),
    "account_executive": ("Citra Lestari", "SALES"),
    "tender_specialist": ("Fajar Ramadhan", "SALES"),
    "billing_admin": ("Indah Permatasari", "FIN"),
    "legal_liaison": ("Dimas Hutapea", "DIR"),
    "qhse_coordinator": ("Wulan Sari", "QHSE"),
    "head_of_operation": ("Rina Wijaya", "OPS"),
    "lead_engineer": ("Teguh Santoso", "ENG"),
    "engineer": ("Budi Hartono", "ENG"),
    "ofs_superintendent": ("Rudi Simanjuntak", "OPS"),
    "epcom_superintendent": ("Agung Prasetyo", "OPS"),
    "field_engineer": ("Eko Firmansyah", "OPS"),
    "operation_staff": ("Joko Susilo", "OPS"),
    "asset_inventory_coordinator": ("Sinta Maharani", "WH"),
    "warehouse_head": ("Hadi Kurniawan", "WH"),
    "lead_controller": ("Maya Anggraini", "FIN"),
    "head_of_finance": ("Siti Rahmawati", "FIN"),
    "finance_officer": ("Putri Handayani", "FIN"),
    "ap_accountant": ("Lina Marlina", "FIN"),
    "cashier": ("Sari Puspitasari", "FIN"),
    "tax_specialist": ("Arif Hidayat", "FIN"),
    "procurement_officer": ("Dewi Anggraeni", "PROC"),
    "hcbp_officer": ("Nadia Putri", "HC"),
    "client_rep": ("Thomas Siregar", "OPS"),
    "vendor": ("Ahmad Fauzi", "PROC"),
}

CLIENTS = (
    ("CL-001", "PT Energi Rokan Hulu (demo)", "01.234.567.8-215.000", "valid", 30, "IDR"),
    ("CL-002", "PT Migas Jambi Merang (demo)", "02.345.678.9-331.000", "valid", 45, "IDR"),
    ("CL-003", "Mahakam Offshore Ltd (demo)", "03.456.789.0-091.000", "pending", 60, "USD"),
    ("CL-004", "PT Sumatera Gas Bumi (demo)", "04.567.890.1-123.000", "valid", 30, "IDR"),
    ("CL-005", "PT Natuna Laut Energi (demo)", "05.678.901.2-215.000", "expired", 30, "IDR"),
)

VENDOR_CATEGORIES = ("equipment_rental", "chemicals", "logistics", "subcontract", "spare_parts")
VENDOR_NAMES = {
    "equipment_rental": ("PT Sewa Alat Migas", "PT Pompa Prima Teknik", "CV Kompresor Andalan"),
    "chemicals": ("PT Kimia Sumur Abadi", "PT Surya Chemical Services", "CV Larutan Prima"),
    "logistics": (
        "PT Trans Cilegon Logistik",
        "PT Samudra Kargo Nusantara",
        "CV Angkut Lintas Sumatra",
    ),
    "subcontract": (
        "PT Jasa Welltest Mandiri",
        "PT Rekayasa Proses Indonesia",
        "CV Inspeksi Teknik",
    ),
    "spare_parts": ("PT Suku Cadang Industri", "PT Seal & Valve Indonesia", "CV Baut Mur Sentosa"),
}

FIELD_EMPLOYEES = (
    ("EMP-F01", "Eko Firmansyah", "Field Engineer", 14_500_000, "K/1"),
    ("EMP-F02", "Joko Susilo", "Operator Senior", 9_800_000, "K/2"),
    ("EMP-F03", "Agus Santoso", "Operator Pompa", 8_200_000, "K/0"),
    ("EMP-F04", "Dedi Kurniadi", "Operator Separator", 8_200_000, "TK/0"),
    ("EMP-F05", "Rizky Maulana", "Mekanik", 7_900_000, "TK/0"),
    ("EMP-F06", "Yusuf Hakim", "Operator Nitrogen", 8_500_000, "K/1"),
    ("EMP-F07", "Bambang Sudirman", "Welltest Supervisor", 16_000_000, "K/3"),
    ("EMP-F08", "Andre Wibowo", "HSE Officer Lapangan", 9_000_000, "TK/1"),
)
OFFICE_EMPLOYEES = (
    ("EMP-O01", "Rina Wijaya", "Head of Operation", "OPS", 32_000_000, "K/2"),
    ("EMP-O02", "Siti Rahmawati", "Head of Finance & Support", "FIN", 30_000_000, "K/1"),
    ("EMP-O03", "Dewi Anggraeni", "Procurement Officer", "PROC", 11_000_000, "TK/0"),
    ("EMP-O04", "Nadia Putri", "HCBP Officer", "HC", 10_500_000, "TK/0"),
    ("EMP-O05", "Sari Puspitasari", "Kasir", "FIN", 8_000_000, "K/0"),
    ("EMP-O06", "Maya Anggraini", "Lead Controller", "FIN", 22_000_000, "K/1"),
)

ITEMS = (
    ("ITM-001", "Seal kit pompa triplex", "set", "spare_parts", 4, 2_350_000),
    ("ITM-002", "Hose nitrogen 2 in x 30 m", "roll", "hose", 2, 7_800_000),
    ("ITM-003", "Gasket ring RX-24", "pcs", "spare_parts", 20, 185_000),
    ("ITM-004", "Demulsifier", "drum", "chemicals", 6, 6_400_000),
    ("ITM-005", "Corrosion inhibitor", "drum", "chemicals", 6, 5_900_000),
    ("ITM-006", "Filter element separator", "pcs", "spare_parts", 10, 1_250_000),
    ("ITM-007", "Oli mesin 15W-40", "pail", "consumable", 12, 1_150_000),
    ("ITM-008", "Coverall FR", "pcs", "ppe", 30, 650_000),
    ("ITM-009", "Safety helmet", "pcs", "ppe", 30, 210_000),
    ("ITM-010", "Pressure gauge 0-5000 psi", "pcs", "instrument", 5, 2_750_000),
)

WAREHOUSES = (
    ("WH-CLG", "Base Cilegon", "base", "Cilegon, Banten", None),
    ("WH-RKN", "Site Rokan", "site", "Duri, Riau", None),
)

ASSETS = (
    ("AST-SEP-01", "Separator 3-phase 12K", "Separator", "A", 18_000_000, "SEP-12K-0091"),
    ("AST-PMP-01", "Pump unit triplex 600 HP", "Pumping unit", "A", 12_500_000, "PU-600-2231"),
    ("AST-BST-01", "Booster pump 150 HP", "Pumping unit", "B", 4_500_000, "BP-150-0412"),
    ("AST-N2-01", "Nitrogen unit 1500 scfm", "Nitrogen unit", "A", 15_000_000, "N2-1500-0077"),
    ("AST-EPF-01", "Early production facility skid", "EPF", "A", 35_000_000, "EPF-0003"),
    ("AST-GEN-01", "Genset 250 kVA", "Utility", "C", 2_200_000, "GEN-250-1180"),
)

# code, name, unit, unit cost, unit price, cost element (the 8 demo services from the prompt)
PRICE_ITEMS = (
    ("SRV-PUMP", "Pump unit (operating)", "hari", 9_500_000, 14_000_000, "EQUIP-OWN"),
    ("SRV-BOOST", "Booster pump (operating)", "hari", 3_200_000, 5_000_000, "EQUIP-OWN"),
    ("SRV-FE", "Field engineer", "hari", 1_800_000, 3_000_000, "MANPOWER"),
    ("SRV-OPR", "Operator", "hari", 950_000, 1_600_000, "MANPOWER"),
    ("SRV-CHEM", "Chemicals package", "paket", 18_000_000, 24_000_000, "CONSUMABLE"),
    ("SRV-N2", "Nitrogen unit (operating)", "hari", 11_000_000, 17_500_000, "EQUIP-OWN"),
    ("SRV-MOB", "Mobilisasi / demobilisasi", "lumpsum", 45_000_000, 60_000_000, "LOGISTICS"),
    ("SRV-HSE", "HSE package", "hari", 1_200_000, 2_000_000, "QHSE"),
)

PERIOD_YEAR = 2026
OPEN_MONTH = 10  # Jan-Sep closed, Oct open, Nov-Dec not opened yet

FX = (("USD", date(2026, 10, 1), "16450.0000", "BI"),)
