"""Conflicting role pairs from docs/domain/DOA.md (segregation of duties)."""

RULES: tuple[tuple[str, str, str], ...] = (
    ("ap_accountant", "cashier", "Payment run: penyiap ≠ perilis"),
    ("ap_accountant", "head_of_finance", "Payment run: penyiap ≠ penyetuju"),
    ("ap_accountant", "director", "Payment run: penyiap ≠ penyetuju (> Rp 1 M)"),
    ("cashier", "head_of_finance", "Payment run: penyetuju ≠ perilis"),
    ("cashier", "director", "Payment run: penyetuju ≠ perilis (> Rp 1 M)"),
    ("cashier", "procurement_officer", "Pengubah rekening vendor ≠ perilis pembayaran"),
    ("head_of_finance", "procurement_officer", "Pengubah rekening vendor ≠ penyetuju pembayaran"),
    ("finance_officer", "lead_controller", "Jurnal manual: pembuat ≠ penyetuju"),
    ("hcbp_officer", "head_of_finance", "Penggajian: penghitung ≠ penyetuju"),
    ("field_engineer", "ofs_superintendent", "DOR: pengaju ≠ penyetuju"),
    ("field_engineer", "epcom_superintendent", "DOR: pengaju ≠ penyetuju"),
    ("operation_staff", "ofs_superintendent", "DOR: pengaju ≠ penyetuju"),
    ("operation_staff", "epcom_superintendent", "DOR: pengaju ≠ penyetuju"),
)


def norm(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)
