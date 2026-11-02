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
- App: http://localhost:5173 · component catalogue (dev only): http://localhost:5173/dev/komponen
- API: http://localhost:8000/api/health · docs: http://localhost:8000/api/docs
- Mailpit: http://localhost:8025 · MinIO console: http://localhost:9001
- Checks: `make test`, `make lint`, `make e2e` (Playwright: contrast in light/dark, 400 px width, focus ring)

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
