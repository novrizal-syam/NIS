# 07b · Treasury, payment run, cash advances
1. Bank accounts, balances from GL, bank reconciliation (CSV/MT940 import, auto-match, unmatched list).
2. Payment run: AP Accountant selects due items (approved vendor invoices, net salaries, BPJS, tax) → DOA `payment_run` → Cashier releases (balance check, bank bulk-transfer CSV; host-to-host adapter interface for Mandiri/BRI/BNI/BCA later) → journals; PPh 23 bukti potong PDF per vendor. Three-person SoD enforced.
3. 13-week cash forecast: AR by due date (net of PPh 23) + WIP to be invoiced; AP due, payroll on the 25th, BPJS, tax on the 15th and month end, loan instalments, CAPEX milestones.
4. Cash advances: request → Head of Operation → Cashier disburses (journal) → settlement with receipt photos per cost element (project actuals) → refund or reimbursement; alert after 14 days.
Tests: SoD (preparer = approver rejected; approver = releaser rejected), insufficient balance, settlement journal and budget actuals.
