# 00 · Bootstrap the repository
Scope: empty repo → running skeleton. No business modules yet.

1. Create the layout in CLAUDE.md. Docker Compose with `api` (FastAPI, uvicorn reload), `web` (Vite dev server), `db` (PostgreSQL 16), `minio`, `mailpit` (SMTP catcher for dev). `.env.example` with every variable; never commit `.env`.
2. Backend core: settings (pydantic-settings), async SQLAlchemy session, Alembic with naming conventions, base model (id UUID, created_at, updated_at, created_by, is_demo), error handler returning `{code, message}` in Bahasa Indonesia, health endpoint, structured JSON logging, CORS for the web origin.
3. Services stubs with tests: `numbering.next(doc_type)` using a counter table with `SELECT … FOR UPDATE` (prove no duplicates with 50 parallel calls), `audit.record(...)`, `storage.put/get` (MinIO), `money` helpers (IDR integer, id-ID formatting).
4. Frontend: Vite + React + TS, Tailwind, shadcn/ui, TanStack Query, react-i18next (id default, en), React Router. Implement the Nustrad theme from `docs/brand/BRAND.md`: `src/theme/tokens.css` (light + dark + system via `prefers-color-scheme` and a `data-theme` toggle), Tailwind mapping, fonts, focus ring. Copy logos from `docs/brand/logos/` to `public/brand/`; favicon and PWA icons from the monogram.
5. App shell per BRAND.md: ink sidebar with reverse logo and grouped menu (Ringkasan · Lead ke Kontrak · Rencana · Procure to Pay · Eksekusi · Order to Cash · Keuangan · SDM & Dokumen · Settings) — items not built yet show "Segera"; top bar; login page placeholder; a "Komponen" dev page showing buttons, inputs, table, status pills, cards in both themes.
6. Tooling: ruff + mypy (backend), eslint + prettier + typecheck (frontend), pytest + Vitest wired, a `Makefile` with `up`, `migrate`, `test`, `lint`.
7. GitHub Actions CI: lint, typecheck, tests on push.

Done when: `docker compose up` shows the themed shell at localhost, the dev Komponen page passes a contrast check in light and dark, all tests and linters green. Report files and commands.
