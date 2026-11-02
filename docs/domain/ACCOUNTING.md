# Accounting, cost elements, posting rules, tax

## Chart of accounts (seed; extendable)
1110 Bank Mandiri IDR · 1111 Bank USD · 1120 Cash advances & petty cash · 1210 Accounts receivable · 1220 Unbilled revenue (WIP) · 1310 Inventory · 1410 Prepaid PPh 23 · 1420 PPN input · 1510 Fixed assets · 1520 Asset under construction (AUC) · 1590 Accumulated depreciation · 2110 Accounts payable · 2120 GR/IR clearing · 2210 PPN output · 2220 PPh 21 payable · 2230 PPh 23 payable · 2240 BPJS payable · 2310 Salaries payable · 2410 Bank loan · 3100 Share capital · 3200 Retained earnings · 4100 Service revenue · 5100 Direct manpower · 5200 Equipment & maintenance · 5300 Consumables & chemicals · 5400 Equipment rental · 5500 Subcontract · 5600 Logistics & transport · 5700 QHSE · 6100 General & administrative · 6200 Depreciation · 7100 FX gain/loss

## Cost elements → expense account
Manpower→5100 · Owned equipment (internal rate)→5200 · Rented equipment→5400 · Consumables & chemicals→5300 · Subcontract→5500 · Logistics & transport→5600 · QHSE→5700 · Contingency (locked reserve, never posted directly).

Every journal line carries dimensions: project_id, wbs_id, cost_element, cost_center, asset_id, partner_id (client/vendor/employee) where relevant.

## Posting rules (event → journal)
| Event | Debit | Credit |
|---|---|---|
| DOR approved (revenue) | 1220 | 4100 |
| DOR approved (consumables issued at site) | 5300 | 1310 |
| Ticket signed with disputed lines | 4100 | 1220 |
| Customer invoice created | 1210 (total) | 1220 (subtotal), 2210 (PPN) |
| Customer receipt | 1110 (net), 1410 (PPh 23 withheld) | 1210 |
| Material issue (MR) | 5300 | 1310 |
| Goods/service receipt, direct to project | expense by cost element | 2120 |
| Goods receipt, stock item | 1310 | 2120 |
| Vendor invoice matched | 2120 (DPP), 1420 (PPN) | 2110 (DPP + PPN − PPh 23), 2230 (PPh 23) |
| Payroll approved | 5100 (field, per project) / 6100 (office) incl. employer BPJS | 2310 (net), 2220 (PPh 21), 2240 (BPJS employee + employer) |
| Payment run released | 2110 / 2310 / 2240 / 22xx | 1110 |
| Cash advance disbursed | 1120 | 1110 |
| Cash advance settled | expense by cost element, 1110 (refund) | 1120 |
| Tax paid (PPh) | 2220 / 2230 | 1110 |
| PPN settled | 2210 | 1420, 1110 (difference) |
| CAPEX milestone paid | 1520 | 1110 or 2110 |
| Asset capitalised | 1510 | 1520 |
| Monthly depreciation | 6200 (or 5200 for project equipment) | 1590 |

Internal rates (manpower, owned equipment) are charged to the project budget for management reporting only; in the ledger those costs arrive through payroll and depreciation.

## Tax configuration (seed; confirm with GEK's tax consultant)
- PPN 12% × DPP nilai lain 11/12 of the selling price (effective 11%).
- PPh 23: 2% on services and rentals (withheld by clients on GEK invoices; withheld by GEK on vendor service/rental invoices).
- PPh 21: TER method (PP 58/2023), TER tables A/B/C stored as data; December annual reconciliation; 1721-A1.
- BPJS Kesehatan & Ketenagakerjaan (JHT, JP, JKK, JKM) employee/employer rates and wage caps as data.
- Bea meterai Rp 10.000 on documents above Rp 5.000.000 (e-Meterai adapter).
- Deadlines (PMK 81/2024, configurable): PPh 21/23 pay by the 15th, file by the 20th; PPN pay and file by end of the following month.
- Overtime: 1/173 × monthly basic × factor (PP 35/2021). Field allowance default Rp 350.000/day on site.

## Period close checklist
Blocking: all DORs of the period approved; trial balance balanced. Warning (allowed with a note): unsigned tickets, open GR/IR (accrue received-not-invoiced), unpaid payroll, unfiled tax, unsettled cash advances, unreconciled bank lines, depreciation not run. Close by Lead Controller; reopen only by Head of Finance & Support with a reason.

## Retention
Financial and tax records 10 years (UU 8/1997, UU KUP Art. 28). No hard delete of posted documents.
