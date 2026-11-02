# 04c · Goods receipt, inventory, material request
1. Inventory: stock per item per warehouse (Base Cilegon, project sites), moving-average cost, transfers base → site, stock opname with variance approval by Lead Controller, reorder suggestions; valuation report reconciles to account 1310.
2. GR (partial/full) by Warehouse Head (goods) or project owner (services), photos/BAST: `commit` → `actualize`; journal per ACCOUNTING.md (direct to project expense, or inventory for stock items) via `ledger.post_journal` (create the ledger service here if 07a has not run: balanced-entry check, closed-period check, dimensions).
3. MR by Field Engineer: check site then base stock; issue available quantity (actual + journal 5300/1310); shortfall auto-creates a PR at last price (04a rules apply).
Tests: moving average, partial GR, journal balance, MR split into issue + PR.
