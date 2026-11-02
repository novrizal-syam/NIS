# 03c · Budget Change Request and versions
1. BCR form on a Locked project: WBS, cost element, amount, source (Contingency release | Budget increase | Transfer), reason, justification, attachment, optional reference to a blocked document.
2. Backend validation: release ≤ remaining contingency; transfer ≤ available on the source line.
3. DOA `bcr` per DOA.md (≤ 10% Head of Operation; larger or revenue change Director).
4. Approval → new version in `budget_versions` (v1, v2, …) with change note; baseline v0 untouched; current = latest.
5. Emit `bcr_approved(project, wbs, cost_element, ref)` hook (consumed in 04a).
6. Tabs: "Versi anggaran" (baseline vs current per line) and "BCR".
Tests: 10% routing, contingency limit, baseline immutability. Playwright: draft → controller (18% rejected, 25% passes) → approve → Locked → test-check over budget blocked → BCR → approved → v1 → test-check passes.
