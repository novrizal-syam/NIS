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
