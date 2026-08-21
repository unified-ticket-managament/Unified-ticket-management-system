# Technology Stack

Confirmed directly from `unified-backend/requirements.txt` and `unified-frontend/package.json` — real pinned versions, not approximations.

## Backend (`unified-backend/`)

| Layer | Technology | Version (pinned) |
|---|---|---|
| Web framework | FastAPI | 0.138.0 |
| ASGI server | Uvicorn (standard extras) | 0.49.0 |
| ASGI toolkit | Starlette | 1.3.1 |
| ORM | SQLAlchemy (async) | 2.0.51 |
| Async Postgres driver | asyncpg | 0.31.0 |
| Sync Postgres driver (Alembic) | psycopg2-binary | 2.9.12 |
| Migrations | Alembic | 1.18.4 |
| Validation/settings | Pydantic / pydantic-settings | 2.13.4 / 2.14.2 |
| Email validation | email-validator | 2.3.0 |
| Multipart forms | python-multipart | 0.0.32 |
| Env loading | python-dotenv | 1.2.2 |
| JWT | python-jose | 3.3.0 |
| Crypto backend | cryptography | 49.0.0 |
| Password hashing | passlib[bcrypt] / bcrypt | 1.7.4 / 4.0.1 |
| HTTP client | httpx | 0.28.1 |
| S3-compatible storage | boto3 | 1.43.39 |
| Microsoft Graph auth | msal | 1.37.0 (pinned specifically for `cryptography==49` compatibility) |
| HTML parsing (email bodies) | beautifulsoup4 | 4.15.0 |
| In-process scheduling | APScheduler | 3.11.3 |
| Structured logging | structlog | 24.4.0 |
| Testing | pytest / pytest-asyncio | 8.3.4 / 0.25.0 |
| Shared models | `shared_models` (local editable install, `-e ../shared_models`) | — |

## Frontend (`unified-frontend/`)

| Layer | Technology | Version |
|---|---|---|
| Framework | Next.js (App Router) | 16.2.9 |
| UI library | React / React DOM | 18 |
| Language | TypeScript | 5 |
| Data fetching/caching | @tanstack/react-query | 5.101.0 |
| Tables | @tanstack/react-table | 8.21.3 |
| Forms | react-hook-form + @hookform/resolvers | 7.80.0 / 5.4.0 |
| Schema validation | zod | 4.4.3 |
| State | zustand (+ persist middleware) | 5.0.14 |
| UI primitives | Radix UI (alert-dialog, avatar, checkbox, dialog, dropdown-menu, label, progress, scroll-area, select, separator, slot, switch, tabs, toast, tooltip) | various |
| Styling | Tailwind CSS (+ tailwindcss-animate, class-variance-authority, tailwind-merge, clsx) | 3.4.1 |
| Embedded-workspace routing | react-router-dom | 7.18.1 |
| HTTP client | axios | 1.18.0 |
| Rich text editor | @tiptap/react + extensions | — |
| Org chart rendering | d3-hierarchy, d3-selection, d3-transition, d3-zoom | — |
| Animation | framer-motion | 12.40.0 |
| Icons | lucide-react | — |

## Infrastructure

| Concern | Technology |
|---|---|
| Database | PostgreSQL, hosted on Neon |
| Object storage | Supabase Storage (default) or any S3-compatible endpoint |
| Local object storage (dev only) | MinIO, via `unified-backend/docker-compose.yml` |
| Hosting (Blueprint path) | Render.com — `render.yaml`, 2 web services |
| Hosting (confirmed-active CI/CD path) | EC2 + systemd, deployed via GitHub Actions SSH (`.github/workflows/deploy.yml`) |
| Mailbox integration | Microsoft Graph API (MSAL client-credentials auth) |

See [09-deployment](../09-deployment/README.md) for why two hosting paths coexist.
