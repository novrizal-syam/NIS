# Nustrad ERP · Claude Code starter kit

A kit for building the GEK ERP (designed in GEK-ERP-001 and prototyped in GEK ERP Live Prototype v2) as a real application with Claude Code, branded with the Nustrad logo and theme.

## What is in the kit
| Path | Purpose |
|---|---|
| `CLAUDE.md` | Project memory Claude Code loads in every session: context, stack, rules, workflow. Kept short on purpose. |
| `docs/domain/PROCESS.md` · `DOA.md` · `ACCOUNTING.md` | Business rules Claude Code reads only when a phase needs them. |
| `docs/brand/BRAND.md` + `logos/` | Nustrad theme tokens, type, app shell rules and logo files. |
| `prompts/00…10` | 25 phase prompts, each one small enough for one session. |
| `.claude/commands/` | Slash commands: `/phase`, `/fixbug`, `/feature`, `/review`. |

## Run the app (after phase 00)
```bash
cp .env.example .env
make up          # docker compose up -d --build: api, web, db, minio, mailpit
make migrate     # alembic upgrade head
```
- First run: set `SETUP_TOKEN` in `.env` (a random value), open http://localhost:5173/setup and follow the wizard: Super Admin (strong password) → mandatory 2FA + 10 recovery codes shown once → company profile → departments → demo data or empty → finish. After that `/setup` is closed for good. Databases that already had users are treated as set up.
- Administration (Settings): Pengguna & Peran (invite, temporary password, import, deactivate, reset, unlock, sessions), Peran & Izin (permission matrix, custom roles, temporary roles, "View as role"), Pemisahan Tugas (SoD rules and exception register, Director approval), Tinjauan Akses (quarterly review, Excel/PDF). First login asks for password change, privacy notice (UU 27/2022), 2FA when the role requires it, and profile.
- Email: `EMAIL_PROVIDER=smtp` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS`; port 465 uses implicit TLS) or `EMAIL_PROVIDER=resend` (`RESEND_API_KEY`), plus `EMAIL_FROM`, `EMAIL_FROM_NAME` and `APP_BASE_URL` for links. In dev everything lands in Mailpit. Invitations (`/activate?token=…`, 72 h) and password reset (`/reset-password?token=…`, 60 min, 3 requests per email per hour) are single use and stored hashed; every send is logged in `email_log` without the token. When email is not configured nothing fails: the admin sees the activation link to copy. Super Admin can send a test email from Settings.
- Sales (Lead ke Kontrak): Lead (`LD-26-001`, New → Contacted → Qualified when ≥ 3 of 5 criteria, or Disqualified with reason) → "Jadikan Opportunity" (`OPP-26-001`) → kanban/table Qualified → Quotation → Submitted → Won/Lost. Qualified → Quotation only through a bid/no-bid decision (6 scores, ≥ 60 % recommends bid) approved by the Director in the DOA inbox; a rejected bid or approved no-bid ends as Lost with the reason. Dashboard tiles: open and weighted pipeline, win rate vs 45 %, new contract value YTD vs Rp 80 M. The 60 % / 45 % / Rp 80 M figures are rows in `system_settings` (`crm.*`).
- Quotations (`QT-26-001 Rev.0`): created from an opportunity at the Quotation stage; lines from the price database (qty, unit cost and unit price editable), discount %. Totals and margin are computed by the backend (lines rounded to whole rupiah, margin = (total − cost) / total). Submit goes through the DOA engine: margin ≥ 25 % → Head of Sales, < 25 % → Director; margin below 20 % (`quotation.margin_warning_pct`) shows a red warning. Approved, rejected or sent quotations change only through a new revision; older revisions stay read-only as history. "Kirim ke klien" issues letter `001/GEK-SLS/{roman month}/{year}` (table `outgoing_letters`), renders the PDF on the GEK letterhead (company profile logo, never cost/margin), stores it in the DMS, optionally emails it to the client contact with the PDF attached, and moves the opportunity to Submitted with its value set to the quoted total.
- Won (`Tandai Menang`, only from Submitted with the latest quotation revision sent): ONE database transaction creates the contract `CTR-26-001` (rate schedule = quotation lines after discount; equipment breakdown 0, standby filled manually; consumables cost + markup; mob/demob lump sum), a Draft project `PRJ-26-001` (revenue = contract value; budget per cost element = quoted cost; Contingency = `project.contingency_pct`, default 5 % of cost) and links the sent quotation PDF into the project documents. Any failure rolls everything back. "Tandai Kalah" records the reason and the winner price. Contracts (Kontrak: PO/SPK, period, payment term, usage %, rate schedule) and projects (Proyek: budget read-only until phase 03) have their own lists with Excel export.
- Tenders (Tender, for opportunities marked as a tender): tender number and method, aanwijzing, clarification deadline, closing (date + time, WIB), opening, bid validity, bid bond, TKDN, bid price; document checklist Admin/Technical/Commercial (files are DMS attachments; status Present only when a file is attached and still valid at closing, otherwise Missing; N/A when not requested); clarification Q&A log; package approval `tender_package` in parallel (technical → Head of Operation ‖ commercial → Director), allowed only with 0 missing mandatory documents and a price; submission record (time, channel, receipt, proof); result (won/lost/disqualified/cancelled, rank, winner, winning price, lessons learned — required when lost/disqualified). A lost/disqualified/cancelled result closes the opportunity as Lost; won continues with "Tandai Menang". The dashboard lists tenders closing within 7 days.
- Project budget (03a): the Head of Operation assigns the planner (Lead Engineer); the planner edits the Draft budget as cost element × WBS (default EXEC "Execution"; add MOB/DEMOB/per well), whole rupiah; totals, revenue and planned margin are computed by the backend. Submit → Controller review (Lead Controller; the backend refuses approval when the planned margin is below `project.min_margin_pct`, default 20 %; reject needs a note and returns to Draft) → Awaiting approval (total cost ≤ Rp 2.000.000.000 Head of Operation, above that Director) → Locked with an immutable baseline v0 in `budget_versions` (a database trigger rejects UPDATE/DELETE). After lock every budget field is read-only in the backend; changes come through BCR (03c). Contingency is flagged `locked_reserve`.
- Budget control (03b, `services/budget_control.py`, used by phases 04–07): `available()`, `check()`, `reserve()` (PR pre-commitment), `commit()` (PO, consumes the PR's pre-commitment), `actualize()` (GR/DOR/issues, consumes the PO's commitment), `release()` (cancel/savings). Every write goes to the append-only `budget_ledger` (trigger rejects UPDATE/DELETE) under a row lock on the budget line, so parallel requests cannot overspend. Blocked when the project is not Locked, the cost element is Contingency, or the amount exceeds available (the error carries the shortfall). Planner and Lead Controllers are notified once per line at 80 %. The project page shows budget / pre-commit / commit / actual / available per line. Admin-only `POST /api/budget/test-check` (404 when `APP_ENV=production`).
- BCR (03c, project tab "BCR"): on a Locked project the planner requests a change for a WBS × cost element: contingency release (≤ remaining contingency), transfer (≤ available on the source line) or budget increase (optional revenue change for a client VO), with reason, justification, attachments and an optional blocked-document reference. DOA `bcr`: contingency/transfer/increase ≤ 10 % of total budget → Head of Operation; larger increase or revenue change → Director. The source is re-checked under row locks when approved. Approval creates budget version v1, v2 … with a change note (baseline v0 untouched; current = latest) and emits `bcr_approved` (`app.project.bcr_service.on_bcr_approved`, used in 04a). Tab "Versi anggaran" compares baseline v0 with the current budget.
- Purchase requisition (04a, Pengadaan › Purchase Requisition): PR on a Locked project, WBS and cost element (not Contingency) with need date, delivery location, lines (item or free text, qty, UoM, estimated price) and attachments. Submit runs `budget_control.check`: OK → DOA `purchase_requisition` (≤ Rp 50 jt Head of Operation, ≤ Rp 500 jt Head of Finance & Support, above Director); short → "Terblokir anggaran" with the shortfall and "Ajukan BCR" (prefilled: shortfall rounded up to Rp 1 jt, reference to the PR; users without budget rights see who to ask). Final approval re-checks and `reserve()`s the pre-commitment, or goes back to Blocked and notifies the requester. `bcr_approved` re-checks blocked PRs on that line (referenced PR first, then by submit date) and sends those that fit to approval. Edit only in Draft/Blocked; reject needs a reason → Draft; cancel releases the reservation. Project-scoped users now see the projects they are assigned to as planner.
- RFQ and PO (04b, Pengadaan › RFQ / Purchase Order): from an Approved PR, an RFQ goes to ≥ 3 vendors of one category (CSMS pending, blacklisted or inactive vendors cannot be selected); quotes record unit prices, delivery days, terms, validity and attachments. Score = price 60 % (lowest/price) + delivery 20 % (fastest/days) + rating 20 % (rating/5), weights in `rfq.weights`. The best score is awarded directly; another vendor needs a written reason and DOA `rfq_award` (Head of Finance & Support). Every quote is kept in the price history per item/vendor. The PO (PPN `tax.ppn_effective_pct`, default 11 % = 12 % × 11/12; standard late-delivery penalty clause; PDF on the GEK letterhead in the PO documents) is issued from the award: the PR's pre-commitment is released and the PO subtotal (DPP) committed, so savings return to available; the PR becomes "Sudah dipesan". Revisions with the same or lower value apply at once (difference released); a higher value needs re-approval (DOA `po_revision`, same thresholds as the PR, on the new value) and is checked against the budget.
- Goods receipt, inventory and material request (04c, Pengadaan › Penerimaan Barang / Persediaan / Permintaan Material):
  - Ledger (`services/ledger.py`, tables `journal_entries`/`journal_lines`, numbers `JV-26-0001`): `post_journal()` is the only way to post; it refuses unbalanced entries, unknown/inactive/non-posting accounts, Contingency and dates in a closed fiscal period, and stores dimensions (project, WBS, cost element, cost center, asset, partner). Posted journals are append-only (database trigger); corrections go through `reverse()`.
  - GR from an issued PO ("Terima barang/jasa"): goods (PO has item lines) by the Warehouse Head, services by the project manager; partial or full, never more than is open; posting needs a photo/delivery note or BAST attachment. Direct to project: commitment → actual and Dr expense of the cost element / Cr 2120. Stock items received into a warehouse: Dr 1310 / Cr 2120 at moving-average cost and the PO commitment is released (the project is charged when the material is issued, so it is never counted twice). Fully received → PO "Selesai" and any leftover commitment released. A PO revision cannot go below received quantities.
  - Stock per item per warehouse (moving average; value is authoritative, so the last unit takes the remaining value), append-only stock moves, transfers between warehouses (`TRF`), stock opname (`SOP`; variance needs DOA `stock_opname` → Lead Controller, then Dr/Cr 1310 against `inventory.variance_account`, default 6100), reorder suggestions (≤ reorder point → refill to 2×, last price) and a valuation that reconciles to account 1310.
  - MR by a Field Engineer on a project team (new project tab "Tim proyek"; members get the project in their project-scoped rights): site stock first, then Base; the issued part is charged at once (budget actual + Dr 5300 / Cr 1310); the shortfall becomes a PR at each item's last price, created and submitted in the engineer's name (04a rules: blocked or DOA).
- Vendor invoice and 3-way match (04d, Pengadaan › Tagihan Vendor): the AP Accountant records the vendor invoice against a PO with posted receipts (vendor invoice no. — unique per vendor, tax invoice no., date, type goods or service/rental, term defaulting to the vendor's new `payment_term_days`, DPP, lines prefilled with received-not-billed quantities at the PO price) and attaches the invoice/faktur scan. PPN = 12 % × 11/12 of DPP (`tax.ppn_effective_pct`) unless entered as on the faktur; PPh 23 `tax.pph23_pct` (2 %) on services/rentals, doubled without NPWP, none on goods. "Cocokkan 3 arah" checks per line billed qty ≤ received − already billed and price = PO price, and DPP = line total, within `ap.match_tolerance_pct` (default 0): match → "Disetujui untuk dibayar", due = date + term, journal Dr 2120 (GR value; any in-tolerance price difference to the cost element's expense), Dr 1420 / Cr 2110 (DPP + PPN − PPh 23), Cr 2230; no match → "Selisih pencocokan" with the reasons, nothing posted, the PO creator notified, not payable. Resolve by a correction (typing error) or a vendor credit note (reduces DPP/PPN, corrected lines), then match again. `ap_service.ensure_payable()` / `GET /api/finance/payables` are the gate for payment runs (07b): only approved invoices with an open balance. Tabs "Umur hutang" (not due, 1–30, 31–60, 61–90, > 90 days; Excel) and "Kartu hutang vendor" (account 2110 per vendor from the ledger, opening and running balance).
- Daily Operational Report (05a, Eksekusi › Daily Operation Report; installable PWA, works offline): on Locked projects the team's field engineer reports per day: equipment per unit (operating + standby + breakdown + rig-up/down must be 24 h), crew, consumables from the site warehouse (≤ stock), activities and NPT, technical data from a template per service type (`dor.templates`: well test, pumping, nitrogen, EPF; set the template and the service line OFS/EPCOM in the project tab "Tim proyek"), HSE counts and photos (DMS). Units and people with an expired mandatory certificate cannot be selected (reason shown); warning within 60 days (certificates now carry a `mandatory` flag, default on). Live pricing on the device from the contract rate schedule (equipment hours/24 × operating/standby/breakdown rate, rig-up/down at the operating rate, breakdown 0 unless agreed; personnel per person-day; consumables cost × (1 + markup)) and internal cost (asset day rate, price-item cost, moving-average stock cost); the server recalculates. Drafts are kept in IndexedDB and pushed to `POST /api/operations/dors/sync` (idempotent by device `client_id`; `base_version` detects edits from another device → "Konflik versi": load the server version or overwrite) on save, on reconnect, every minute and by service-worker background sync (`public/sw.js` also caches the app shell). Submit → DOA `dor` (OFS or EPCOM Superintendent who is on the project team; the submitter can never approve); "Terlambat" when submitted or approved after 08:00 WIB the next day; reject returns it for correction. Approval, in the approval transaction: budget actuals per cost element (EQUIP-OWN, MANPOWER, CONSUMABLE), site stock issue at moving-average cost, journals Dr 1220 / Cr 4100 (revenue accrual) and Dr 5300 / Cr 1310, asset operating hours (`asset_usage`), HSE man-hours (`hse_daily`), payroll day records (`payroll_days`, one per person per day), contract usage with a one-time alert to Head of Sales at ≥ 80 %.
- End-to-end happy path against the real backend (lead → bid → quotation 34 % → Head of Sales → send → won → contract + project): start an S3 endpoint on :9000 (MinIO or `moto_server -p 9000`), run `frontend/e2e/real/reset-db.sh`, start the API on :8000 with `DATABASE_URL=…/nustrad_e2e S3_ENDPOINT_URL=http://localhost:9000 uvicorn app.main:app --port 8000`, then `cd frontend && E2E_REAL=1 npx playwright test e2e/real` (lead-to-contract happy path; budget flow: 18 % rejected / 25 % approved → Locked → over-budget check blocked → BCR → v1 → check passes; PR flow: Rp 150 jt PR on Rp 55 jt → Blocked → BCR → approved → PR approved → available reduced; MR flow: field engineer asks 8 drums → 2 from site, 3 from Base, 3 become a PR; valuation equals 1310; DOR flow: the field engineer fills a DOR offline, it syncs when the connection returns, is submitted and approved by the OFS Superintendent). Reset the database before each run. Without `E2E_REAL` the spec is skipped.
- Lost authenticator: sign in with a recovery code (2FA must then be enrolled again), or the audited CLI `docker compose exec api python -m app.auth.cli reset-2fa --email ...`. Also `... app.auth.cli unlock --email ...`.
- App: http://localhost:5173 · component catalogue (dev only): http://localhost:5173/dev/komponen
- API: http://localhost:8000/api/health · docs: http://localhost:8000/api/docs
- Mailpit: http://localhost:8025 · MinIO console: http://localhost:9001
- Checks: `make test`, `make lint`, `make e2e` (Playwright: contrast in light/dark, 400 px width, focus ring)

