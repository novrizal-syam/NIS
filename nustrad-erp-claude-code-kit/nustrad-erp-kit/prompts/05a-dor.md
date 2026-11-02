# 05a · Daily Operational Report (PWA, offline-first)
Read: PROCESS.md (Execution).
1. Mobile-first DOR screen for Locked projects with all sections in PROCESS.md; configurable technical-data templates per service line (well test: oil/gas/water rates, pressures, choke; pumping: rate, pressure).
2. Validations: 24 h per unit; consumables ≤ site stock; mobilisation gate (expired mandatory certificate cannot be selected, reason shown; warn ≤ 60 days).
3. Live pricing preview from the contract rate schedule (equipment hours/24 × status rate, breakdown 0; personnel per person-day; consumables cost × (1 + markup)) and internal cost (internal rates, moving-average stock cost).
4. Offline: IndexedDB drafts, background sync, conflict detection; installable PWA with the Nustrad monogram icon.
5. Submit → DOA `dor` (project Superintendent, SoD); late flag after 08:00 next day.
6. Approval in ONE transaction: project actuals per cost element, site stock issue, journals (1220/4100 and 5300/1310), asset operating hours, HSE man-hours, payroll day records; contract usage alert to Head of Sales at ≥ 80%.
Tests: validations, pricing, transaction effects, SoD. Playwright incl. offline draft then sync.
