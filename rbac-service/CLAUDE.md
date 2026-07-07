# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Enterprise RBAC (Role-Based Access Control) User Management System — a FastAPI backend + Next.js frontend monorepo. Six roles manage users, roles, and permissions across a reporting hierarchy (`manager_id` / `teamlead_id` on each user): **Super Admin** (rank 5, all permissions) > **Site Lead** (rank 4, all permissions except `ticket:system_config`/`audit:export`) > **Account Manager** (rank 3, renamed in-place from "Manager" — same `role_id`, no orphaned data) > **Team Lead** (rank 2) > **Staff** (rank 1), plus **Viewer** which sits outside the rank ladder as a client-facing role with a small fixed permission set (`user:view`, `role:view`, `permission:view`). Site Lead and Viewer are both deliberately excluded from `organization_service.py`'s `ROLE_HIERARCHY`/`_build_subtree` (which only spans Super Admin → Account Manager → Team Lead → Staff) — Site Lead has unconditional visibility of everything rather than a place in the reporting tree.

- `backend/` — FastAPI + SQLAlchemy (async) + Alembic + PostgreSQL (Neon)
- `frontend/` — Next.js 16 (App Router) + TypeScript + Tailwind + Shadcn UI

## Commands

### Backend (run from `backend/`)

```bash
.venv\Scripts\activate                          # Windows venv (already created)
pip install -r requirements.txt
alembic upgrade head                            # apply migrations
python scripts/seed.py                          # idempotent demo data (roles, permissions, users) — see "Seeding" below, it also renames/cleans up, not just additive
uvicorn app.main:app --reload                   # dev server → http://127.0.0.1:8000, docs at /docs
alembic revision --autogenerate -m "message"    # new migration after model changes
```

There is no test suite — `pytest`/`pytest-asyncio` are in `requirements.txt` but no test files exist except `test_db.py` (a standalone manual DB-connectivity script, not a real test; do not treat it as a template for pytest tests). `backend/hash_password.py` is a similar one-off scratch script. Neither is imported by the app.

### Frontend (run from `frontend/`)

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # next build (output: standalone)
npm run start
npm run lint      # currently broken — see Known Issues below
npx tsc --noEmit  # use this to verify type correctness; treat as the real "lint" gate
```

## Architecture

### Backend: layered, but authorization stops at the frontend

Routes (`app/api/v1/`) → Services (`app/services/`) → Repositories (`app/repositories/`) → SQLAlchemy models. Two model sources are merged into one `Base.metadata`: `User` and `Role` come from an **external pip package** (`shared_models`, installed via git URL in `requirements.txt` — shared with a separate ticket-management service against the same database), while `Permission`, `RolePermission`, and `AuditLog` are local (`app/models/`). `backend/alembic/env.py` imports both sources and filters out the other service's tables via `include_object` so `alembic revision --autogenerate` only diffs this service's own tables.

**Every route only checks authentication (`Depends(get_current_active_user)`), never authorization.** There is no `require_permission`-style dependency anywhere in the backend — any authenticated user can call any endpoint (list all users, change any role's permissions, etc.) regardless of their role or permission set. All access control — permission-gated buttons, role-based page visibility, the Users page's reporting-hierarchy filtering — is enforced **only in the frontend**. Treat this as a known architectural constraint, not something to silently "fix" by adding backend checks unless asked.

Audit logging is defined (`AuditLogService`, `audit_logs` table, `GET /audit-logs`) but **nothing calls it** — no service creates an audit log entry when a user/role/permission changes, so the table is always empty in practice.

**Seeding is not purely additive** (`scripts/seed.py`): the main loop only ever *adds* a permission grant a role is missing per `DEFAULT_ROLES` — it never revokes one just because a role's default list changed. Two explicit cleanup lists run once near the top of `seed()`, before the main loop, to handle everything the additive loop can't: `DEPRECATED_PERMISSIONS` (permission names to delete outright, including their `role_permissions` grants — e.g. `ticket:bulk_reassign`, `ticket:configure_routing`) and `REVOKED_GRANTS` (specific `(role_name, permission_name)` pairs to un-grant without deleting the permission itself — e.g. Staff's `ticket:create`). When narrowing a role's permissions going forward, add the removal to one of these two lists — editing `DEFAULT_ROLES` alone will not revoke anything from a DB that already has the old grant. There's also a one-time in-place role rename block (`Role.name` mutated directly, same `role_id`, guarded so it only fires if the old name exists and the new one doesn't yet) — this is the safe pattern for renaming a role without orphaning users/grants, used for the "Manager" → "Account Manager" rename.

**Database URL normalization** (`app/core/config.py`, `Settings.normalize_database_url`) is important to understand before touching `DATABASE_URL` handling: it rewrites `postgres://`/`postgresql://` → `postgresql+asyncpg://`, translates `sslmode=` → `ssl=`, and strips `channel_binding=` — all required because Neon's connection strings use kwargs asyncpg doesn't accept. `alembic/env.py` does the reverse translation (`+asyncpg` stripped, `ssl=` → `sslmode=`) to get a psycopg2-compatible sync URL for migrations. Don't naive-string-replace this logic — use `urllib.parse`, per the existing implementation.

