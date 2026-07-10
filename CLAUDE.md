# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

This is a monorepo formed by merging three previously-independent git repos via `git subtree` (full history preserved — `git log --follow` works across the merge point), **plus a later backend unification** (see the callout immediately below — read it before trusting any `rbac-service/backend/...` or `ticketing-service/backend/...` path anywhere else in this file or either sub-`CLAUDE.md`):

- `unified-backend/` — **the real, running backend for both domains**, one FastAPI process. `app/rbac/` (routes/services/repositories/models for auth, users, roles, permissions, permission overrides, permission requests) and `app/ticketing/` (routes/services/repositories/models for tickets, interactions, attachments, clients, mail) are both subpackages of this **one** app — see "Backend unification" below.
- `rbac-service/` — the **shell frontend application** (Next.js 16). Owns authentication, session, roles/permissions/users UI, and role-based routing/navigation for the whole product. `rbac-service/backend/` still physically exists but is now an **empty shell** (only `__pycache__` under `app/`) — do not edit or run it; it is not deployed and nothing imports it. Has its own `CLAUDE.md` — read it before working in this directory.
- `ticketing-service/` — the **ticket management product frontend** (Vite/React), independently runnable, with its page tree **also embedded** inside `rbac-service`'s Next.js app (see below). `ticketing-service/backend/` is likewise now an empty shell for the same reason as above — its real code lives in `unified-backend/app/ticketing/`. Has its own `CLAUDE.md`.
- `shared_models/` — the one real copy of the `User`/`Role` SQLAlchemy models `unified-backend` imports (as a local editable install, not a git-URL pip dependency). Never edit these models from anywhere else — there isn't another copy.

Both domains share **one physical Postgres database** (Neon) but keep independent Alembic migration histories — `unified-backend/alembic_rbac/` owns `users`/`roles`/`permissions`/`audit_logs`/`user_permission_overrides`/`permission_requests`, `unified-backend/alembic_ticketing/` owns `tickets`/`interactions`/`attachments`/`ticket_audit_logs`/`ticket_edit_access_requests`. Each chain's own `env.py` filters out the other domain's tables via `include_object` so `alembic revision --autogenerate` only ever diffs its own tables. Never generate a migration in one chain that touches the other's tables — this is enforced by convention, not by anything structural, since both chains now run against the exact same database from the exact same process.

## Backend unification

The two backends (`rbac-service/backend` and `ticketing-service/backend`) were merged into **one process, `unified-backend/`**, at some point after the original two-service split described in the rest of this document was written — most of the narrative below (JWT issuer/verifier language, "service boundary", "the two services' `.env` files") was written when they were genuinely separate OS processes and is now a **conceptual** description of a module boundary (`app.rbac` vs. `app.ticketing`), not a network/process one. Concretely:

- **One `.env`, one port.** `unified-backend/.env` (`DATABASE_URL`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, storage vars — the union of both old `.env` files) and one `uvicorn` process, started via `unified-backend/scripts/start.sh` (runs both Alembic chains — `alembic_rbac` then `alembic_ticketing` — then `uvicorn app.main:app`). See "Local development" below for the exact commands.
- **RBAC routes are prefixed `/api/v1`, ticketing routes are not.** `unified-backend/app/main.py` mounts `rbac_api_router` under `/api/v1` but every `ticketing_*_router` (tickets, inbox, interactions, attachments, clients, ...) at the process root — `GET /tickets`, not `GET /api/v1/tickets`. Both frontends' env vars reflect this split base path (see the "stale port" Known Issue in `rbac-service/CLAUDE.md`, which is exactly this distinction tripping up an env var default).
- **`app.auth.jwt.create_access_token` is only ever called from `app.rbac.services.auth_service`** — a convention preserved from the two-process days (see "Cross-service identity" below), not something the module system enforces now that both halves are one importable codebase. Don't add a second call site under `app.ticketing`.
- **Both Alembic chains still run against the same DB independently on purpose** (see render.yaml's own comments) — they coexist safely via two distinct `alembic_version`-equivalent tracking tables and disjoint table ownership; merging them into one chain was deliberately not done.
- render.yaml already documents this merge in detail (see its top-of-file comment and the `unified-backend` service block) — treat it as the more current source if this section and render.yaml ever disagree.

## Cross-service identity: RBAC issues, Ticketing verifies

This section describes a **conceptual** boundary that survived the process merge above — read "service" below as "module" (`app.rbac` vs. `app.ticketing`), not "separate deployable."

RBAC's own code (`app.rbac.services.auth_service`) is the **sole issuer** of JWT access/refresh tokens (HS256). Ticketing's own code (`app.ticketing`) is a **verify-only consumer** — it decodes and validates tokens against the same `JWT_SECRET_KEY` (now literally the same `settings.jwt_secret_key`, read once by the one process), then re-resolves the user from the shared `users` table on every request; it has no login/signup/refresh endpoint of its own and no `create_token`-shaped function anywhere in its code. Before the merge this required byte-identical `JWT_SECRET_KEY` values across two `.env` files; now there is only one `.env` to get right. See `ticketing-service/CLAUDE.md`'s "Access control" section for the exact dependency chain (`get_current_user`/`get_current_agent`, `AGENT_ROLE_NAMES`/`SUPERVISOR_ROLE_NAMES`).

**The access token also carries a `permissions` claim, plus a separate `scoped_permissions` claim.** `app.rbac`'s `create_access_token` embeds the caller's full effective permission list (role defaults ∪ active *unscoped* personal overrides, computed by `PermissionResolverService`) at login/refresh time as `permissions`, and any *ticket-scoped* overrides (e.g. `ticket:editother_ticket` granted for one specific ticket only — see `rbac-service/CLAUDE.md`'s "Permission requests" section) separately as `scoped_permissions: dict[str, list[str]]` (permission name → ticket ids). `app.ticketing`'s `dependencies/auth.py` threads both onto the resolved `User` as transient, non-persisted attributes (same pattern as `TicketService._attach_names`) and reads them via `access_control.has_permission`/`has_permission_for_ticket`/`ensure_has_permission` — a decode-only check, never a fresh call back into `app.rbac`. This is how fine-grained (not just role-name) authorization crosses the module boundary — see `rbac-service/CLAUDE.md`'s "Per-user permission overrides" section for how both claims are computed and granted, and `ticketing-service/CLAUDE.md`'s "Permission-based enforcement" section for how they're consumed. A stale or absent claim degrades to an empty list/dict rather than crashing, so a token issued before either claim existed still decodes safely — and granting or revoking a permission doesn't affect a token already issued, only the next login/refresh.

## The ticket workspace exists in two places

`ticketing-service/frontend` is a real, independently-runnable Vite/React app with its own login flow. Its entire page tree was **also copied** (not just linked) into `rbac-service/frontend/src/ticket-workspace/` and mounted inside RBAC's own Next.js app via `react-router-dom`, so that Staff/Team Lead/Manager get one seamless product after logging into RBAC, instead of being bounced to a separately-hosted app. See `rbac-service/CLAUDE.md`'s "Ticket workspace embedding" section for the exact mounting mechanism, routing rules (which roles land where), and the design-token unification that makes the embedded copy visually match RBAC's own pages.

**These two copies do not stay in sync automatically.** A change to a ticket page, component, or API wrapper generally needs to be made in both `ticketing-service/frontend/src/...` and `rbac-service/frontend/src/ticket-workspace/...` (same relative paths; the embedded copy imports via the `@tw/*` alias instead of `@/*`) if it should be visible in both the standalone app and the embedded experience. Check which one(s) are actually reachable/deployed before assuming a one-sided change is sufficient.

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
