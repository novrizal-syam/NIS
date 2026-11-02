# 03b · Budget control service (used by phases 04–07)
1. `budget_ledger` (append-only): project, wbs, cost_element, kind (pre_commit|commit|actual|release), amount, doc_type, doc_id, at, by. Balances are derived, never stored by hand.
2. `services/budget_control.py`: `available()`, `check()` (blocked when project not Locked, cost element is Contingency, or amount > available; returns shortfall), `reserve()`, `commit()`, `actualize()`, `release()`; each in a transaction with a row lock on the budget line so parallel calls cannot overspend.
3. Notify Planner and Lead Controller once per line when usage crosses 80%.
4. Project detail table: budget, pre-commit, commit, actual, available, % used bar (warning ≥ 80%, danger when exhausted).
5. Admin-only test endpoint `POST /api/budget/test-check` (disabled when `ENV=production`).
Tests: all functions; two parallel reserves exceeding available → only one succeeds.
