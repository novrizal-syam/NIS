#!/usr/bin/env bash
# Restore a dump into a database (10d). DESTROYS the target database's current content.
#   restore.sh <dump-file> <target-db> --yes
set -euo pipefail
DUMP=${1:?dump file}
TARGET=${2:?target database}
[ "${3:-}" = "--yes" ] || { echo "Add --yes to confirm overwriting database $TARGET" >&2; exit 2; }
if [ -f "$DUMP.sha256" ]; then sha256sum -c "$DUMP.sha256" >/dev/null; fi
psql -v ON_ERROR_STOP=1 -d postgres -c "DROP DATABASE IF EXISTS \"$TARGET\" WITH (FORCE)"
psql -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE \"$TARGET\""
pg_restore --no-owner --exit-on-error -d "$TARGET" "$DUMP"
echo "restore ok: $DUMP -> $TARGET"
