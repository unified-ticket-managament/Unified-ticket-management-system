# Prerequisites

| Requirement | Version | Why |
|---|---|---|
| Python | 3.12+ (3.12.5 confirmed used in production per `render.yaml`) | Backend runtime |
| Node.js | 20+ (20.18.0 confirmed used in production) | Frontend runtime |
| npm | Bundled with Node | Frontend package management |
| A PostgreSQL database | Any version compatible with the pinned `asyncpg`/`psycopg2` versions | A free [Neon](https://neon.tech) project is what this project actually uses — you need **both** an async (asyncpg) and a sync (psycopg2) connection string to the same database |
| Git Bash / WSL / macOS / Linux shell | — | `scripts/start.sh` is a bash script; on native Windows PowerShell, run its three commands individually instead (see [backend-setup.md](backend-setup.md)) |

## Optional, but needed for full functionality

| Requirement | Needed for |
|---|---|
| A Supabase project (or any S3-compatible endpoint) | Real attachment upload/download — without it, `StorageConfigurationError` will surface as a clean 503 on any attachment action |
| A Microsoft Entra ID (Azure AD) app registration | Real Graph mailbox integration — without it, the system falls back to a mock mail provider automatically, no error |
| Docker (for MinIO) | `unified-backend/docker-compose.yml` provisions a local S3-compatible bucket if you don't want to use real Supabase/S3 for local dev |

## What you do NOT need

- Docker for the backend or frontend themselves — neither is containerized in any confirmed deployment path; `docker-compose.yml` is MinIO-only.
- A local Postgres install — this project targets Neon (or any real Postgres) even in local dev; no `docker-compose` Postgres service exists.
- SMTP credentials — outbound email safely degrades to logging-only if unset.
