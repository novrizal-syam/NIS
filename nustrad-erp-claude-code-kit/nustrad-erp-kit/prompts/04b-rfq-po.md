# 04b · RFQ and purchase order
1. RFQ from an Approved PR to ≥ 3 vendors of the matching category (CSMS pending/Blacklisted not selectable); record quotes (price, delivery days, terms, validity, attachment).
2. Scoring: price 60% (lowest/price), delivery 20% (fastest/days), vendor rating 20% (rating/5); weights in settings. Non-best award → DOA `rfq_award` with written reason. Price history per item/vendor.
3. PO (PO-26-xxx) from the award: lines, PPN, terms, delivery, standard late-delivery penalty clause; PDF on GEK letterhead. Issue → `release` pre-commitment of the PR + `commit` PO value; savings return to available. Revision with higher value → re-approval.
Tests: CSMS exclusion, scoring, budget movements, revision rule.
