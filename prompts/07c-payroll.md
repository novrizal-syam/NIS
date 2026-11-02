# 07c · Payroll (hire to pay)
1. Monthly period with cut-off (default 25th). Components: basic, fixed allowances, field allowance per site day (default Rp 350.000), overtime (1/173 × basic × factor, PP 35/2021), deductions.
2. Site days and overtime from approved DORs (timesheet), editable by HCBP with reason.
3. BPJS (Kesehatan, JHT, JP, JKK, JKM) employee/employer with wage caps; PPh 21 TER monthly (PP 58/2023) from tables stored as data; December annual calculation; 1721-A1.
4. Calculate → HCBP submit → DOA `payroll` → journal (field cost allocated to projects by DOR days) → paid via payment run. Payslip PDFs visible only to the employee and HCBP. Sensitive-field rules apply to every screen and export.
Tests: days from DOR, TER lookup, BPJS caps, allocation to projects, journal balance, payslip access control.
