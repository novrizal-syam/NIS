#!/usr/bin/env bash
# Production health check (10f). Run every 5 minutes from cron on the VM (or any host):
#   */5 * * * * ERP_URL=https://erp.gek.co.id BACKUP_DIR=/srv/nustrad-backups \
#     ALERT_EMAIL=it@gek.co.id /opt/nustrad/deploy/monitoring/check.sh
# Checks: API and database answer, TLS certificate valid > 14 days, last backup < 26 hours,
# disk < 85 %. Prints one line per problem and exits 1; sends mail when ALERT_EMAIL is set
# and `mail` exists. Optional HEARTBEAT_URL (e.g. a healthchecks.io ping) is called on success.
set -uo pipefail
ERP_URL=${ERP_URL:?set ERP_URL}
BACKUP_DIR=${BACKUP_DIR:-/srv/nustrad-backups}
problems=()

health=$(curl -fsS --max-time 10 "$ERP_URL/api/health" 2>/dev/null) || health=""
case "$health" in
  *'"status":"ok"'*) ;;
  "") problems+=("API tidak menjawab di $ERP_URL/api/health") ;;
  *) problems+=("API menjawab tetapi tidak sehat: $health") ;;
esac

host=${ERP_URL#https://}; host=${host%%/*}
if end=$(echo | openssl s_client -servername "$host" -connect "$host:443" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2); then
  if [ -n "$end" ] && [ $(( ($(date -d "$end" +%s) - $(date +%s)) / 86400 )) -lt 14 ]; then
    problems+=("Sertifikat TLS habis dalam < 14 hari ($end)")
  fi
fi

if [ -d "$BACKUP_DIR" ]; then
  if [ ! -f "$BACKUP_DIR/last-ok" ] || [ -n "$(find "$BACKUP_DIR/last-ok" -mmin +1560)" ]; then
    problems+=("Backup terakhir lebih dari 26 jam yang lalu (lihat $BACKUP_DIR/backup.log)")
  fi
  used=$(df --output=pcent "$BACKUP_DIR" | tail -1 | tr -dc 0-9)
  [ "${used:-0}" -ge 85 ] && problems+=("Disk backup terisi ${used}%")
fi
used=$(df --output=pcent / | tail -1 | tr -dc 0-9)
[ "${used:-0}" -ge 85 ] && problems+=("Disk sistem terisi ${used}%")

if [ ${#problems[@]} -eq 0 ]; then
  [ -n "${HEARTBEAT_URL:-}" ] && curl -fsS --max-time 10 "$HEARTBEAT_URL" >/dev/null
  exit 0
fi
msg=$(printf '%s\n' "${problems[@]}")
echo "$msg"
if [ -n "${ALERT_EMAIL:-}" ] && command -v mail >/dev/null; then
  echo "$msg" | mail -s "[Nustrad ERP] Peringatan produksi" "$ALERT_EMAIL"
fi
exit 1
