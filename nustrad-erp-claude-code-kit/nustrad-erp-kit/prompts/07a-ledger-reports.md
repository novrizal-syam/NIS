# 07a · General ledger engine and financial reports
1. Consolidate `services/ledger.py`: `post_journal()` (balanced check, open-period check, dimensions, source link), reversal, manual journals with Lead Controller approval, posting-rule table as configuration covering every event in ACCOUNTING.md (refactor earlier phases to call it if they don't yet — no behaviour change).
2. Opening balance import (GL, AR, AP, stock, assets) as of the go-live date.
3. Multi-currency USD with FX rates and realised FX on settlement (7100).
4. Reports: general ledger, trial balance, P&L (month/YTD, by project), balance sheet, cash flow (direct, from bank accounts), dimension reports, management project P&L (DOR revenue vs actual incl. internal rates, committed, remaining budget). Excel and PDF export.
Tests: every posting rule balanced; closed period rejects; trial balance equals zero after the full scenario.
