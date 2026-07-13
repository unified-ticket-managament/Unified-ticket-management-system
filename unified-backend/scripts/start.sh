#!/usr/bin/env bash
# Runs both independent Alembic migration chains (rbac-owned tables,
# then ticketing-owned tables — order matters only against a genuinely
# empty database, since ticketing's tables FK into rbac's users table),
# then starts the single unified uvicorn process. Run from unified-backend/
# as the working directory (both alembic.ini's script_location and each
# Settings' env_file=".env" resolve relative to CWD).
set -e

alembic -c alembic_rbac/alembic.ini upgrade head
alembic -c alembic_ticketing/alembic.ini upgrade head

# Local-dev-only convenience: nothing else triggers the SLA sweep
# outside of Render's own once-a-minute Cron Job hitting
# POST /internal/sla/sweep in production (see scripts/sla_sweep_ping.py),
# so a still-PENDING clock never gets checked at all during local
# testing unless something else pokes that endpoint. Opt in per-
# developer by exporting ENABLE_LOCAL_SLA_SWEEP_LOOP=true in your own
# shell/`.env` — this must never be set in Render's env vars, since
# this same start.sh is also Render's unified-backend startCommand and
# the real cron job already covers that endpoint there.
if [ "${ENABLE_LOCAL_SLA_SWEEP_LOOP:-false}" = "true" ]; then
  echo "ENABLE_LOCAL_SLA_SWEEP_LOOP=true — starting local SLA sweep loop in background."
  python scripts/sla_sweep_local_loop.py &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
