#!/usr/bin/env bash
# Tested restore (10d): restore the newest dump into a scratch database and compare it with
# the source: migration version, row counts of key tables, trial balance zero, encrypted
# personal data still encrypted. Exit code != 0 when anything differs. Run weekly.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BACKUP_DIR=${BACKUP_DIR:-/backups}
SOURCE=${PGDATABASE:-nustrad}
CHECK_DB=${CHECK_DB:-nustrad_restore_check}
DUMP=${1:-$(ls -1t "$BACKUP_DIR"/daily/nustrad-*.dump | head -1)}
"$HERE/restore.sh" "$DUMP" "$CHECK_DB" --yes >/dev/null

q() { psql -X -A -t -v ON_ERROR_STOP=1 -d "$1" -c "$2"; }
fail=0
for table in alembic_version users journal_entries journal_lines customer_invoices vendor_invoices dors employees attachments audit_log; do
  a=$(q "$SOURCE" "SELECT count(*) FROM $table" 2>/dev/null || echo missing)
  b=$(q "$CHECK_DB" "SELECT count(*) FROM $table" 2>/dev/null || echo missing)
  if [ "$a" != "$b" ]; then echo "MISMATCH $table: source=$a restored=$b"; fail=1; fi
done
v1=$(q "$SOURCE" "SELECT version_num FROM alembic_version")
v2=$(q "$CHECK_DB" "SELECT version_num FROM alembic_version")
[ "$v1" = "$v2" ] || { echo "MISMATCH migration: $v1 vs $v2"; fail=1; }
tb=$(q "$CHECK_DB" "SELECT coalesce(sum(debit) - sum(credit), 0) FROM journal_lines")
[ "$tb" = "0" ] || { echo "TRIAL BALANCE not zero in restore: $tb"; fail=1; }
plain=$(q "$CHECK_DB" "SELECT count(*) FROM employees WHERE nik IS NOT NULL AND nik NOT LIKE 'enc:%'")
[ "$plain" = "0" ] || { echo "UNENCRYPTED NIK rows in restore: $plain"; fail=1; }
psql -X -q -d postgres -c "DROP DATABASE IF EXISTS \"$CHECK_DB\" WITH (FORCE)"
if [ "$fail" = "0" ]; then echo "restore verified: $DUMP (migration $v2)"; fi
exit $fail
