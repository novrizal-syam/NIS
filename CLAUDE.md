# Nustrad ERP — project memory for Claude Code

Production ERP built by Nustrad (PT Nusantara Strategic Advisory) for its first client, PT Global Energi KITA (GEK), an Indonesian oil & gas services company (well clean-up and well testing, 12K separator, pumping, nitrogen, EPF, EPC). Revenue about Rp 25 M in 2026, target Rp 85 M in 2030, 20–40 users. Clients are KKKS (SKK Migas contractors).

This is a real system. Financial numbers must be correct and auditable. No data may be lost.

## Read on demand (do not load all at once)
- `docs/domain/PROCESS.md` — end-to-end flows and status machines per module
- `docs/domain/DOA.md` — approval matrix and segregation-of-duties rules
- `docs/domain/ACCOUNTING.md` — chart of accounts, cost elements, posting rules, tax config
- `docs/brand/BRAND.md` — Nustrad theme, tokens, logo usage, UI rules
- `prompts/` — the phase prompts; only the current phase matters

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, PostgreSQL 16. Money is `NUMERIC(18,0)` IDR (integer rupiah) or `NUMERIC(18,2)` for USD. Never float.
- Frontend: React 18 + Vite + TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, React Hook Form + Zod, react-i18next (Bahasa Indonesia default, English second).
- Mobile: the DOR and approval screens are a PWA; DOR works offline (IndexedDB) and syncs.
- Files: S3-compatible object storage (MinIO in dev).
- Tests: pytest (backend), Vitest (frontend units), Playwright (end-to-end).
- Runtime: Docker Compose for dev (`api`, `web`, `db`, `minio`, `mailpit`).

## Layout
```
backend/app/{core,auth,master,workflow,crm,contract,project,procurement,inventory,operations,billing,finance,payroll,tax,capex,asset,maintenance,qhse,lms,dms,reporting}
backend/app/services/{numbering,budget_control,ledger,email,audit,storage}.py
backend/tests/
frontend/src/{app,components,features/<module>,lib,i18n,theme}
docs/  prompts/  .claude/commands/
```

## Commands
- `docker compose up -d` · `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q` · `cd frontend && npm run test && npm run lint && npm run typecheck`
- `npx playwright test` (end-to-end, only when the phase prompt asks)

## Non-negotiable rules
1. RBAC on every endpoint (role + permission + data scope). Users can hold several roles.
2. Segregation of duties enforced in the backend: a requester never approves their own document; payment run preparer, approver and releaser are three different people.
3. One DOA engine (`workflow`) for every approval. Thresholds live in the database, never hard-coded.
4. Audit log for every create/update/delete/approve/reject (who, when, before, after). Posted documents are never edited or deleted, only reversed.
5. Atomic document numbering: `LD-26-001`, `OPP`, `QT`, `CTR`, `PRJ`, `BCR`, `MR`, `PR`, `PO`, `GR`, `VI`, `DOR`, `TK`, `INV`, `PAY`, `CA`, `CPX`, `WO`, `JV-26-0001`; outgoing letters `001/GEK-{DEPT}/{roman month}/{year}`.
6. Explicit status machines; illegal transitions rejected by the backend.
7. Every financial event posts a balanced double-entry journal through `services/ledger.post_journal()` in the same DB transaction as its source document. Closed periods reject postings.
8. Budget consumption only through `services/budget_control.py` (append-only ledger; row-level locking so parallel requests cannot overspend).
9. Demo data has `is_demo = true`; Settings has "Remove all demo data" (Super Admin only).
10. Validation in Pydantic and Zod; error messages in Bahasa Indonesia, plain and specific.
11. Sensitive fields (salary, NIK, bank account, personal tax ID) need an explicit permission and are stripped from API responses and exports otherwise (UU 27/2022 PDP).
12. Timezone Asia/Jakarta; number format id-ID (`Rp 1.250.000`); dates `7 Okt 2026`.

## How to work in this repo (keeps cost and risk low)
- Work on ONE phase prompt at a time. Start in plan mode, show a short plan (files to add/change), then implement.
- Read existing code for the area before changing it. Reuse services (numbering, workflow, budget_control, ledger, email, audit, storage) and UI components; do not duplicate them.
- Do not refactor, rename or restyle code outside the current scope. Do not touch earlier phases except to add fields or hooks the prompt names.
- Every phase: Alembic migration, backend tests for the business rules listed in the prompt, all tests green before reporting.
- Report at the end: files added/changed, migrations, env vars, how to test manually. Keep it short.
- Commit once per sub-phase with message `phase <n>: <scope>`.

## UI rules (details in docs/brand/BRAND.md)
- Nustrad theme: brand-ink sidebar with the reverse logo, white work area, gold as fill and accent only (never gold text on white), Prompt for headings, Montserrat for text, light and dark themes from the same tokens.
- Dense, scannable screens: summary first, then the table. Status as pills. Every list has filters, pagination and Excel export.
- Accessible: 4.5:1 text contrast, visible focus ring, keyboard reachable, works at 400 px width.
