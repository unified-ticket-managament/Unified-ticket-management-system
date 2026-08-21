# Scope

## In current production scope (confirmed implemented and reachable)

- Authentication (email/password login, JWT access + refresh tokens, logout audit)
- Role-based access control: 6 roles, per-role permission catalog, per-user permission overrides (global and ticket-scoped), a request/approval workflow for requesting permissions
- User management (create/update/deactivate, hierarchy validation, Employee ID)
- Organization structure: reporting-manager assignment, dynamic organization chart, company-wide ticket-assignment capability
- Client management (onboarding, contacts, account-manager ownership)
- Ticket lifecycle: creation (from an interaction), assignment/claim/transfer, status/priority changes, close/reopen, related-ticket linking
- Mail/Inbox: pending-item triage, reply, internal notes (with real recipient delivery), forwarding to internal users, drafts (auto-saving), attachments, custom folders, tagging
- Mail/OTP automation rules (condition-matched actions, OTP recognition stopping the First Response SLA clock)
- SLA tracking: First Response and Resolution clocks, configurable per-priority policy, four-tier breach ladder, pause/resume on client-waiting status
- Escalation workflow: auto/manual escalation, ack-window auto-advance, Acknowledge & Assign two-step acceptance, Escalation Handling SLA, CRITICAL priority tier
- Notifications: in-app (bell + System Mail), real-time via SSE, outbound email for a fixed set of business-critical types
- Audit logging: two independent systems (RBAC-native `audit_logs`, ticketing-domain `ticket_audit_logs`)
- Reports (a page exists in the frontend — **not independently verified in depth** what data it aggregates; see [04-functional-modules/dashboard-reporting.md](../04-functional-modules/dashboard-reporting.md))
- Microsoft Graph mailbox integration (optional — degrades to a mock provider when unconfigured)

## Explicitly out of scope for the current system (confirmed absent, not merely unverified)

- AI/NLP-based ticket classification, response drafting, or escalation processing — **no such code was found** anywhere in the repository during this documentation pass.
- Workload-based assignment ranking (recommending "assign to X because they have capacity") — design-only, no code.
- Reporting Manager HR actions (leave approval, attendance, performance reviews, timesheets) — the assignment/data-model plumbing exists; none of the actual action surface does.
- An availability/shift-presence system (online/leave/shift status) — no schema exists for it.
- A standalone second frontend — `ticketing-service/frontend` no longer exists at all as of 2026-08-21 (its last remnant, a stale pre-built bundle, was deleted); `ticketing-service/` is now an empty directory and was never part of current deployment.
- Multi-process/multi-worker horizontal scaling of the backend — the RBAC session cache and SSE pub/sub are both single-process, in-memory, no shared broker.

## Ambiguous / needs confirmation

- Which of the two deployment paths (Render Blueprint vs. GitHub Actions → EC2) is the actual live production environment. See [09-deployment/environments.md](../09-deployment/environments.md).
- Whether an N8N (or similar) relay is actually wired to the generic inbound-mail endpoint (`POST /emails/incoming`) in production, or whether Graph is the sole real transport.
- Whether outbound business-critical email has been verified against a real SMTP server in production (it is unit-tested at the logic level only, per root `CLAUDE.md`'s own note on that feature).

See [16-known-limitations](../16-known-limitations/README.md) for the full, categorized list of gaps, and [17-roadmap](../17-roadmap/README.md) for what's actually planned versus merely conceivable.
