# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

This is a monorepo formed by merging three previously-independent git repos via `git subtree` (full history preserved — `git log --follow` works across the merge point), **plus a later backend unification** (see the callout immediately below — read it before trusting any `rbac-service/backend/...` or `ticketing-service/backend/...` path anywhere else in this file or either sub-`CLAUDE.md`):

- `rbac-service/` — the **shell application**. Owns authentication, session, roles/permissions/users, and role-based routing/navigation for the whole product. Next.js 16 frontend + (see "Backend consolidation" below for where its backend actually lives now). Has its own `CLAUDE.md` — read it before working in this directory.
- `ticketing-service/` — the **ticket management product** — a standalone, independently-runnable Vite/React frontend with its own login flow (docs/history describe a once-independent backend too; see "Backend consolidation" below for why that's no longer accurate). Its frontend is **also embedded** inside `rbac-service`'s Next.js app (see below). Has its own `CLAUDE.md`, though its backend-architecture sections now describe history, not the current runtime.
- `shared_models/` — the one real copy of the `User`/`Role` SQLAlchemy models the backend imports (as a local editable install, not a git-URL pip dependency). Never edit these models from a service's own repo copy — there isn't one.
- `unified-backend/` — **the actual, currently-running backend for everything** (see below). Has no `CLAUDE.md` of its own yet; this file and each service's `CLAUDE.md` cover it.

## Backend consolidation: one FastAPI app, not two

`rbac-service/backend/` and `ticketing-service/backend/` **no longer exist as separate running services** — they were merged into a single `unified-backend/` FastAPI app (`unified-backend/app/main.py`), discovered mid-session when `ticketing-service`'s old port-8001 process turned out to have never existed post-merge and every "network error" traced back to the frontend still pointing at it. Both services' own `CLAUDE.md` "Commands"/local-dev sections have since been corrected to point at `unified-backend/` — if you ever see one describing a standalone `backend/` directory or a separate port again, that's drift to fix, not the current state; the ticket-workspace/RBAC frontend-side documentation in both files was already accurate and untouched.

Layout: `unified-backend/app/rbac/` (former `rbac-service/backend/app/`) and `unified-backend/app/ticketing/` (former `ticketing-service/backend/app/`) are mounted in the same `FastAPI()` instance — RBAC's routers under `/api/v1` exactly as before, Ticketing's routers unprefixed exactly as before (see `app/main.py`'s router-mounting comment) — so **every existing route path is byte-identical to the two standalone services**, just served from one process on one port (`:8000` by default) instead of two. `app/notifications/` is a third, newer module living alongside them (see `rbac-service/CLAUDE.md` if a notifications feature needs touching). Two independent Alembic histories are preserved as `alembic_rbac/` and `alembic_ticketing/` (own `versions/` dirs, own `include_object` filtering) — `unified-backend/scripts/rbac_seed/` and `scripts/ticketing_seed/` are the corresponding seed scripts, run via `alembic -c alembic_rbac/alembic.ini upgrade head` / `alembic -c alembic_ticketing/alembic.ini upgrade head` (order matters only against a genuinely empty DB, since ticketing's tables FK into rbac's `users`). One physical Postgres database (Neon) throughout, same as before the merge.

`unified-backend/.env` is the one env file both halves read from — `JWT_SECRET_KEY`/`JWT_ALGORITHM` no longer need to match across two files since there's only one now, but the RBAC-issues/Ticketing-verifies token *architecture* described below is otherwise unchanged (it's just enforced within one process instead of across two).

## Cross-service identity: RBAC issues, Ticketing verifies

This section describes a **conceptual** boundary that survived the process merge above — read "service" below as "module" (`app.rbac` vs. `app.ticketing`), not "separate deployable."

RBAC's own code (`app.rbac.services.auth_service`) is the **sole issuer** of JWT access/refresh tokens (HS256). Ticketing's own code (`app.ticketing`) is a **verify-only consumer** — it decodes and validates tokens against the same `JWT_SECRET_KEY` (now literally the same `settings.jwt_secret_key`, read once by the one process), then re-resolves the user from the shared `users` table on every request; it has no login/signup/refresh endpoint of its own and no `create_token`-shaped function anywhere in its code. Before the merge this required byte-identical `JWT_SECRET_KEY` values across two `.env` files; now there is only one `.env` to get right. See `ticketing-service/CLAUDE.md`'s "Access control" section for the exact dependency chain (`get_current_user`/`get_current_agent`, `AGENT_ROLE_NAMES`/`SUPERVISOR_ROLE_NAMES`).

**The access token also carries a `permissions` claim, plus a separate `scoped_permissions` claim.** `app.rbac`'s `create_access_token` embeds the caller's full effective permission list (role defaults ∪ active *unscoped* personal overrides, computed by `PermissionResolverService`) at login/refresh time as `permissions`, and any *ticket-scoped* overrides (e.g. `ticket:editother_ticket` granted for one specific ticket only — see `rbac-service/CLAUDE.md`'s "Permission requests" section) separately as `scoped_permissions: dict[str, list[str]]` (permission name → ticket ids). `app.ticketing`'s `dependencies/auth.py` threads both onto the resolved `User` as transient, non-persisted attributes (same pattern as `TicketService._attach_names`) and reads them via `access_control.has_permission`/`has_permission_for_ticket`/`ensure_has_permission` — a decode-only check, never a fresh call back into `app.rbac`. This is how fine-grained (not just role-name) authorization crosses the module boundary — see `rbac-service/CLAUDE.md`'s "Per-user permission overrides" section for how both claims are computed and granted, and `ticketing-service/CLAUDE.md`'s "Permission-based enforcement" section for how they're consumed. A stale or absent claim degrades to an empty list/dict rather than crashing, so a token issued before either claim existed still decodes safely — and granting or revoking a permission doesn't affect a token already issued, only the next login/refresh.

## The ticket workspace exists in two places

`ticketing-service/frontend` is a real, independently-runnable Vite/React app with its own login flow. Its entire page tree was **also copied** (not just linked) into `rbac-service/frontend/src/ticket-workspace/` and mounted inside RBAC's own Next.js app via `react-router-dom`, so that Staff/Team Lead/Manager get one seamless product after logging into RBAC, instead of being bounced to a separately-hosted app. See `rbac-service/CLAUDE.md`'s "Ticket workspace embedding" section for the exact mounting mechanism, routing rules (which roles land where), and the design-token unification that makes the embedded copy visually match RBAC's own pages.

**These two copies do not stay in sync automatically.** A change to a ticket page, component, or API wrapper generally needs to be made in both `ticketing-service/frontend/src/...` and `rbac-service/frontend/src/ticket-workspace/...` (same relative paths; the embedded copy imports via the `@tw/*` alias instead of `@/*`) if it should be visible in both the standalone app and the embedded experience. Check which one(s) are actually reachable/deployed before assuming a one-sided change is sufficient.

<<<<<<< Updated upstream
Both copies now call the **same** `unified-backend` process (see "Backend unification" below), just via different base-URL env vars — `ticketing-service/frontend`'s own `VITE_API_BASE_URL` and `rbac-service/frontend`'s `NEXT_PUBLIC_TICKETING_API_URL` should both point at the unified backend's root (no `/api/v1`) once it's running on one port instead of two.

## Local development

Two processes for full end-to-end testing (one unified backend, RBAC frontend — the standalone Ticketing frontend is a third, optional one only needed if testing that app directly rather than the embedded copy):

```bash
cd unified-backend && bash scripts/start.sh     # :8000 — runs both Alembic chains, then uvicorn
cd rbac-service/frontend && npm run dev         # :3000, embeds the ticket workspace
```

`scripts/start.sh` assumes `unified-backend/.env` already exists (`DATABASE_URL`, `ALEMBIC_DATABASE_URL`, `JWT_SECRET_KEY`/`JWT_ALGORITHM`, storage vars — see `unified-backend/app/core/config.py`'s `Settings` for the full field list). If you'd rather run the pieces individually: `alembic -c alembic_rbac/alembic.ini upgrade head`, `alembic -c alembic_ticketing/alembic.ini upgrade head`, then `uvicorn app.main:app --reload --port 8000`, all from `unified-backend/`. `Settings` is cached via `@lru_cache` — editing `.env` while the backend is already running has no effect until it's restarted (`--reload` only reacts to Python file changes).

**Both frontends need their ticketing-API base URL pointed at the unified backend's root (no `/api/v1`), not a separate `:8001`.** `rbac-service/frontend`'s embedded ticket workspace defaults `NEXT_PUBLIC_TICKETING_API_URL` to the old standalone-ticketing-service port (`http://localhost:8001`) if unset — since that port no longer has anything listening on it post-merge, this silently network-errors every ticketing-domain request while RBAC-native requests keep working. Set `NEXT_PUBLIC_TICKETING_API_URL=http://localhost:8000` in `rbac-service/frontend/.env.local` (restart `npm run dev` after — `NEXT_PUBLIC_*` vars are baked in at server start). See `rbac-service/CLAUDE.md`'s matching Known Issues entry.

See each frontend's own `CLAUDE.md` and `ticketing-service`'s `run` skill for the full prerequisite/verification checklist (the skill still describes the old two-backend shape in places — mentally translate `backend/` paths to `unified-backend/app/ticketing/` per "Backend unification" above).

## Deployment

Render.com, via the root `render.yaml`: one Web Service for `unified-backend`, one for `rbac-frontend`, one static site for `ticketing-frontend` — see that file's own top-of-file comment for the full merged-deployment rationale and `DEPLOYMENT.md` for the runbook (Neon setup, the CORS/API-URL circular-dependency first-deploy sequence, seeding). Rotating `JWT_SECRET_KEY` in production is a real, disruptive step — every currently-issued token becomes invalid immediately, forcing a global logout. Schedule it deliberately; don't treat it as a routine env var change.
=======
**The gap between the two copies has widened, not narrowed.** A Mail-page rebuild (two-panel layout, redesigned Message Details, a real auto-saving Draft feature — see `rbac-service/CLAUDE.md`'s "Mail v2" section) was implemented **only** in the embedded copy, since the standalone `ticketing-service/frontend` app wasn't the one being tested/iterated on. The standalone app's own Mail/Inbox page still reflects the older design documented in `ticketing-service/CLAUDE.md`. Don't assume the two `CLAUDE.md`s' Mail-related sections describe the same UI anymore — they don't, and reconciling them (porting the newer design back to the standalone app) hasn't been done.

## Local development

Two processes for full end-to-end testing (the unified backend, and the RBAC frontend that embeds the ticket workspace — the standalone Ticketing frontend is a third, optional one only needed if testing that app directly rather than the embedded copy):

```bash
cd unified-backend && uvicorn app.main:app --reload                 # :8000 — serves both /api/v1/* (RBAC) and unprefixed ticketing routes
cd rbac-service/frontend && npm run dev                             # :3000, embeds the ticket workspace
```

(`unified-backend/scripts/rbac_seed/start.sh` runs both Alembic upgrades then starts uvicorn, if you want the one-liner.) The backend caches its `Settings` via `@lru_cache` — editing `.env` while it's already running has no effect until it's restarted (`--reload` only reacts to Python file changes, not `.env` edits, and has been unreliable enough on Windows in this repo that a full process kill + restart is the trustworthy fix when a change "isn't taking effect"). See `rbac-service/CLAUDE.md` and `ticketing-service/CLAUDE.md` for frontend-side prerequisites — both files' backend "Commands" sections already point at `unified-backend/` (see "Backend consolidation" above).

## Deployment

Render.com, via the single root-level `render.yaml` (not `rbac-service/render.yaml` — that path is stale): one `unified-backend` Web Service (rootDir `unified-backend`) plus separate `rbac-frontend` and `ticketing-frontend` Web Services, matching the post-merge one-backend/two-frontends topology described above. Rotating `JWT_SECRET_KEY` in production is a real, disruptive step — every currently-issued token becomes invalid immediately, forcing a global logout. Schedule it deliberately; don't treat it as a routine env var change.
>>>>>>> Stashed changes
