# Dependencies

Key third-party packages and *why* they were chosen, beyond just "it's a web framework." Version numbers: see [technology-stack.md](technology-stack.md).

## Backend

| Package | Why this one specifically |
|---|---|
| `asyncpg` + SQLAlchemy async | The whole backend is async end-to-end (routes, services, repositories) — a sync driver would block the event loop under load. |
| `msal` (pinned to 1.37.0) | Explicitly pinned for compatibility with `cryptography==49.0.0` — a version constraint discovered and documented in `requirements.txt`'s own comments, not arbitrary. |
| `APScheduler` | Chosen specifically to **replace** an earlier GitHub-Actions-cron-triggered design for the SLA sweep — an explicit architectural decision, not the default choice. See [15-architecture-decisions/ADR-005-scheduler.md](../15-architecture-decisions/ADR-005-scheduler.md). |
| `beautifulsoup4` | HTML→plain-text conversion for inbound email bodies (Graph returns HTML; Timeline/notifications need plain text). |
| `boto3` | S3-compatible storage backend option, alongside Supabase's own client library. |
| `python-jose` | JWT encode/decode — the one library both `app.rbac` (issuer) and `app.ticketing` (verifier) share, ensuring identical token semantics. |
| `structlog` | Structured logging — used alongside stdlib `logging` (the latter configured once in `main.py` via `logging.basicConfig`). |
| `-e ../shared_models` | A local editable install, not a pinned git-URL dependency — a change to `shared_models/` is picked up immediately by the one process that imports it, with no separate publish/version-bump step. |

## Frontend

| Package | Why this one specifically |
|---|---|
| `@tanstack/react-query` | Server-state caching/dedup across the app — both the shell and the embedded ticket workspace use it, reducing redundant fetches (a documented, measured fix for several N+1-style frontend request patterns). |
| `zustand` | Lightweight client state (auth, settings) without Redux boilerplate; `persist` middleware backs localStorage-durable state. |
| `react-router-dom` (in a Next.js app) | Required specifically to run the embedded ticket workspace's copied page tree with minimal changes to its own internal routing — Next's App Router governs the shell, react-router governs the workspace subtree, bridged by a `RouterSync` component. |
| `zod` + `react-hook-form` | Schema-validated forms throughout — Zod schemas are rebuilt via `useMemo` when i18n is involved, since translated error messages depend on the active language. |
| `@tiptap/*` | Rich-text editing for Mail compose/reply — a real historical gotcha: added to `package.json` without `npm install` ever being re-run in one session, causing a confusing "Module not found" error that looked like a code bug rather than a missing install (see [14-troubleshooting](../14-troubleshooting/README.md)). |
| `d3-*` (hierarchy/selection/transition/zoom) | Powers the dynamic Organization Chart's rendering, panning, and zoom — not a general charting library used elsewhere. |
| `framer-motion` | Page/drawer transitions only — a deliberate, narrow usage scope (not a general animation framework used throughout). |

## Why two Axios instances exist in one frontend app

`src/lib/api.ts` (shell) and `src/ticket-workspace/api/client.ts` (embedded workspace) are separate Axios instances pointed at two different `NEXT_PUBLIC_*` base URLs — both of which resolve to the *same* backend process today. This is a direct, unremoved artifact of the pre-consolidation two-service architecture, not a deliberate current-state design choice — see [15-architecture-decisions](../15-architecture-decisions/README.md).
