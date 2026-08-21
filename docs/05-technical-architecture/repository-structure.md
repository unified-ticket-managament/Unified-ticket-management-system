# Repository Structure

This is a monorepo formed by merging three previously-independent git repositories via `git subtree` (full history preserved), plus a later backend unification and frontend consolidation.

```
.
├── unified-backend/          The actual, currently-running backend for everything
│   ├── app/
│   │   ├── main.py           FastAPI app assembly, routers, lifespan, middleware
│   │   ├── rbac/              RBAC domain — mounted at /api/v1
│   │   │   ├── api/v1/        Routes
│   │   │   ├── services/      Business logic + (partial) authorization
│   │   │   ├── repositories/  Data access
│   │   │   ├── models/        Permission, RolePermission, AuditLog, UserPermissionOverride,
│   │   │   │                  PermissionRequest, ReportingManagerTeam (User/Role/Category
│   │   │   │                  re-exported from shared_models)
│   │   │   └── schemas/       Pydantic request/response models
│   │   ├── ticketing/         Ticketing domain — mounted unprefixed
│   │   │   ├── api/           13 router files
│   │   │   ├── services/      30 service files — the largest single directory in the app
│   │   │   ├── repositories/   16 repository files
│   │   │   ├── models/         17 model files
│   │   │   ├── schemas/        ~25 schema files
│   │   │   ├── enums/          Postgres-native enum definitions
│   │   │   └── storage/        Supabase/S3 storage abstraction
│   │   ├── notifications/     Shared, cross-cutting — notify(), SSE, email policy
│   │   ├── core/               config.py (Settings), rbac_cache.py, sla_scheduler.py,
│   │   │                       graph_*_scheduler.py, email_sender.py, request_timing.py
│   │   ├── dependencies/       auth.py — shared get_current_user/get_current_agent/get_current_user_sse
│   │   ├── database/            session.py (engine/pool), timing.py
│   │   └── auth/                 jwt.py (encode/decode)
│   ├── alembic_rbac/           RBAC's own migration history (20 files)
│   ├── alembic_ticketing/      Ticketing's own migration history (59 files, one merge point)
│   ├── scripts/
│   │   ├── rbac_seed/          RBAC seed data (roles, permissions, demo Super Admin)
│   │   ├── ticketing_seed/     Demo client seeding
│   │   ├── org_seed/           Real 99-employee org import + backfill scripts
│   │   └── start.sh            The actual local/prod startup sequence
│   ├── tests/                  46 test files, 491 test functions
│   └── docker-compose.yml      MinIO only (local object storage) — no app containers
│
├── unified-frontend/          The only actively maintained frontend
│   ├── src/
│   │   ├── app/                Next.js App Router route tree
│   │   ├── components/         Shell UI (auth, layout, users, roles, organization, profile, settings...)
│   │   ├── services/            RBAC-side API client layer
│   │   ├── store/                Zustand stores
│   │   ├── lib/                   role-access.ts, i18n, api.ts
│   │   ├── modules/rbac/          A separate RBAC domain module
│   │   ├── providers/             App-level React providers
│   │   ├── types/                 Shared TypeScript types
│   │   └── ticket-workspace/       Embedded copy of the ticket workspace (own api/, pages/,
│   │                               components/, hooks/, context/, lib/, types/)
│   └── docs/                       Stale ARCHITECTURE.md/API.md/DEPLOYMENT.md — do not trust,
│                                    see unified-frontend/CLAUDE.md's own Known Issues note
│
├── ticketing-service/            Empty as of 2026-08-21 — its last remnant, a stale pre-built
│                                 dist/ bundle with no package.json/src/, was deleted in the
│                                 same commit that added client filters/the OTP classifier.
│                                 Not part of current build/deployment; nothing to run here.
│
├── shared_models/
│   └── shared_models/
│       └── models/               User, Role, Category — single source of truth,
│                                 installed as a local editable package by unified-backend
│
├── render.yaml                  Render Blueprint — 2 services (unified-backend, unified-frontend)
├── DEPLOYMENT.md                STALE — describes a retired 4-service topology, do not follow as-is
├── CLAUDE.md                    Deep technical/historical reference (root)
└── .github/workflows/
    └── deploy.yml                The only workflow file — GitHub Actions → EC2 via SSH, on every
                                   push to main. (No sla-sweep.yml exists despite being referenced
                                   elsewhere.)
```

See [02-system-architecture/architecture-overview.md](../02-system-architecture/architecture-overview.md) for why this shape exists, and [16-known-limitations](../16-known-limitations/README.md) for the specific doc-vs-code drift points called out above.
