# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

This is a monorepo formed by merging three previously-independent git repos via `git subtree` (full history preserved — `git log --follow` works across the merge point):

- `rbac-service/` — the **shell application**. Owns authentication, session, roles/permissions/users, and role-based routing/navigation for the whole product. Next.js 16 frontend + FastAPI backend. Has its own `CLAUDE.md` — read it before working in this directory.
- `ticketing-service/` — the **ticket management product**, owned as an independently-deployable service (its own FastAPI backend, its own Postgres tables) but with its frontend **also embedded** inside `rbac-service`'s Next.js app (see below). Has its own `CLAUDE.md`.
- `shared_models/` — the one real copy of the `User`/`Role` SQLAlchemy models both backends import (as a local editable install, not a git-URL pip dependency). Never edit these models from either service's own repo copy — there isn't one; both `requirements.txt` files point at this directory.

Both backends share **one physical Postgres database** (Neon) but keep independent Alembic migration histories — `rbac-service` owns `users`/`roles`/`permissions`/`audit_logs`/`user_permission_overrides`, `ticketing-service` owns `tickets`/`interactions`/`attachments`/`ticket_audit_logs`/`ticket_edit_access_requests`. Each service's `alembic/env.py` filters out the other service's tables via `include_object` so `alembic revision --autogenerate` only ever diffs its own tables. Never generate a migration in one service that touches the other's tables.

## Cross-service identity: RBAC issues, Ticketing verifies

`rbac-service`'s backend is the **sole issuer** of JWT access/refresh tokens (HS256). `ticketing-service`'s backend is a **verify-only consumer** — it decodes and validates tokens against the same shared `JWT_SECRET_KEY`, then re-resolves the user from the shared `users` table on every request; it has no login/signup/refresh endpoint of its own and no `create_token`-shaped function anywhere in its code. The two services' `.env` files must have byte-identical `JWT_SECRET_KEY` values, or every request to `ticketing-service` 401s as an invalid token. See `ticketing-service/CLAUDE.md`'s "Access control" section for the exact dependency chain (`get_current_user`/`get_current_agent`, `AGENT_ROLE_NAMES`/`SUPERVISOR_ROLE_NAMES`).

**The access token also carries a `permissions` claim** — `rbac-service`'s `create_access_token` embeds the caller's full effective permission list (role defaults ∪ active personal overrides, computed by `PermissionResolverService`) at login/refresh time. `ticketing-service` threads this onto the resolved `User` as a transient, non-persisted attribute in `dependencies/auth.py` (same pattern as `TicketService._attach_names`) and reads it via `access_control.has_permission`/`ensure_has_permission` — a decode-only check, never a fresh call back to RBAC. This is how fine-grained (not just role-name) authorization crosses the service boundary — see `rbac-service/CLAUDE.md`'s "Per-user permission overrides" section for how the claim is computed and granted per-user, and `ticketing-service/CLAUDE.md`'s "Permission-based enforcement" section for how it's consumed. A stale or absent claim degrades to an empty list rather than crashing, so a token issued before this claim existed still decodes safely — and revoking a permission doesn't invalidate a token already issued, only affects the next login/refresh.

## The ticket workspace exists in two places

`ticketing-service/frontend` is a real, independently-runnable Vite/React app with its own login flow. Its entire page tree was **also copied** (not just linked) into `rbac-service/frontend/src/ticket-workspace/` and mounted inside RBAC's own Next.js app via `react-router-dom`, so that Staff/Team Lead/Manager get one seamless product after logging into RBAC, instead of being bounced to a separately-hosted app. See `rbac-service/CLAUDE.md`'s "Ticket workspace embedding" section for the exact mounting mechanism, routing rules (which roles land where), and the design-token unification that makes the embedded copy visually match RBAC's own pages.

**These two copies do not stay in sync automatically.** A change to a ticket page, component, or API wrapper generally needs to be made in both `ticketing-service/frontend/src/...` and `rbac-service/frontend/src/ticket-workspace/...` (same relative paths; the embedded copy imports via the `@tw/*` alias instead of `@/*`) if it should be visible in both the standalone app and the embedded experience. Check which one(s) are actually reachable/deployed before assuming a one-sided change is sufficient.

## Local development

Three processes for full end-to-end testing (RBAC backend, Ticketing backend, RBAC frontend — the standalone Ticketing frontend is a fourth, optional one only needed if testing that app directly rather than the embedded copy):

```bash
cd rbac-service/backend && uvicorn app.main:app --reload            # :8000
cd ticketing-service/backend && uvicorn app.main:app --reload --port 8001
cd rbac-service/frontend && npm run dev                             # :3000, embeds the ticket workspace
```

Both backends require `JWT_SECRET_KEY`/`JWT_ALGORITHM` in their `.env` (identical values), and both cache their `Settings` via `@lru_cache` — editing `.env` while a backend is already running has no effect until it's restarted (`--reload` only reacts to Python file changes). See each service's own `CLAUDE.md` and `ticketing-service`'s `run` skill for the full prerequisite/verification checklist.

## Deployment

Render.com, one Web Service per backend/frontend pair per service (see `rbac-service/render.yaml`; `ticketing-service`'s Render services are dashboard-configured, no `render.yaml` in this repo yet). Rotating `JWT_SECRET_KEY` in production is a real, disruptive step — every currently-issued token on both services becomes invalid immediately, forcing a global logout. Schedule it deliberately; don't treat it as a routine env var change.
