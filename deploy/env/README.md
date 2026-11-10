# Environments

| | development | staging | production |
| --- | --- | --- | --- |
| `APP_ENV` | `development` | `staging` | `production` |
| Secrets | dev defaults allowed | real, refused if missing | real, refused if missing |
| `DATA_ENCRYPTION_KEYS` | optional (derived) | required, own key | required, own key |
| HTTPS / HSTS | no | required | required |
| API docs `/api/docs` | on | on | off (see `docs/api/`) |
| Demo data | allowed | allowed for rehearsal | removed before go-live |
| Integrations | manual/file | manual or provider sandbox | live when credentials exist |
| Data | local | restored copy of production for rehearsals | real |

Copy the matching `*.env.example` to `.env` on the server. The API refuses to start in staging
or production when SECRET_KEY, DATA_ENCRYPTION_KEYS, HTTPS URLs or the storage secret are unsafe.
