# Business process and status machines

Spine: Client → Contract (rate schedule) → Project → WBS → Budget (locked, versioned) → Cost element. Every cost or revenue transaction carries project, WBS and cost element.

## Lead to contract
- Lead: New → Contacted → Qualified | Disqualified (reason). Qualify needs ≥ 3 of 5: client budget/AFE, technical fit, start ≤ 6 months, decision maker known, CSMS possible.
- Opportunity: Qualified → Quotation → Submitted → Won | Lost. Bid/no-bid: 6 scores 1–5 (strategic fit with RJPP, technical capability, asset & crew availability, CSMS & compliance, margin, commercial & legal risk); % = average/5; ≥ 60% recommends bid; Director decides.
- Tender (when the opportunity is a tender): dates (aanwijzing, clarification deadline, closing with time, opening, bid validity), bid bond, TKDN, document checklist Admin/Technical/Commercial (expired document = missing), clarification log, parallel approval (technical → Head of Operation, commercial → Director) only when 0 mandatory documents missing and price filled; submission record; result with lessons learned.
- Quotation: lines from the price database (code, description, unit, qty, unit cost, unit price, cost element), discount %, revisions Rev.0/Rev.1; margin = (price − cost)/price; approval per DOA; "Send to client" creates a numbered outgoing letter + PDF in DMS.
- Won → in ONE transaction: Contract (rate schedule = quotation lines after discount; manual rates allowed: equipment operating/standby/breakdown = 0, personnel per day, consumables cost + markup %, mob/demob lump sum) + Project Draft (revenue = contract value; budget per cost element = quotation cost; Contingency = 5% of cost) + DMS project folder.

## Project & budget
- Project: Draft → Controller review → Awaiting approval → Locked → Closed.
- Locked creates baseline v0 (immutable). Budget changes only through BCR → version v1, v2… Baseline kept.
- Available = current budget − pre-commitment (approved PR) − commitment (PO) − actual (GR, DOR, stock issue, cash-advance settlement, payroll allocation). Warning at 80%. Hard stop above available.
- BCR: source = Contingency release | Budget increase | Transfer; reason = Client variation order | Scope change | Price escalation | Estimate error. Approval triggers `bcr_approved` → re-check PRs in "Blocked by budget" for that line.

## Procure to pay
- MR: stock check site → base; issue what exists (actual + journal); shortfall becomes a PR at last price.
- PR: Draft → Submitted → Blocked by budget | Awaiting approval → Approved | Rejected | Cancelled. Re-check budget at final approval; reserve pre-commitment. Cancel releases.
- RFQ: ≥ 3 qualified vendors (CSMS pending/Blacklisted excluded); score price 60% + delivery 20% + rating 20%; non-best award needs reason.
- PO: pre-commitment → commitment; savings return to available. PO revision with higher value needs re-approval.
- GR: commitment → actual; Dr expense (or inventory) / Cr GR/IR.
- Vendor invoice: 3-way match PO = GR = invoice (tolerance configurable, default 0) → Approved for payment | Match exception (resolved by credit note).

## Execution
- DOR (PWA, offline): equipment hours per unit (operating + standby + breakdown + rig-up/down = 24), crew (mobilisation gate blocks expired mandatory certificates; warn ≤ 60 days), consumables from site stock (≤ stock), activities, NPT, service-specific technical data, HSE stats, geotagged photos. Live pricing from the rate schedule. Draft → Submitted → Approved | Returned. Approval by the project's Superintendent before 08:00 next day. Approval posts revenue accrual, project cost, stock issue, asset hours, man-hours, payroll days; alert Sales when contract usage ≥ 80%.
- Maintenance (GEK-MNT-001): 27 equipment types, criticality A/B/C, certificates & calibration with 90/60/30-day alerts (expired = cannot be allocated), PM task library by frequency (calendar and operating hours from DOR), work orders with checklists (FRM-MNT), corrective WO from DOR breakdowns, downtime, KPIs (utilisation ≥ 85%, downtime < 3%).
- QHSE: HIRADC/JSA per project (required before mobilisation), permits, inspections, incidents, CAPA, statistics, CSMS evidence pack.

## Order to cash
- Service ticket from approved DOR(s): Awaiting client signature → Signed | (disputed lines removed + revenue reversed) → Invoiced. Client signs on tablet or by secure link (PSrE adapter later).
- Invoice only from signed tickets: Draft → Faktur issued → Sent → Paid. Reminders D-7, D+1, D+7; escalate D+14. Coretax XML export; PJAP adapter later.
- Receipt: bank import (CSV/MT940) auto-match; PPh 23 withheld = prepaid tax; days-to-cash KPI (target < 30).

## Finance
- Payment run: AP Accountant selects due items (approved vendor invoices, net salaries, BPJS, tax) → DOA → Cashier releases (balance check, bank file, bukti potong PPh 23).
- Cash advance: Requested → Approved → Disbursed → Settled (receipts by cost element; refund or reimbursement); alert after 14 days unsettled.
- Payroll: Not started → Calculated → Submitted → Approved → Paid (via payment run). Days on site and overtime from approved DORs.
- Tax per type: Open → Billing code created → Paid (NTPN) → Filed (BPE).
- Month-end close: see ACCOUNTING.md.

## CAPEX
Draft → Submitted → (Awaiting RUPS) → Approved (locked in CAPEX plan) → In execution (AUC) → Capitalised → Post-investment review at 6 and 12 months. Business case: NPV @ 12% (configurable), IRR, payback, buy vs rent vs lease.

## Documents & learning
- Incoming letter: Registered → Routed (disposisi: PIC, instruction, deadline) → Closed (reply letter linked).
- Outgoing letter: Draft → Awaiting approval → Approved → Sent (e-sign + e-Meterai when needed).
- SOP: revision submitted → Director approval → new revision effective, old archived as Uncontrolled → LMS read-and-acknowledge training auto-assigned to affected roles.
- Certificates: alerts 90/60/30 days; expired blocks crew allocation and DOR selection until renewal is recorded.
