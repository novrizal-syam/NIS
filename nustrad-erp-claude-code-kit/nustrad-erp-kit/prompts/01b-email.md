# 01b · Email delivery for invitations and password reset
Small scope. Do not change auth flows or UI beyond what is listed.

1. `services/email.py`: `send_email(to, subject, html, text)`; provider from env: `EMAIL_PROVIDER` (smtp|resend), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS`, `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_FROM_NAME`, `APP_BASE_URL`. No credentials in code.
2. Wire it into the existing invite (link `/activate?token=…`, 72 h, single use) and forgot-password (`/reset-password?token=…`, 60 min, single use). Tokens stored hashed.
3. Two Bahasa Indonesia HTML templates on the Nustrad theme (primary logo, gold button with ink label, plain footer "Dikirim oleh Nustrad ERP untuk PT Global Energi KITA"), with expiry and "abaikan jika bukan Anda".
4. Send in a background task; `email_log` (to, kind, status sent/failed/not_configured, error, time), never store tokens in logs.
5. Settings → Pengguna: "Kirim ulang undangan" (invalidates old token), last email status; "Kirim email uji" (Super Admin).
6. Forgot-password always returns the same message; rate limit 3 per email per hour.
7. Not configured → no error; show the activation link to the admin to copy; log `not_configured`.

Tests: token expiry, single use, hashing, rate limit; send verified against Mailpit in dev.
