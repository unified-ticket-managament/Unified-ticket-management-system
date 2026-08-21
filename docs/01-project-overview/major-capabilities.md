# Major Capabilities

| Capability | Status | Notes |
|---|---|---|
| Authentication (JWT, login/refresh/logout) | **Implemented** | Sole issuer: `app.rbac`. See [08-security/authentication.md](../08-security/authentication.md). |
| RBAC (6 roles, permission catalog) | **Implemented** | Enforcement is uneven — real in Ticketing, historically authentication-only in much of RBAC, partially hardened by a 2026-07-14/15 audit. |
| Per-user permission overrides (global + ticket-scoped) | **Implemented** | Additive-only — see [16-known-limitations/functional-limitations.md](../16-known-limitations/functional-limitations.md). |
| Permission request/approval workflow | **Implemented** | Addressed to one specific person, not a role. |
| Organization structure (Reporting Managers, dynamic org chart) | **Implemented** | HR action surface (leave, attendance, reviews) explicitly **not built**. |
| Client management | **Implemented** | |
| Ticket lifecycle (create/assign/claim/transfer/close/reopen/related) | **Implemented** | |
| Mail/Inbox (compose, reply, forward, drafts, attachments, folders, tags) | **Implemented** | "Mail v2" redesign exists only in the embedded `unified-frontend` copy — the standalone `ticketing-service/frontend` has no source at all anymore. |
| Mail/OTP automation rules | **Implemented** | Exact-match `client` condition — no fuzzy/implicit matching. |
| SLA tracking (First Response + Resolution clocks) | **Implemented** | Policy targets live-editable, not hardcoded. |
| SLA breach notification ladder | **Implemented** | Idempotent per `(clock, threshold)` crossing. |
| Escalation workflow (auto/manual, ack-window advance) | **Implemented** | Starting level is dynamic, not always Team Lead. |
| Escalation Handling SLA | **Implemented** | 25%-of-original-target formula, computed once. |
| CRITICAL priority tier | **Implemented** | Escalation-only, permanent, never manually selectable. |
| Real-time notifications (SSE) | **Implemented** | Per-process only — no multi-worker broadcast. |
| Outbound email for business-critical notifications | **Implemented, not fully live-verified** | Confirmed only via unit tests + import checks, per root `CLAUDE.md`'s own note. |
| Audit logging | **Implemented, partial coverage** | Two separate systems; several action types (attachment download/delete, mail draft save/delete) deliberately not logged. |
| Reports/dashboard | **Implemented** | Depth of aggregation **not independently verified** in this pass — see [04-functional-modules/dashboard-reporting.md](../04-functional-modules/dashboard-reporting.md). |
| Microsoft Graph mailbox integration | **Implemented, optional** | Degrades to a mock provider when unconfigured. |
| Workload-based assignment ranking | **Planned, design-only** | No code. See [17-roadmap/v2-roadmap.md](../17-roadmap/v2-roadmap.md). |
| Reporting Manager HR action surface (leave/attendance/reviews/timesheets) | **Not Implemented** | Deliberately scoped out of the Organization Structure feature. |
| AI/NLP (classification, drafting, escalation processing) | **Not Implemented / Not Confirmed** | No code found. See [04-functional-modules/ai-nlp.md](../04-functional-modules/ai-nlp.md). |
| Availability/shift-presence tracking | **Not Implemented** | No schema exists. |
| Standalone second frontend (`ticketing-service/frontend`) | **Decommissioned** | Nothing remains on disk at all as of 2026-08-21 — even the stale build artifact was deleted; `ticketing-service/` is empty. |
