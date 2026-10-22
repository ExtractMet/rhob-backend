#!/usr/bin/env sh
# Render-safe start script: binds 0.0.0.0 and $PORT (default 10000), applies migrations when
# a PostgreSQL DATABASE_URL is configured, then starts uvicorn.
set -e
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-1}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
case "$DATABASE_URL" in
  postgres*) alembic upgrade head ;;
esac
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers
