# Nustrad ERP REST API

The full specification is [`openapi.json`](openapi.json) (OpenAPI 3.1, generated from the code with
`cd backend && python -m scripts.export_openapi`; a test fails when it is out of date). Outside
production the interactive documentation is served at `/api/docs`.

## Basics

| Topic | Rule |
| --- | --- |
| Base path | `/api` |
| Authentication | `POST /api/auth/login` → access token (15 minutes) + HttpOnly refresh cookie; send `Authorization: Bearer <token>`; `POST /api/auth/refresh` renews it. 2FA codes go in the login body. |
| Authorisation | Every endpoint checks role + permission + data scope (own, department, project, all). Approvals go through the DOA engine; nobody approves their own document. |
| Sensitive data | Salary, NIK, bank account and personal tax ID are omitted unless the caller holds the matching permission (UU 27/2022 PDP). |
| Errors | `{"code": "BUDGET_BLOCKED", "message": "…", "details": {…}}`; messages in Bahasa Indonesia; 401 / 403 / 404 / 409 / 422 as usual. |
| Money | Strings of whole rupiah (`"1250000"`); USD with two decimals. Never floats. |
| Dates | `YYYY-MM-DD`; timestamps ISO 8601 in UTC; business dates are Asia/Jakarta. |
| Lists | Filters as query parameters; long lists paginate with `page` (50 per page) or are capped and sorted newest first. |
| Files | Upload with `multipart/form-data` to `/api/attachments` (PDF, JPG, PNG, max 20 MB); downloads stream through the API so permissions apply. |
| Public | Only `/api/health`, the setup wizard, sign-in, client signature links (`/api/billing/sign/{token}`) and DMS share links (`/api/public/share/{token}`) work without a token. |

## Integration adapters

| Integration | Without credentials (manual/file) | With credentials |
| --- | --- | --- |
| Coretax DJP via PJAP | `POST /api/integrations/pjap/efaktur` returns the e-Faktur XML to import in Coretax | `PJAP_BASE_URL`, `PJAP_API_KEY`: the XML is uploaded and the PJAP reference returned |
| Bank | Bulk-transfer CSV per payment run; statements imported as CSV/MT940 | Host-to-host adapter per bank account (Mandiri, BRI, BNI, BCA) implementing `treasury.adapters.BankAdapter` |
| PSrE e-signature | `internal`: signature image + audit reference | Provider adapter registered in `billing.psre`, selected with setting `psre.provider` |
| e-Meterai (Peruri) | `internal` reference only | Provider adapter in `letters.emeterai`, setting `emeterai.provider` |
| Email | Notifications kept in-app | `EMAIL_PROVIDER=smtp` + `SMTP_*`, or `resend` + `RESEND_API_KEY` |
| WhatsApp Business | Outbox with wa.me links (Pengaturan › Integrasi) | `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TOKEN` (Cloud API; job `whatsapp`) |

Secrets are only read from environment variables; settings in the database hold modes and
non-secret options. `GET /api/integrations` shows what is live.
