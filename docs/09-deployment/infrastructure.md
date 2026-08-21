# Infrastructure

## Managed services (shared across whichever deployment path is live)

| Service | Provider | Purpose |
|---|---|---|
| PostgreSQL | Neon | The one shared database, both Alembic chains |
| Object storage | Supabase Storage (default) or S3-compatible | Attachment files |
| Mailbox | Microsoft Graph (Entra ID app registration) | Optional inbound/outbound email |
| Outbound SMTP | Any SMTP provider (optional) | Business-critical notification emails |

## Local-only infrastructure

`unified-backend/docker-compose.yml` defines exactly 2 services — **no application containers, no Postgres container**:
- `minio` (image `minio/minio`) — S3-compatible object storage for local dev, ports 9000 (API)/9001 (console), credentials `minioadmin`/`minioadmin`.
- `minio-init` (image `minio/mc`) — provisions the `communication-attachments` bucket on startup, depends on `minio`'s healthcheck.

The backend and frontend processes themselves are run directly (`uvicorn`, `npm run dev`/`next start`), not containerized, in every path this documentation pass could confirm.

## Render (Path B)

Two free-tier web services, `render.yaml`:

| Service | Runtime | Root dir | Build | Start |
|---|---|---|---|---|
| `unified-backend` | Python 3.12.5 | `unified-backend` | `pip install -r requirements.txt` | `bash scripts/start.sh` |
| `unified-frontend` | Node 20.18.0 | `unified-frontend` | `npm ci && npm run build` | `npm run start` |

No `region:` is set for either — defaults to Render's Oregon region, a cross-region hop from Neon's `us-east-1` (an acknowledged-but-unfixed detail per `unified-frontend/CLAUDE.md`'s performance notes). Free-tier services spin down after 15 minutes of inactivity — first request after idle can take 30-60s.

## EC2 (Path A — the one confirmed to actually fire on every push)

`.github/workflows/deploy.yml` SSHs (via `appleboy/ssh-action@v1.2.0`, using `EC2_HOST`/`EC2_USER`/`EC2_SSH_PRIVATE_KEY` GitHub secrets) into a host running the app under **systemd** as two services (`unified-backend`, `unified-frontend`), with the repo checked out at `/opt/utms`. No containerization here either — plain `systemctl restart`.

## What's NOT confirmed

- Which EC2 instance type/size, OS, or region is in use.
- Whether the EC2 host has its own reverse proxy (nginx, etc.) in front of the two systemd services, or whether they're directly internet-facing.
- Whether monitoring/alerting infrastructure (CloudWatch, Render's own dashboards, or a third party) is wired to either path.

See [10-operations](../10-operations/README.md) for what to check operationally given this ambiguity.
