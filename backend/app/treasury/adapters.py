"""Bank file adapters for payment runs.

`csv` writes a generic bulk-transfer CSV the Cashier uploads to internet banking. Host-to-host
adapters (Mandiri, BRI, BNI, BCA) implement the same interface later: `build()` returns the file
to send and `send()` transmits it (the CSV adapter does not transmit)."""

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Transfer:
    seq: int
    payee: str
    bank_name: str | None
    account_no: str | None
    account_name: str | None
    amount: Decimal
    reference: str


@dataclass(frozen=True)
class BankFile:
    filename: str
    content_type: str
    content: bytes


class BankAdapter(Protocol):
    code: str
    label: str
    host_to_host: bool

    def build(
        self, run_number: str, pay_date: date, debit_account: str, transfers: list[Transfer]
    ) -> BankFile: ...

    async def send(self, file: BankFile) -> str | None:
        """Transmit to the bank; returns the bank's reference (None when not transmitted)."""
        ...


class CsvBulkTransfer:
    code = "csv"
    label = "CSV bulk transfer (unggah manual)"
    host_to_host = False

    def build(
        self, run_number: str, pay_date: date, debit_account: str, transfers: list[Transfer]
    ) -> BankFile:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=",", lineterminator="\r\n")
        w.writerow(
            [
                "no",
                "debit_account",
                "value_date",
                "beneficiary_bank",
                "beneficiary_account",
                "beneficiary_name",
                "amount",
                "currency",
                "remark",
            ]
        )
        for t in transfers:
            w.writerow(
                [
                    t.seq,
                    debit_account,
                    pay_date.strftime("%Y%m%d"),
                    t.bank_name or "",
                    t.account_no or "",
                    (t.account_name or t.payee)[:70],
                    format(t.amount, "f"),
                    "IDR",
                    f"{run_number} {t.reference}"[:35],
                ]
            )
        return BankFile(f"{run_number}-bulk-transfer.csv", "text/csv", buf.getvalue().encode())

    async def send(self, file: BankFile) -> str | None:
        return None


ADAPTERS: dict[str, BankAdapter] = {"csv": CsvBulkTransfer()}


def get(code: str) -> BankAdapter:
    return ADAPTERS.get(code) or ADAPTERS["csv"]
