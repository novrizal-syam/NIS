# 05b · Assets & maintenance, QHSE
1. Equipment register extended per GEK-MNT-001: 27 equipment types (well testing, instrumentation, utilities, pumping), criticality A/B/C, certificates & calibration with 90/60/30-day alerts; expired = cannot be allocated to a project.
2. PM task library by equipment type and frequency (daily/weekly/monthly/operating hours/per job/annual) with an importer for `GEK_PM_Plan_Peralatan.xlsx` (sheets Task Library, Equipment Register).
3. Scheduler: calendar and operating-hour triggers (hours from DOR) → work orders with checklists (FRM-MNT forms), spare parts issued from stock, labour hours, photos, result, signature. Corrective WO auto-created from DOR breakdowns. Downtime log. Pre-mobilisation and post-job inspection checklists.
4. KPIs: utilisation (≥ 85%), downtime (< 3%), PM compliance, MTBF/MTTR.
5. QHSE: HIRADC/JSA per project (required before first DOR), permit to work, inspections, observations, incidents & investigation, CAPA with due dates, statistics (man-hours, LTI, TRIR), CSMS evidence export.
Tests: allocation blocked by expired certificate, hour-based PM trigger, corrective WO from breakdown.
