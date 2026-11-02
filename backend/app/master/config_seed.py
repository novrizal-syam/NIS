"""Configuration (not demo data) from docs/domain/ACCOUNTING.md: currencies, chart of
accounts, cost elements. Used by the data migration; edit later in Data Master."""

CURRENCIES = (("IDR", "Rupiah", 0), ("USD", "Dolar AS", 2))

# code, name, type, normal balance
ACCOUNTS: tuple[tuple[str, str, str, str], ...] = (
    ("1110", "Bank Mandiri IDR", "asset", "debit"),
    ("1111", "Bank USD", "asset", "debit"),
    ("1120", "Uang muka kerja & kas kecil", "asset", "debit"),
    ("1210", "Piutang usaha", "asset", "debit"),
    ("1220", "Pendapatan belum ditagih (WIP)", "asset", "debit"),
    ("1310", "Persediaan", "asset", "debit"),
    ("1410", "PPh 23 dibayar dimuka", "asset", "debit"),
    ("1420", "PPN masukan", "asset", "debit"),
    ("1510", "Aset tetap", "asset", "debit"),
    ("1520", "Aset dalam penyelesaian (AUC)", "asset", "debit"),
    ("1590", "Akumulasi penyusutan", "asset", "credit"),
    ("2110", "Utang usaha", "liability", "credit"),
    ("2120", "GR/IR clearing", "liability", "credit"),
    ("2210", "PPN keluaran", "liability", "credit"),
    ("2220", "Utang PPh 21", "liability", "credit"),
    ("2230", "Utang PPh 23", "liability", "credit"),
    ("2240", "Utang BPJS", "liability", "credit"),
    ("2310", "Utang gaji", "liability", "credit"),
    ("2410", "Utang bank", "liability", "credit"),
    ("3100", "Modal saham", "equity", "credit"),
    ("3200", "Laba ditahan", "equity", "credit"),
    ("4100", "Pendapatan jasa", "revenue", "credit"),
    ("5100", "Tenaga kerja langsung", "expense", "debit"),
    ("5200", "Peralatan & pemeliharaan", "expense", "debit"),
    ("5300", "Bahan habis pakai & kimia", "expense", "debit"),
    ("5400", "Sewa peralatan", "expense", "debit"),
    ("5500", "Subkontrak", "expense", "debit"),
    ("5600", "Logistik & transport", "expense", "debit"),
    ("5700", "QHSE", "expense", "debit"),
    ("6100", "Umum & administrasi", "expense", "debit"),
    ("6200", "Penyusutan", "expense", "debit"),
    ("7100", "Laba/rugi selisih kurs", "expense", "debit"),
)

# code, name, expense account (None = Contingency: locked reserve, never posted directly)
COST_ELEMENTS: tuple[tuple[str, str, str | None], ...] = (
    ("MANPOWER", "Tenaga kerja", "5100"),
    ("EQUIP-OWN", "Peralatan milik (tarif internal)", "5200"),
    ("EQUIP-RENT", "Peralatan sewa", "5400"),
    ("CONSUMABLE", "Bahan habis pakai & kimia", "5300"),
    ("SUBCONTRACT", "Subkontrak", "5500"),
    ("LOGISTICS", "Logistik & transport", "5600"),
    ("QHSE", "QHSE", "5700"),
    ("CONTINGENCY", "Kontinjensi", None),
)
