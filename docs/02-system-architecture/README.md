# System Architecture

This section documents how UTMS's pieces fit together as actually deployed and run — not an idealized target architecture.

- [architecture-overview.md](architecture-overview.md) — system context, the two-process shape
- [component-architecture.md](component-architecture.md) — major components inside the backend and frontend
- [deployment-architecture.md](deployment-architecture.md) — actual production infrastructure (Render **and** the real, active EC2 path)
- [data-flow.md](data-flow.md) — how a request/email moves through the system
- [integration-architecture.md](integration-architecture.md) — external systems and how the app talks to them
- [architecture-principles.md](architecture-principles.md) — the recurring design patterns this codebase actually follows
- [diagrams/](diagrams/) — supporting diagrams referenced from the above

## The one-paragraph version

One FastAPI process (`unified-backend`) serves two API domains — RBAC (`/api/v1/...`) and Ticketing (unprefixed) — against one shared PostgreSQL database (Neon), with two independent Alembic migration histories. One Next.js process (`unified-frontend`) is the only actively maintained UI: it owns authentication/session/RBAC administration and embeds a full copy of the ticket workspace (Mail, Tickets, SLA, Reports) as a client-side `react-router-dom` subtree. A second, standalone ticket-workspace frontend (`ticketing-service/frontend`) used to exist in the repository as a stale, pre-built `dist/` bundle with no source tree; as of the commit adding client filters/OTP classifier (2026-08-21), even that `dist/` bundle was deleted — `ticketing-service/` is now an empty directory. It is **not** part of the current build or deployment.
