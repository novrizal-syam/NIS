# 02b · Quotation
1. Quotation per opportunity: lines from the price database (editable qty, unit cost, unit price), discount %, revisions with history. Totals and margin computed in the backend.
2. Submit via DOA `quotation` (margin ≥ 25% Head of Sales; < 25% Director). Margin < 20% shows a danger warning.
3. Approved → "Kirim ke klien": quotation PDF on the GEK letterhead (company profile logo), saved in DMS, outgoing letter number `001/GEK-SLS/{roman}/{year}` from numbering (table `outgoing_letters`: number, to, subject, date, file), optional email to the client contact via `send_email`; stage → Submitted.

Tests: margin calculation with discount, DOA routing at 25%, revision history.
