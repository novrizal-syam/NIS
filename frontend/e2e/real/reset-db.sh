#!/usr/bin/env bash
# Recreate the throw-away e2e database (migrations + seed). Run from the repo root.
# Needs: a local PostgreSQL (postgres/postgres) and the backend virtualenv.
set -euo pipefail
cd "$(dirname "$0")/../../../backend"
. .venv/bin/activate
PGPASSWORD=${PGPASSWORD:-postgres} psql -h localhost -U postgres -q \
  -c "DROP DATABASE IF EXISTS nustrad_e2e WITH (FORCE)" -c "CREATE DATABASE nustrad_e2e"
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/nustrad_e2e
export S3_ENDPOINT_URL=${S3_ENDPOINT_URL:-http://localhost:9000}
alembic upgrade head >/dev/null 2>&1
python -m tests.e2e_seed
# Object storage bucket (MinIO in docker compose creates it; a bare S3/moto does not).
python - <<'PY'
from app.services.storage import get_storage
import asyncio
asyncio.run(get_storage().ensure_bucket())
PY
