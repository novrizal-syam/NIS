# 04a · Purchase requisition with automatic budget check
Only PR. RFQ, PO, GR, stock and vendor invoices are later prompts.
1. PR (PR-26-xxx): project (Locked only), WBS, cost element (not Contingency), need date, delivery location, lines (item or free-text service, qty, UoM, estimated price), attachments. Status machine per PROCESS.md.
2. Submit → `budget_control.check`. OK → DOA `purchase_requisition` (50 jt / 500 jt / above). Blocked → status "Blocked by budget" with shortfall and a "Ajukan BCR" button that opens the BCR form prefilled (amount = shortfall rounded up to Rp 1 jt, reference to this PR).
3. Final approval re-checks; OK → `reserve()` (pre-commitment) → Approved; otherwise back to Blocked + notify requester.
4. Implement the `bcr_approved` hook: referenced PR first, then other blocked PRs on the same line by submit date; those that fit → Awaiting approval + notify; others stay Blocked. Audit "re-checked after BCR-xx".
5. Edit only in Draft/Blocked; cancel releases reserved budget; reject requires a reason → Draft.
6. PR list with status filters and danger pill for Blocked; detail with live budget info, approval history, linked BCR; appears in "Persetujuan Saya".
Tests: routing by amount; blocked with correct shortfall; BCR approval moves the PR; second PR still short stays Blocked; parallel approvals cannot overspend; requester cannot approve; cancel releases. Playwright: Rp 150 jt PR on Rp 55 jt remaining → Blocked → BCR → approve → PR to approval → approve → available reduced.