## Demo data
`make demo` loads demo data (every row has `is_demo = true`): one user per role, 10 departments, 5 clients, 15 vendors (3 per category, 1 CSMS pending), 8 field + 6 office employees, 10 items, 2 warehouses, 6 assets, periods Jan–Dec 2026 (Jan–Sep closed, Oct open), 8 priced services, USD rate, 8 leads and 5 opportunities across all stages. Some certificates are expired or close to expiry so alerts can be tried. Company and person names are fictional.

Remove it with `make demo-remove` or Settings › Pengaturan › "Hapus semua data demo" (Super Admin only). Configuration (chart of accounts, cost elements, roles, DOA rules) is not demo data and stays.

Password for every demo user: `Demo-GEK-2026` (override with `DEMO_PASSWORD` before `make demo`). Roles marked 2FA must enrol an authenticator app at first sign-in.

| Role | Email | Name | 2FA |
|---|---|---|---|
| Super Admin | `super.admin@demo.gek.co.id` | Andi Pratama | ya |
| Admin | `admin@demo.gek.co.id` | Yoga Saputra | ya |
| Director | `director@demo.gek.co.id` | Hendra Wijaksono | ya |
| Shareholders (RUPS) | `shareholders@demo.gek.co.id` | Ratna Kusumawardani |  |
| Head of Sales & Ext. Comm. | `head.of.sales@demo.gek.co.id` | Bayu Nugroho |  |
| Account Executive | `account.executive@demo.gek.co.id` | Citra Lestari |  |
| Tender Specialist | `tender.specialist@demo.gek.co.id` | Fajar Ramadhan |  |
| Billing Admin | `billing.admin@demo.gek.co.id` | Indah Permatasari |  |
| Legal & Liaison Officer | `legal.liaison@demo.gek.co.id` | Dimas Hutapea |  |
| QHSE Coordinator | `qhse.coordinator@demo.gek.co.id` | Wulan Sari |  |
| Head of Operation | `head.of.operation@demo.gek.co.id` | Rina Wijaya |  |
| Lead Engineer (Planner) | `lead.engineer@demo.gek.co.id` | Teguh Santoso |  |
| Engineer | `engineer@demo.gek.co.id` | Budi Hartono |  |
| OFS Superintendent | `ofs.superintendent@demo.gek.co.id` | Rudi Simanjuntak |  |
| EPCOM Superintendent | `epcom.superintendent@demo.gek.co.id` | Agung Prasetyo |  |
| Field Engineer | `field.engineer@demo.gek.co.id` | Eko Firmansyah |  |
| Operation Staff | `operation.staff@demo.gek.co.id` | Joko Susilo |  |
| Asset & Inventory Coordinator | `asset.inventory.coordinator@demo.gek.co.id` | Sinta Maharani |  |
| Warehouse Head | `warehouse.head@demo.gek.co.id` | Hadi Kurniawan |  |
| Lead Controller | `lead.controller@demo.gek.co.id` | Maya Anggraini | ya |
| Head of Finance & Support | `head.of.finance@demo.gek.co.id` | Siti Rahmawati | ya |
| Finance Officer | `finance.officer@demo.gek.co.id` | Putri Handayani |  |
| AP Accountant | `ap.accountant@demo.gek.co.id` | Lina Marlina | ya |
| Cashier | `cashier@demo.gek.co.id` | Sari Puspitasari | ya |
| Tax Specialist | `tax.specialist@demo.gek.co.id` | Arif Hidayat |  |
| Procurement Officer | `procurement.officer@demo.gek.co.id` | Dewi Anggraeni |  |
| HCBP Officer | `hcbp.officer@demo.gek.co.id` | Nadia Putri | ya |
| Client Representative | `client.rep@demo.gek.co.id` | Thomas Siregar |  |
| Vendor | `vendor@demo.gek.co.id` | Ahmad Fauzi |  |

