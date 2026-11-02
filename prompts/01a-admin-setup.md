# 01a · First-run setup and role administration
Extend 01; do not remove existing users or data.

1. First-run wizard at /setup while `system_settings.setup_completed = false`; every other route redirects there. Requires the one-time `SETUP_TOKEN` env var. Steps: Super Admin account (strong password) → mandatory TOTP + 10 recovery codes shown once → company profile (PT Global Energi KITA, NPWP, address, logo, fiscal year Jan–Dec, IDR, Asia/Jakarta, Bahasa Indonesia) → departments/cost centers (prefilled) → load demo data or start empty → finish (setup_completed = true; /setup returns 403 forever). Audit every step. Wizard uses the Nustrad login layout from BRAND.md.
2. Super Admin vs Admin: the last Super Admin cannot be deleted, deactivated or demoted; warn when only one exists. Admin has no business approve/post permissions. Break-glass 2FA reset only via recovery code or an audited CLI command.
3. Users: list (status Invited/Active/Locked/Inactive, 2FA, last login), invite by email link (72 h, single use) or temporary password shown once, CSV/Excel import with error report, deactivate (no delete), reset password, unlock, reset 2FA, force logout, active sessions, link to employee record.
4. First login for normal users: change password → accept privacy notice (UU 27/2022 PDP, store timestamp) → 2FA if the role requires → profile (photo, phone, signature image) → short skippable role tour.
5. Roles & permissions screen: system roles (editable permissions, not deletable) and custom roles (create, clone, deactivate); permission matrix module × action with checkboxes; data scope per module; sensitive-field permissions (default: HCBP Officer, Head of Finance & Support, Director); temporary role assignments with start/end dates (auto-revoke job); read-only "View as role" preview (audited).
6. SoD conflict rules screen (pairs from DOA.md); assigning a conflicting combination requires reason + Director approval and lands in the SoD exception register.
7. Quarterly access review report (user × roles × sensitive permissions × last login; flag > 90 days inactive), Excel/PDF export.

Tests: /setup without token → 403; second setup → 403; last Super Admin protection; revoked permission → endpoint 403 immediately; salary hidden in API and export; temporary role expiry; SoD conflict needs approval.
