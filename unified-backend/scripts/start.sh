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

# The SLA sweep runs in-process now (app/core/sla_scheduler.py, an
# APScheduler job started from app/main.py's lifespan) — identically
# in local dev and every deployed environment, no separate cron/loop
# process needed here anymore.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