### Frontend: App Router + centralized role-access config

- `src/lib/role-access.ts` is the single source of truth for role-based UI behavior: `ROLE_NAMES` constants (`SUPER_ADMIN`, `SITE_LEAD`, `ACCOUNT_MANAGER`, `TEAM_LEAD`, `STAFF`, `VIEWER`), per-role sidebar visibility (`NAV_ITEMS_BY_ROLE`), `SUPERVISOR_ROLE_NAMES`, and which roles a given role is allowed to assign on user creation (`CREATABLE_ROLES_BY_ROLE`). New role-conditional UI logic should extend this file rather than hardcoding role-name strings in components.
- `src/app/(dashboard)/dashboard/[[...slug]]/page.tsx` is the dashboard's role router: Site Lead → `SiteLeadDashboard` (`components/dashboard/site-lead-dashboard.tsx`), Viewer/Super Admin → `ViewerDashboard`, everything else → `TicketWorkspaceApp`. `SiteLeadDashboard` is a distinct component (not a `ViewerDashboard` reskin) built around a "day-to-day" primary-actions section (Add User, Manage Roles & Permissions, View Audit Logs) plus full org stats — it deliberately uses plain hardcoded English strings instead of `useTranslation()`/`t()` to avoid touching all four i18n dictionaries.
- `src/components/auth/AuthGuard.tsx` gates the whole `(dashboard)` route group on `authService.me()` resolving; `PermissionGuard` conditionally renders based on `useAuthStore().hasPermission()`. Individual pages (e.g. Users) additionally self-gate with a role allowlist check that renders `AccessDenied` (403) for disallowed roles — this is a page-level pattern, not a route middleware, since `middleware.ts` only handles public/auth routing, not per-role authorization. Site Lead is treated as unrestricted like Super Admin in these checks (e.g. `user-detail-drawer.tsx`'s `isUnrestrictedActor`), not ownership-limited like Account Manager.
- Users page hierarchy filtering is entirely client-side: fetch all users (`page_size: 100`), then filter in-memory by `manager_id`/`teamlead_id` against the current user, since the backend has no server-side filtering for this and no row-level authorization (see above). Super Admin and Site Lead both see every user except other Super Admins.
- Permission editing lives in `src/components/users/user-detail-drawer.tsx` (a right-side `Sheet`), not a standalone page — there is no `/permissions` route. Opening a user's drawer edits **that user's role's** permission set (`PUT /roles/{role_id}/permissions`), not a per-user override; permissions are role-scoped everywhere in this system. An Account Manager editing permissions can only toggle permissions they personally hold (checked against their own `AuthUser.permissions`); Super Admin and Site Lead are unrestricted; Team Lead/Staff/Viewer can't reach this UI at all.
- i18n is a small custom system, not a library: `src/lib/i18n/translations.ts` (flat dictionary keyed by dotted strings, one object per language) + `src/hooks/use-translation.ts` (reads the active language from `useSettingsStore`, which persists via zustand). Adding a UI string requires adding the same key to every language dictionary — `Record<keyof typeof en, string>` on the non-English dictionaries enforces this at compile time.
- `src/components/shared/data-table.tsx` (`DataTable`/`DataTablePagination`) wraps `@tanstack/react-table` and is reused by both Users and Audit Logs; it supports an optional `onRowClick` for row-level navigation/drawers without needing per-page reimplementation.
- Zustand stores (`src/store/`) are the persistence layer for anything not backed by the API: `auth-store.ts` (current user + theme), `settings-store.ts` (language, notifications, security prefs, mock session list), `profile-extras-store.ts` (phone/address/avatar URL — fields with no backend column, stored client-side only and not synced across devices).
- Backend API base URL is `process.env.NEXT_PUBLIC_API_URL` (`src/lib/api.ts`), falling back to `http://localhost:8000/api/v1` for local dev. Being a `NEXT_PUBLIC_*` var, it's baked in at build time — changing it in a deployed environment requires a rebuild, not just a restart.

## Known Issues

- `npm run lint` is broken: Next.js 16 dropped `next lint`, but the project still has an old-format `.eslintrc.json` rather than an ESLint 9 flat config. Use `npx tsc --noEmit` to check for real errors instead.
- `docs/ARCHITECTURE.md`, `docs/API.md`, and `docs/DEPLOYMENT.md` describe an earlier/aspirational design that has drifted from the actual implementation (e.g. they document a `refresh_tokens` table, `require_permission()` backend enforcement, and extra `/users` query params like `role_id`/`is_active` — none of which exist in the current code). Don't treat `docs/` as authoritative; verify against the actual source.

## Deployment

Render.com deployment is set up via the root `render.yaml` (two Web Services: `rbac-backend`, `rbac-frontend`) against an external Neon database — see `DEPLOYMENT.md` at the repo root for the full runbook (Neon setup, the CORS/API-URL circular-dependency first-deploy sequence, seeding). Local dev and Render both read the same normalization logic; nothing else differs between environments.

## Work Completed So Far

The frontend has been substantially rebuilt on top of the original scaffold, feature by feature, always via the existing App Router / Zustand / React Query / Shadcn stack (no new state libraries or routing approach introduced):

- **Full UI pass** on Login (Clerk-style split layout, inline invalid-credential error, forgot-password toast), Dashboard, Users, Roles, Audit Logs, Settings, and Profile — Vercel/Linear-style aesthetic, Framer Motion used for page/drawer transitions only.
- **Role-based access control** end-to-end on the frontend: sidebar items, dashboard widgets, and Users-page row visibility all differ per role (Super Admin / Site Lead / Account Manager / Team Lead / Staff / Viewer), centralized in `lib/role-access.ts`. Staff/Viewer get a 403 `AccessDenied` page if they navigate to `/users` directly.
- **Users ↔ Permissions merge**: the standalone Permissions page was removed; permission management now happens in the User Details drawer (`user-detail-drawer.tsx`), opened by clicking a row. The drawer's Reporting Structure section is conditional on the *selected user's* role (Account Manager shows none, Team Lead shows only "Reporting Account Manager", Staff shows both). Account Managers can edit permissions but only toggle ones they personally hold (disabled checkbox + tooltip otherwise); Super Admin and Site Lead are unrestricted; Team Lead and below are read-only.
- **Site Lead role added + Manager renamed to Account Manager** (see role hierarchy in "Project Overview" above): a full role-hierarchy redesign implemented from an approved design doc — new `Site Lead` role/demo user/dashboard, in-place rename of `Manager` → `Account Manager` (same `role_id`, no orphaned users/grants), and a corrected permission matrix per role, applied via `scripts/seed.py`'s rename + cleanup-list mechanism (see "Seeding" above). Verified end-to-end: DB-level permission counts, live API login + `/auth/me` for all six demo accounts, `npx tsc --noEmit` clean, both dev servers booting and serving every route, and the ticketing-service's `AGENT_ROLE_NAMES`/`SUPERVISOR_ROLE_NAMES` gate (`ticketing-service/backend/app/services/access_control.py`) re-tested against the renamed/new role names.
- **Create User dialog** enforces the reporting hierarchy: who can be assigned as a user's role, manager, and team lead depends on the creating user's own role (`getCreatableRoleNames` in `role-access.ts`).
- **Organization Chart** got zoom controls (bottom-left, fixed regardless of pan/scroll/zoom — required moving the controls out of the scrollable container, not just CSS positioning).
- **i18n**: a from-scratch translation system (not a library) currently supporting English/Spanish/French/German, applied across nav, dashboard, users, roles, settings, and profile.
- **Render.com deployment prep**: `render.yaml`, `DEPLOYMENT.md`, and a fix to a stale `shared_models` git dependency URL.

Every change above (prior to the Site Lead/Account Manager rework) was verified by actually running both dev servers and driving the UI with Playwright (installed temporarily, removed after) across the five roles that existed at the time — not just type-checked. Two real bugs were caught and fixed this way (not just cosmetic): a Turbopack workspace-root misconfiguration that 404'd every route, and an invalid `<div>`-in-`<p>` DOM nesting in the permission drawer that was silently triggering Next.js's dev error overlay.
