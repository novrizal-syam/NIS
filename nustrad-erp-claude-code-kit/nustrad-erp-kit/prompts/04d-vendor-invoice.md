# 04d · Vendor invoice and 3-way match
1. AP Accountant records vendor invoice: number, tax invoice number, date, DPP, PPN, type goods/service-rental, attachment.
2. 3-way match PO vs GR vs invoice (qty and price, tolerance setting default 0) → "Approved for payment" (due = date + term) or "Match exception" (not payable; resolved by credit note/correction).
3. PPN input 12% × 11/12 DPP (or as on the faktur); PPh 23 2% withheld for services/rentals; journal per ACCOUNTING.md.
4. AP aging; vendor statement.
Tests: match/exception, tax amounts, journal balance, exception cannot enter a payment run.
