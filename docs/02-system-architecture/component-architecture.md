# Component Architecture

## Backend components (`unified-backend/app/`)

```mermaid
flowchart TB
    subgraph Backend["unified-backend (one FastAPI process)"]
        MAIN[main.py — app assembly, CORS, lifespan, routers]
        subgraph RBAC["app/rbac/ — mounted at /api/v1"]
            RAPI[api/v1/*.py] --> RSVC[services/*.py] --> RREPO[repositories/*.py]
        end
        subgraph TICKETING["app/ticketing/ — mounted unprefixed"]
            TAPI[api/*.py] --> TSVC[services/*.py] --> TREPO[repositories/*.py]
        end
        subgraph NOTIF["app/notifications/ — shared"]
            NROUTES[routes.py] --> NSVC[service.py] --> NSSE[sse_manager.py]
            NSVC --> NEMAIL[email_notifier.py]
        end
        subgraph CORE["app/core/ — cross-cutting"]
            CFG[config.py — Settings]
            CACHE[rbac_cache.py — TTL/LRU session cache]
            SCHED[sla_scheduler.py — APScheduler]
            EMAILSEND[email_sender.py — SMTP transport]
        end
        subgraph DEPS["app/dependencies/auth.py — shared by both domains"]
            AUTHDEP[get_current_user / get_current_agent / get_current_user_sse]
        end
        MODELS[(shared_models — User/Role/Category)]
    end
    RSVC --> MODELS
    TSVC --> MODELS
    RSVC --> NSVC
    TSVC --> NSVC
    AUTHDEP --> CACHE
    TAPI --> AUTHDEP
    RAPI -.->|get_current_active_user, same underlying dependency| AUTHDEP
```

### `app/rbac/` — Users, Roles, Permissions, Audit, Organization

Layers: `api/v1/` (routes) → `services/` (business logic + authorization) → `repositories/` (data access) → SQLAlchemy models (`User`/`Role`/`Category` from `shared_models`; `Permission`, `RolePermission`, `AuditLog`, `UserPermissionOverride`, `PermissionRequest`, `ReportingManagerTeam` local to this module). See [05-technical-architecture/backend-architecture.md](../05-technical-architecture/backend-architecture.md).

### `app/ticketing/` — Tickets, Mail, SLA, Escalation

The larger of the two domains: 13 API router files, 30 service files, 16 repository files, 17 model files. Owns the entire client-communication-to-resolved-ticket lifecycle, SLA/escalation clocks, Microsoft Graph mail integration, and the Mail/OTP rule engine. See [04-functional-modules](../04-functional-modules/README.md) for a module-by-module breakdown.

### `app/notifications/` — shared, cross-cutting

The single write path (`NotificationService.notify()`) every trigger in both domains calls through. Fans out to: a DB row, an SSE push (`sse_manager.py`, in-memory per-process pub/sub), and — for a fixed allowlist of business-critical types — a real outbound email (`email_notifier.py`, fire-and-forget background task).

### `app/core/` — configuration, caching, scheduling

`config.py`'s `Settings` (pydantic-settings, `@lru_cache`d) is the one place every environment variable is declared and typed. `rbac_cache.py` is the session-identity cache described above. `sla_scheduler.py` wires an in-process `AsyncIOScheduler` job into the FastAPI `lifespan` hook — the SLA sweep's actual production trigger.

## Frontend components (`unified-frontend/src/`)

```mermaid
flowchart TB
    subgraph Shell["unified-frontend shell (Next.js App Router)"]
        APP[app/ — routes: login, dashboard, users, roles,\naudit-logs, permission-requests, profile, reports, settings/*]
        AUTHG[components/auth/AuthGuard.tsx]
        LAYOUT[components/layout/ — Sidebar, Topbar, DashboardLayout]
        STORE[store/ — auth-store, settings-store, profile-extras-store]
        SVC[services/ — RBAC API client layer]
        ROLEACC[lib/role-access.ts — single source of truth\nfor role-based nav/visibility]
    end
    subgraph TW["src/ticket-workspace/ — embedded, mounted via react-router-dom"]
        TWAPP[TicketWorkspaceApp.tsx — BrowserRouter basename=/dashboard]
        TWPAGES[pages/ — InboxPage, TicketsListPage,\nTicketDetailPage, CreateMailPage, ...]
        TWAPI[api/ — separate axios client]
        TWCTX[context/AuthContext.tsx — thin adapter over shell's auth-store]
    end
    APP --> AUTHG --> LAYOUT
    LAYOUT --> ROLEACC
    LAYOUT -->|Staff/Team Lead/Account Manager land here| TWAPP
    TWAPP --> TWPAGES
    TWCTX -->|re-exposes, does not duplicate| STORE
    SVC -->|axios, NEXT_PUBLIC_API_URL| Backend[(unified-backend /api/v1)]
    TWAPI -->|separate axios instance,\nNEXT_PUBLIC_TICKETING_API_URL| Backend2[(unified-backend, unprefixed)]
```

**Both API clients (`src/lib/api.ts` and `src/ticket-workspace/api/client.ts`) point at the same backend process** — they're separate Axios instances for historical reasons (the pre-merge two-service world), not because they talk to different servers today. See [05-technical-architecture/frontend-architecture.md](../05-technical-architecture/frontend-architecture.md).

## Design-token unification

`.tm-scope` (`src/app/globals.css`) remaps the embedded ticket workspace's own CSS variables onto the shell's computed dark-theme values, so the two visually-distinct original products render as one consistent design system.
