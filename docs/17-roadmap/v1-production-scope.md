# v1 Production Scope

This is a restatement of [01-project-overview/scope.md](../01-project-overview/scope.md) framed as a release-scope document, per this section's required structure — see that document for the authoritative version.

## Implemented and confirmed in production scope

Authentication; RBAC (6 roles, permission catalog, per-user overrides, permission requests); Organization Structure (Reporting Manager assignment, dynamic org chart, widened ticket-assignment); Client management; full ticket lifecycle; Mail/Inbox (compose, reply, forward, drafts, attachments, folders, tags); Mail/OTP rules; SLA tracking (both clocks, breach ladder); Escalation workflow (auto/manual, Acknowledge & Assign, Handling SLA, CRITICAL priority); real-time notifications (SSE) plus conditional outbound email; two-system audit logging; Reports/Dashboard; optional Microsoft Graph mailbox integration.

See [01-project-overview/major-capabilities.md](../01-project-overview/major-capabilities.md) for the full Implemented/Partial/Not-Implemented table.

## Explicitly out of v1

AI/NLP of any kind; workload-based assignment ranking; the Reporting Manager HR action surface (leave/attendance/reviews/timesheets); an availability/shift-presence system; the standalone `ticketing-service/frontend` (decommissioned in practice, no source tree remains).

## What "v1" means here

No version-numbering scheme (semver tags, a CHANGELOG, GitHub releases) was found in the repository — "v1" in this roadmap section is a documentation convention denoting "what's live and confirmed today," not a formally tagged release. See [19-release-notes](../19-release-notes/README.md) for the closest thing to a release history this project has (a dated engineering log, not version tags).
