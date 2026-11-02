# 02a · Leads, opportunities, bid/no-bid
Read: docs/domain/PROCESS.md (Lead to contract). Reuse workflow, numbering, audit, attachments, UI components.

1. Leads list + form (company, contact, source CIVD/e-proc/invitation/visit/referral/website/exhibition, need, estimated value), status machine, qualification checklist (≥ 3 of 5) → "Jadikan Opportunity".
2. Opportunities: kanban (Qualified → Quotation → Submitted → Won/Lost) + table view, owner, probability, value.
3. Bid/no-bid form (6 scores) → doc_type `bid_decision` through the DOA engine; approve → Quotation stage; no-bid/reject → Lost with reason.
4. Sales dashboard tiles: open pipeline, weighted pipeline, win rate vs 45% target, new contract value YTD vs Rp 80 M.

Tests: score threshold, SoD on bid_decision, status transitions.
