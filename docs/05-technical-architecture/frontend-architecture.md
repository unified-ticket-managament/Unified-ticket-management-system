# Frontend Architecture

**`unified-frontend` is the only actively maintained frontend.** `ticketing-service/frontend` no longer exists on disk at all as of 2026-08-21 — even its last remnant, a stale pre-built `dist/` bundle with no `package.json`/`src/`, was deleted in the same commit that added client filters and the OTP classifier. The `ticketing-service/` directory is now empty.

## Two codebases in one Next.js app

```
unified-frontend/src/
├── app/                    Next.js App Router — the shell's own routes
├── components/, lib/,      Shell UI, state, API client, i18n, role-access config
│   store/, services/,
│   hooks/, types/
└── ticket-workspace/        Embedded copy of the ticket workspace, mounted as a
                              client-only react-router-dom subtree
```

### The shell (`src/app/`, `src/components/`, etc.)

Owns authentication, session, RBAC administration (Users/Roles/Permissions/Audit Logs/Permission Requests), Profile/Settings, and role-based routing for the whole product.

Route tree (App Router): `/login`, `/dashboard` (+ catch-all `/dashboard/[[...slug]]` for per-role landing dashboards), `/all-tickets`, `/all-tickets/:id`, `/my-tickets`, `/users`, `/roles`, `/roles/:id`, `/audit-logs`, `/permission-requests`, `/profile`, `/reports`, `/settings/reporting-managers`, `/settings/sla-timing-matrix`. The `(dashboard)/layout.tsx` group layout mounts the ticket workspace for any `/dashboard/*` slug beyond the bare root, avoiding remounts on slug change.

### The embedded ticket workspace (`src/ticket-workspace/`)

An adapted copy of the original standalone ticketing frontend, mounted via `TicketWorkspaceApp.tsx`'s own `<BrowserRouter basename="/dashboard">`. Uses a **separate** Axios client (`api/client.ts`, `NEXT_PUBLIC_TICKETING_API_URL`) from the shell's own (`src/lib/api.ts`, `NEXT_PUBLIC_API_URL`) — both point at the same backend process today, the split is a historical artifact of the pre-merge two-service world.

`src/ticket-workspace/context/AuthContext.tsx` is a thin adapter re-exposing the shell's own `useAuthStore` — the embedded copy holds no session state of its own.

### Design-token unification

`.tm-scope` (`src/app/globals.css`) remaps the workspace's own CSS variables onto the shell's computed dark-theme values, so both halves render as one consistent visual product.

## State management (`src/store/`)

| Store | Purpose |
|---|---|
| `auth-store.ts` | Current user + theme, Zustand + `persist` |
| `settings-store.ts` | Language, notifications, security prefs |
| `profile-extras-store.ts` | Client-only extras (legacy — most fields are now real backend columns, see [04-functional-modules](../04-functional-modules/README.md)) |
| `mock-tickets-store.ts` | Dev/demo mock ticket data, no persist |

## API client layers

- **Shell**: `src/lib/api.ts` (shared Axios instance) + `src/services/index.ts` (one file, all RBAC-domain service objects: `authService`, `userService`, `organizationService`, `reportingManagerService`, `roleService`, `categoryService`, `permissionService`, `permissionOverrideService`, `permissionRequestService`, `auditService`).
- **Ticket workspace**: `src/ticket-workspace/api/` — one file per domain (`ticket.ts`, `inbox.ts`, `mailFolder.ts`, `email.ts`, `sla.ts`, `interaction.ts`, `auditLog.ts`, `agent.ts`, `categories.ts`, `clients.ts`, `notifications.ts`, `rbacUsers.ts`, `rules.ts`).

## Role-based access (`src/lib/role-access.ts`)

The single source of truth for role-based UI behavior: `ROLE_NAMES`, `getVisibleNavItems`/`canSeeNavItem`, `SUPERVISOR_ROLE_NAMES`/`isSupervisorRole`, `getCreatableRoleNames`, `canManageRolePermissionsFor`. **Known drift, not yet reconciled**: this file's `SUPERVISOR_ROLE_NAMES` (`[SITE_LEAD, SUPER_ADMIN]` only) does not match the ticketing backend's actual `SUPERVISOR_ROLE_NAMES` (`{Team Lead, Account Manager, Site Lead, Super Admin}`) — three different "supervisor" definitions exist across the codebase (this file, the standalone-app's equivalent constant, and the real backend set) and none of them agree.

## Notification bell

Real (not mocked), backed by `GET /notifications`, `GET /notifications/stream` (SSE, replacing what used to be 30s polling), `POST /notifications/{id}/read`, `/read-all`. `resolveNotificationHref()` prefixes ticket-workspace-owned link paths with `/dashboard` since the backend writes links as if the workspace were mounted at the app root.

## Testing

**No test files or test framework configuration exist anywhere in `unified-frontend/`** — confirmed by an explicit search for `*.test.*`/`*.spec.*`/`__tests__` (only third-party `node_modules` internals matched). `npx tsc --noEmit` is the de facto correctness gate, since `npm run lint` is broken (Next.js 16 dropped `next lint`; the project still has an ESLint 8-style config).

## Known frontend-specific issues

See `unified-frontend/CLAUDE.md`'s own Known Issues section (partially reproduced in [14-troubleshooting](../14-troubleshooting/README.md)): Turbopack workspace-root/cache issues on directory rename or concurrent `build`+`dev`, the stale `:8001` ticketing-API default, unhandled 500s reading as CORS failures, and merge/pull silently discarding uncommitted work with no conflict marker.
