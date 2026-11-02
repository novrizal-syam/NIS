"""Excel export for every list screen (CLAUDE.md UI rules). Money stays integer rupiah."""

import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

JAKARTA = ZoneInfo("Asia/Jakarta")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

Kind = Literal["text", "idr", "number", "date", "datetime"]
FORMATS: dict[str, str] = {
    "idr": '"Rp" #,##0',
    "number": "#,##0",
    "date": "d mmm yyyy",
    "datetime": "d mmm yyyy hh:mm",
}


@dataclass(frozen=True)
class Column:
    header: str
    key: str
    kind: Kind = "text"
    width: int = 18


def _cell(value: Any, kind: Kind) -> Any:
    if value is None:
        return None
    if kind == "idr":
        return int(Decimal(value))
    if isinstance(value, datetime):
        # Excel has no time zones: write Jakarta wall-clock time.
        return value.astimezone(JAKARTA).replace(tzinfo=None)
    if isinstance(value, date | int | float | Decimal):
        return value
    return str(value)


def build_xlsx(sheet: str, columns: Sequence[Column], rows: Iterable[dict[str, Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet[:31]
    ws.append([c.header for c in columns])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="F1F2F2")
    for row in rows:
        ws.append([_cell(row.get(c.key), c.kind) for c in columns])
    for idx, col in enumerate(columns, start=1):
        letter = get_column_letter(idx)
        ws.column_dimensions[letter].width = col.width
        if col.kind in FORMATS:
            for (cell,) in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                cell.number_format = FORMATS[col.kind]
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_response(
    filename: str, sheet: str, columns: Sequence[Column], rows: Iterable[dict[str, Any]]
) -> StreamingResponse:
    data = build_xlsx(sheet, columns, rows)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
