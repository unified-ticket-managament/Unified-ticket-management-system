# Local Environment

Two processes, run in two terminals:

```bash
cd unified-backend && bash scripts/start.sh     # :8000
cd unified-frontend && npm run dev              # :3000
```

That's it for full end-to-end local testing — the standalone `ticketing-service/frontend` is not needed and no longer exists in the repository at all (as of 2026-08-21, `ticketing-service/` is an empty directory).

## What `scripts/start.sh` actually does

```bash
alembic -c alembic_rbac/alembic.ini upgrade head
alembic -c alembic_ticketing/alembic.ini upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```

On native Windows PowerShell (not Git Bash/WSL), run these three commands individually instead of the bash script.

## Restarting after changes

- **Python code changes**: `uvicorn --reload` picks these up automatically.
- **`.env` changes**: `Settings` is `@lru_cache`d — **a full process restart is required**, `--reload` does not react to `.env` edits.
- **`.env.local` (frontend) changes**: `NEXT_PUBLIC_*` vars are baked in at server start — restart `npm run dev`.

## Windows-specific gotchas (confirmed, recurring in this project's own history)

- `--reload`'s "Reloading..." log line is not proof the new code is live — compare the worker's actual start time against the edited file's mtime, or better, hit the real route with a fresh token.
- Killing the PIDs `uvicorn` reports doesn't reliably clean up orphaned `python.exe` processes or stale socket entries. If you see `[WinError 10013]`, kill every python/uvicorn process, confirm `Get-NetTCPConnection -LocalPort 8000` returns nothing, then start exactly one fresh process.
- If you rename/move the `unified-frontend` directory, delete `.next/` before running `npm run dev` again — Turbopack's cache stores absolute paths tied to the old location.
- Never run `npm run build` in the same directory while `npm run dev` is active — both write into `.next/` and corrupt each other's manifests, making every route 404.

## Local database sharing risk

If you point your local `.env` at the same Neon database used by a deployed environment, your local SLA scheduler and the deployed one both tick against the same rows — a real, confirmed source of confusing "my fix isn't working" sessions. **Recommendation**: create a Neon branch for local development.
