# Backend Setup

```bash
cd unified-backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

This installs `shared_models` automatically as a local editable package (`-e ../shared_models` is in `requirements.txt`) — no separate step needed.

Create `.env` — see [environment-variables.md](environment-variables.md) (no template file exists; construct it from that document).

Run migrations and start the server:

```bash
alembic -c alembic_rbac/alembic.ini upgrade head
alembic -c alembic_ticketing/alembic.ini upgrade head
uvicorn app.main:app --reload --port 8000
```

Or, on Git Bash/WSL/macOS/Linux, the bundled script does all three in order:

```bash
bash scripts/start.sh
```

The API is now at `http://localhost:8000` — interactive docs at `/docs`, ReDoc at `/redoc`, health check at `/health`.

## A critical gotcha: always use the venv's own interpreter

**Never start the backend via a bare `python -m uvicorn ...` or a `uvicorn` on `PATH`** — this can silently resolve `shared_models` to a different, unrelated, stale editable install elsewhere on the machine (confirmed to have happened: check `shared_models.models.user.__file__` if you ever see a confusing `TypeError: '<field>' is an invalid keyword argument for User`). Always start via `.venv\Scripts\python.exe` (or the activated venv's own `uvicorn`).

## Verifying it's really running your code

Don't trust a `--reload` "Reloading..." log line alone. Compare the running worker process's start time against the mtime of any file you just edited, and/or mint a real token and hit an actual route with `curl`/`httpx` — see [10-operations/system-health.md](../10-operations/system-health.md) for the full reasoning.

## Local object storage (optional)

```bash
docker-compose up -d   # MinIO, if you don't want to use real Supabase/S3 locally
```

## Microsoft Graph — optional

Leave all four `GRAPH_*` settings unset to use the built-in mock mail provider (no error, safe default for local dev). Only configure real Graph credentials if you need to test actual inbound/outbound email against a real mailbox.
