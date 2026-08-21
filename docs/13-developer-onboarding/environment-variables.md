# Environment Variables

**No `.env.example` exists for `unified-backend/`** (confirmed — the only `.env.example` in the entire repository is `unified-frontend/.env.example`). This document is the template.

## `unified-backend/.env`

```env
APP_NAME=Unified Backend
APP_ENV=development
DEBUG=true

# Async connection string (asyncpg) — the app's own runtime connection
DATABASE_URL=postgresql+asyncpg://user:password@host/dbname

# Sync connection string (psycopg2) — used only by Alembic migrations
ALEMBIC_DATABASE_URL=postgresql+psycopg2://user:password@host/dbname

# Generate with: python -c "import secrets; print(secrets.token_urlsafe(64))"
JWT_SECRET_KEY=<generate-a-random-secret>
JWT_ALGORITHM=HS256

# Protects the manual SLA-sweep trigger endpoint — any random string
SLA_SWEEP_SHARED_SECRET=<generate-a-random-secret>

CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Attachment storage — "supabase" (default) or "s3"
STORAGE_BACKEND=supabase
STORAGE_BUCKET=communication-attachments
SUPABASE_URL=<your-supabase-project-url>
SUPABASE_SERVICE_ROLE_KEY=<your-supabase-service-role-key>

# Optional — omit entirely to use the mock mail provider / logging-only email
# GRAPH_TENANT_ID=
# GRAPH_CLIENT_ID=
# GRAPH_CLIENT_SECRET=
# GRAPH_MAILBOX_ADDRESS=
# GRAPH_WEBHOOK_CLIENT_STATE=
# GRAPH_WEBHOOK_NOTIFICATION_URL=
# SMTP_HOST=
# SMTP_USERNAME=
# SMTP_PASSWORD=
# SMTP_FROM_EMAIL=
```

See [05-technical-architecture/configuration.md](../05-technical-architecture/configuration.md) for the complete field list, defaults, and what happens when an optional field is left unset.

## `unified-frontend/.env.local`

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_TICKETING_API_URL=http://localhost:8000
```

**Set `NEXT_PUBLIC_TICKETING_API_URL` explicitly** — if left unset, it silently falls back to `http://localhost:8001` (a stale pre-merge default), which network-errors every ticketing request while RBAC-native requests keep working. This exact symptom (RBAC works, tickets/inbox don't) has confused more than one debugging session in this project's history.

## Local MinIO (if not using real Supabase/S3 for local dev)

```bash
cd unified-backend
docker-compose up -d
```

Then point `STORAGE_BACKEND=s3`, `STORAGE_ENDPOINT_URL=http://localhost:9000`, `STORAGE_ACCESS_KEY=minioadmin`, `STORAGE_SECRET_KEY=minioadmin` at it.
