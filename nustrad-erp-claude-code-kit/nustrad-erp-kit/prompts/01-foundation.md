# 01 · Foundation: auth, RBAC, master data, DOA engine, audit, DMS core, notifications
Read first: docs/domain/DOA.md. Reuse services from 00.

1. Auth: email + password (argon2), JWT access (15 min) + refresh (httpOnly cookie, rotation), forced password change on first login, lock after 5 failures, TOTP 2FA (required per role, configurable).
2. RBAC: permissions = module × action (view, create, edit, delete, submit, approve, post, export, admin) + data scope (own, department, project, all) + sensitive-field permissions. FastAPI dependency `require(module, action)` and a scope filter helper. Seed roles from DOA.md.
3. Master data (CRUD, CSV import, Excel export, demo seed): departments & cost centers; clients (NPWP, CSMS status, payment term, currency); vendors (NPWP, bank account, category, status Qualified/CSMS pending/Blacklisted, rating, legal docs with expiry); employees (position, basic salary, PTKP, BPJS numbers, bank, certificates with expiry); items (UoM, category, reorder point); warehouses (Base Cilegon + per-project site); assets (code, class, criticality A/B/C, internal day rate, certificates/calibration expiry); chart of accounts, cost elements and periods from docs/domain/ACCOUNTING.md; price database (8 demo services: pump unit, booster pump, field engineer, operator, chemicals package, nitrogen unit, mob/demob, HSE package); currencies & FX rates.
4. Workflow/DOA engine: `doa_rules` table (doc_type, ordered steps, condition expressions on document fields, parallel groups, approver role), `approval_requests` + `approval_steps`; API submit/approve/reject/delegate; SoD check (requester ≠ approver) in the engine; escalation job; "Persetujuan Saya" inbox with count badge, filters, bulk approve; Settings screen to edit rules. Seed all rules from DOA.md.
5. Audit trail screen with filters; "Riwayat" tab component reusable on any document.
6. DMS core: attachments on any document (PDF/JPG/PNG ≤ 20 MB, versioning, preview).
7. Notifications: in-app bell (approval incoming, returned, expiry alerts); email via `services/email.py` stub (Mailpit in dev).
8. Demo seed (is_demo): one user per role (list in README), 5 clients, 15 vendors (3 per category, 1 CSMS pending), 8 field employees + office staff, 10 items, 6 assets, full COA, periods Jan–Dec 2026 (Jan–Sep closed, Oct open).

Tests: permission denial per role, scope filter, SoD rejection in engine, rule routing by amount, numbering under concurrency. Done when the role matrix behaves as DOA.md and all tests pass.
