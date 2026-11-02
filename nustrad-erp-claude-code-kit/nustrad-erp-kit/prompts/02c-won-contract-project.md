# 02c · Won → contract and draft project
1. "Tandai Menang" / "Tandai Kalah" (reason, winner price if known).
2. Won → ONE DB transaction: Contract (rate schedule from quotation after discount; manual rate lines allowed incl. equipment status rates, personnel/day, consumables cost + markup, mob/demob) + Project Draft (revenue = contract value; budget per cost element from quotation cost; Contingency = 5% from settings) + DMS project folder with the quotation linked.
3. Contract list/detail (rate schedule, client PO/SPK number, value, period, payment term, usage % field). Project list/detail (budget read-only; editing is phase 03).

Tests: won transaction totals per cost element, rollback on failure. Playwright happy path: lead → qualify → bid → quotation 34% → Head of Sales approves → send → won → contract + draft project.
