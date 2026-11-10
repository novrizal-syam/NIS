# Performance check (phase 10e)

Target: the main pages answer in **under 2 seconds with 50,000 transactions**.

## How it is measured

`backend/tests/test_performance.py` is opt-in because it seeds about 200,000 rows:

```bash
cd backend && PERF=1 pytest tests/test_performance.py -s
```

It seeds 50,000 posted journals (100,000 lines) over ten months, 5,000 customer invoices,
5,000 vendor invoices, 50,000 audit records and 2,000 notifications with SQL, runs `ANALYZE`,
then calls each main screen's API once to warm up and once timed. The test fails if any
page takes 2 s or more.

## Result (10 Nov 2026, dev container, PostgreSQL 16)

| Page (API) | Time |
| --- | ---: |
| Journals, page 1 | 17 ms |
| Journals, page 500 with search | 73 ms |
| Trial balance | 46 ms |
| General ledger 1110, one month | 272 ms |
| Profit and loss | 62 ms |
| Balance sheet | 106 ms |
| Cash flow, ten months | 883 ms |
| Customer invoices | 22 ms |
| AR aging | 61 ms |
| Vendor invoices | 19 ms |
| Audit log, page 1 | 27 ms |
| Process map | 25 ms |
| OKR | 89 ms |
| Finance dashboard | 167 ms |
| Notifications | 16 ms |

The slowest page is the cash flow over ten months (0.9 s). It classifies every cash line, so
it grows with the number of bank movements in the range. If it nears 2 s in production,
pre-aggregate it by month.

## What keeps it fast

- Every list is paginated on the server (`page`, `page_size` 25 by default, at most 200) and filtered in SQL.
- Reports aggregate in the database (`GROUP BY` on `journal_lines`), not in Python.
- Indexes on the hot paths: journal entries by date, period and source; journal lines by
  account, project/WBS/cost element and partner; invoices by status and due date (aging);
  audit log by time, entity and actor; notifications by user and read state.
  Migration `0037_performance` added the partner, status/due date and audit-time indexes.

## Whole-scenario end-to-end

`frontend/e2e/real/scenario.spec.ts` runs the full chain against the real backend, each step
done by the person who does it: PR → RFQ (three vendors) → award → PO → service GR with BAST
→ vendor invoice (three-way match) → DOR → ticket signed with a disputed line → invoice and
faktur → bank receipt (PPh 23 withheld) → payroll (calculator cannot approve) → payment run
(preparer, approver and releaser are different people) → PPN paid and filed → month close
and reopen; plus CAPEX to capitalisation and SOP release → training acknowledgement. With the
other real specs (lead → contract, budget lock, MR/PR, blocked PR → BCR, offline DOR) it
covers the whole scenario from phase 10.

```bash
E2E_REAL=1 npx playwright test e2e/real --workers=1
```

Run it with one worker: the scenario closes and reopens the current month.