## How to use
1. Create an empty Git repository, copy the kit into its root, commit.
2. Open a terminal in the repo and run `claude`.
3. Run the phases in order, one per session:
   ```
   /phase 00-bootstrap
   ```
   Claude Code reads the prompt, inspects the code, shows a plan, builds, tests and reports.
4. Check the result yourself (open the app, try the flow in the prompt), then commit: `git commit -am "phase 00-bootstrap"`.
5. Run `/clear` before the next phase so old context does not cost tokens, then `/phase 01-foundation`, and so on.
6. Before each commit you can run `/review` for a rule check.
7. For bugs: `/fixbug Purchasing › PR detail: approve button shown to the requester; requester must not approve`.

Order: 00 → 01 → 01a → 01b → 02a → 02b → 02c → (02d) → 03a → 03b → 03c → 04a → 04b → 04c → 04d → 05a → 05b → 06 → 07a → 07b → 07c → 07d → 08 → 09 → 10.

## Ways to save tokens and time
- One phase per session, then `/clear`. CLAUDE.md is reloaded automatically; domain docs are read only when needed.
- Ask for a plan first (the `/phase` command does this). Correct the plan before code is written.
- Keep prompts scoped. Put extra ideas in a "follow-up" list instead of the current phase.
- Use `/fixbug` with exact steps rather than "fix everything".
- Let tests prove the business rules; run Playwright only where a prompt asks for it.

## Notes
- Stack: FastAPI + PostgreSQL + React (chosen over MongoDB because the ERP needs strict transactions for money). If you continue from an Emergent export that uses MongoDB, tell Claude Code in phase 00 to keep MongoDB with multi-document transactions, and keep everything else.
- The Nustrad logo appears in the app shell, login and emails. GEK's own logo is used on documents GEK sends to its clients and vendors (quotations, POs, invoices, letters). Change this in `docs/brand/BRAND.md` if Nustrad wants a different split.
- Approval limits, tax rates, BPJS and TER tables are seed data, editable in Settings. Confirm them with management and GEK's tax consultant before go-live.
- Real integrations (Coretax via PJAP, bank host-to-host, PSrE e-signature, e-Meterai, WhatsApp Business) need separate contracts; the prompts build adapters with a manual/file mode first.
- Have an independent developer review the finance and payroll phases before production.
