#!/usr/bin/env bash
# Daily backup (10d): PostgreSQL custom-format dump + object storage mirror.
#   PG* variables (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE) select the database.
#   BACKUP_DIR (default /backups), BACKUP_KEEP_DAYS (daily dumps kept, default 35).
#   Monthly dumps (taken on the 1st) are kept 10 years (UU KUP art. 28 / UU 8/1997).
#   Optional: MC_SOURCE (mc alias/bucket of the app storage) and MC_TARGET (off-site copy).
set -euo pipefail
BACKUP_DIR=${BACKUP_DIR:-/backups}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-35}
STAMP=$(date -u +%Y%m%d-%H%M)
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly"
FILE="$BACKUP_DIR/daily/nustrad-$STAMP.dump"

pg_dump --format=custom --compress=9 --no-owner --file="$FILE.part" "${PGDATABASE:-nustrad}"
mv "$FILE.part" "$FILE"
sha256sum "$FILE" > "$FILE.sha256"
if [ "$(date -u +%d)" = "01" ]; then
  cp "$FILE" "$FILE.sha256" "$BACKUP_DIR/monthly/"
fi
find "$BACKUP_DIR/daily" -name 'nustrad-*.dump*' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR/monthly" -name 'nustrad-*.dump*' -mtime +3660 -delete

if [ -n "${MC_SOURCE:-}" ] && command -v mc >/dev/null; then
  mc mirror --overwrite --quiet "$MC_SOURCE" "$BACKUP_DIR/objects"
fi
if [ -n "${MC_TARGET:-}" ] && command -v mc >/dev/null; then
  mc mirror --overwrite --quiet "$BACKUP_DIR" "$MC_TARGET"
fi
echo "backup ok: $FILE ($(du -h "$FILE" | cut -f1))"
