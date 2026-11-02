# 03a · Budget edit, Controller review, approval, baseline lock
Read: PROCESS.md (Project & budget), DOA.md (project_budget).
1. Budget editor for Draft projects: cost element × WBS (default "Execution"; add Mobilisation/Demobilisation/per well), integer IDR; backend totals, revenue, planned margin.
2. Status machine Draft → Controller review → Awaiting approval → Locked, enforced in the backend.
3. DOA `project_budget`: step 1 Lead Controller (backend rejects approval when margin < settings threshold 20%; reject needs a note → Draft); step 2 ≤ Rp 2 M Head of Operation, > Rp 2 M Director.
4. Final approval → Locked + immutable baseline v0 in `budget_versions`; all budget fields read-only after lock (backend). Contingency row flagged `locked_reserve`.
5. Status badge in lists; stepper in project detail.
Tests: margin threshold, amount routing, SoD, edit after lock rejected.
