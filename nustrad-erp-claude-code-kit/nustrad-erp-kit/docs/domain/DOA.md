# Approval matrix (DOA) and segregation of duties

All values are seed data in the `doa_rules` table and editable in Settings (change requires Director approval). Thresholds are proposals from GEK-BPM-001, pending management confirmation.

## Roles
Super Admin, Admin (IT; no business approvals), Director, Shareholders (RUPS; CAPEX only), Head of Sales & Ext. Comm., Account Executive, Tender Specialist, Billing Admin, Legal & Liaison Officer, QHSE Coordinator, Head of Operation, Lead Engineer (Planner), Engineer, OFS Superintendent, EPCOM Superintendent, Field Engineer, Operation Staff, Asset & Inventory Coordinator, Warehouse Head, Lead Controller, Head of Finance & Support, Finance Officer, AP Accountant, Cashier, Tax Specialist, Procurement Officer, HCBP Officer, Client Representative (external), Vendor (external, later).

## Rules
| doc_type | Condition | Approver chain |
|---|---|---|
| bid_decision | all (score ≥ 60% = recommend bid) | Director |
| quotation | margin ≥ 25% | Head of Sales & Ext. Comm. |
| quotation | margin < 25% | Director |
| tender_package | technical / commercial in parallel | Head of Operation ‖ Director |
| project_budget | step 1 all (reject if margin < 20%) | Lead Controller |
| project_budget | step 2 total cost ≤ Rp 2.000.000.000 | Head of Operation |
| project_budget | step 2 total cost > Rp 2.000.000.000 | Director |
| bcr | contingency release, transfer, or increase ≤ 10% of total budget | Head of Operation |
| bcr | increase > 10% or revenue change | Director |
| purchase_requisition | ≤ Rp 50.000.000 | Head of Operation |
| purchase_requisition | ≤ Rp 500.000.000 | Head of Finance & Support |
| purchase_requisition | > Rp 500.000.000 | Director |
| rfq_award | non-best-score vendor | Head of Finance & Support (written reason) |
| dor | all | OFS / EPCOM Superintendent of the project |
| cash_advance | all | Head of Operation |
| manual_journal | all | Lead Controller |
| payroll | all | Head of Finance & Support |
| payment_run | ≤ Rp 1.000.000.000 | Head of Finance & Support (then released by Cashier) |
| payment_run | > Rp 1.000.000.000 | Director (then released by Cashier) |
| capex | all | Director |
| capex | amount > Rp 5.000.000.000 | Director → Shareholders (RUPS) |
| outgoing_letter | all | Director |
| sop_release | all | Director |
| doa_change | all | Director |

Engine features: sequential and parallel steps, delegation with date range, escalation after N hours, reject returns to Draft with mandatory comment, "My Approvals" inbox, bulk approve for same doc_type.

## Segregation of duties (backend-enforced)
- Requester ≠ approver on the same document (all doc_types).
- Payment run: preparer (AP Accountant) ≠ approver ≠ releaser (Cashier).
- Vendor bank-account editor ≠ payment approver/releaser.
- Manual journal creator ≠ approver. Payroll calculator ≠ approver. DOR submitter ≠ DOR approver.
- Assigning roles that create one of these conflicts to one user requires a reason + Director approval and is listed in the SoD exception register (reviewed monthly by Lead Controller).
- Admin role has no business approve/post permissions by default.
