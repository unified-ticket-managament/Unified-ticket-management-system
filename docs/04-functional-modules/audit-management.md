# Audit Management Module

## Purpose
Maintain two separate, permanent records of significant actions — one for identity/access management, one for everything that happens to a ticket — and present both to the user through **one unified navigation entry and one shared event-presentation UI**, without ever merging the two underlying data sources.

## Responsibilities
- RBAC-native audit logging (`audit_logs`) — auth events, user/role/permission mutations, permission overrides/requests, impersonation, and administrative changes (Rules/Mail Folders/SLA Policy).
- Ticketing-domain audit logging (`ticket_audit_logs`) — the much larger ticket-lifecycle event catalog (`AuditEventType`, ~40 values as of this writing).
- Scoped-by-default vs. centralized viewing modes for the ticket audit trail (`ticket:view_global_audit_log`).
- A second, independent centralized view of the RBAC-native trail itself (`audit:view`), reached from the same page rather than a separate sidebar destination.
- One shared frontend presentation layer (`UnifiedAuditEvent`) so a single audit event renders identically regardless of which of the two domains produced it.

## Main Components

**Backend**
- `app/rbac/services/audit_log_service.py`, `app/rbac/models/audit_log.py`, `app/rbac/repositories/audit_log_repository.py`, `app/rbac/api/v1/audit_logs.py`
- `app/ticketing/services/audit_log_service.py` (writer, `log_event`), `app/ticketing/repositories/audit_log_repository.py` (`AuditLogRepository` — `list_visible_page`, `list_by_ticket`, `list_by_ticket_ids`), `app/ticketing/models/audit_log.py`, `app/ticketing/enums/audit_enums.py`
- `TicketService.list_all_audit_logs` (`app/ticketing/services/ticket_service.py`) — the `centralized: bool` branch point for the ticket-domain scoped-vs-global mode.

**Frontend**
- `unified-frontend/src/components/audit/auditEvent.types.ts` — the shared `UnifiedAuditEvent` shape every presentation component reads.
- `unified-frontend/src/components/audit/normalizeAuditEvent.ts` — the two adapters: `normalizeTicketAuditEvent` (ticket domain) and `normalizeCentralizedAuditEvent` (RBAC domain).
- `unified-frontend/src/components/audit/AuditEventRow.tsx`, `AuditEventList.tsx`, `AuditEventDetailsDrawer.tsx` — the shared presentation components (see "Unified audit-event presentation" below).
- `unified-frontend/src/components/audit/CentralizedAuditLogPanel.tsx` — the RBAC-native table/toolbar/export logic, extracted so both call sites below share it verbatim.
- `unified-frontend/src/ticket-workspace/pages/AuditLogPage.tsx` — the single sidebar-reachable page, mounted at `/dashboard/audit-logs`.
- `unified-frontend/src/app/(dashboard)/audit-logs/page.tsx` — the RBAC-native page at `/audit-logs`, no sidebar entry, direct-link only (e.g. the Super Admin dashboard's "Latest Audit Logs" card).

## Inputs
Every mutating action across both domains that has been wired to call the corresponding `AuditLogService`/`log_event`.

## Outputs
Queryable audit trails via `GET /api/v1/audit-logs*` (RBAC) and `GET /tickets/audit-logs` / `GET /tickets/{id}/audit-logs` (Ticketing), both rendered through the same shared frontend presentation layer.

## Navigation & Page Architecture (current, verified in code)

**There is exactly one sidebar entry**, labeled "Audit Logs" (internal `NavItemKey`: `"Ticket Audit Log"`, `unified-frontend/src/lib/role-access.ts` / `src/components/layout/sidebar.tsx`), routed to `/dashboard/audit-logs` for every role that has it in `NAV_ITEMS_BY_ROLE`.

That one page (`AuditLogPage.tsx`) renders **two views** via a local `viewMode: "ticket" | "centralized"` toggle button (visible only when the viewer holds `audit:view`):

1. **Ticket Audit Log** (`viewMode === "ticket"`, the default) — the ticket-domain trail (`ticket_audit_logs`), scoped by role by default, with its own separate `ticket:view_global_audit_log`-gated widening toggle ("Show My Assigned Tickets (Global)") layered on top — see "Two independent permissions" below.
2. **Centralized Audit Log** (`viewMode === "centralized"`) — renders `<CentralizedAuditLogPanel/>` directly, i.e. the RBAC-native `audit_logs` data, gated purely by `audit:view`.

A second, separate route, `/audit-logs` (`app/(dashboard)/audit-logs/page.tsx`), also renders `<CentralizedAuditLogPanel/>` and still enforces its own `audit:view` gate for direct/deep-link access — it has **no sidebar entry of its own** (removed deliberately; see `unified-frontend/CLAUDE.md`'s "Two different nav items both currently *display* the label 'Audit Logs'" note for the history of why). It exists so a link like the Super Admin dashboard's "Latest Audit Logs" card keeps working without needing the ticket workspace mounted.

## Two independent permissions — do not conflate

| Permission | Controls | Domain |
|---|---|---|
| `ticket:view_global_audit_log` | Widens the **Ticket Audit Log** view's own scope beyond "just my/my team's tickets" | Ticketing (`ticket_audit_logs`) |
| `audit:view` | Grants access to the **Centralized Audit Log** view (RBAC's own `audit_logs` table) from either entry point above | RBAC (`audit_logs`) |

Holding one **never** implies the other — confirmed both in the frontend (`AuditLogPage.tsx`'s explicit comment: "Deliberately never called 'centralized' in this file's own variable names to avoid colliding with `centralizedMode`/`effectiveCentralized`'s unrelated, ticket-domain 'all clients' tickets' meaning") and in the backend, where `TicketService.list_all_audit_logs(centralized=True)` checks `ticket:view_global_audit_log` and `list_audit_logs`/`get_audit_log`/`get_user_audit_logs`/`export_audit_logs` all check `audit:view` (`ensure_has_permission`, `app/rbac/services/access_control.py`) — two entirely separate checks with no fallthrough between them. Site Lead/Super Admin bypass the ticket-domain widening check unconditionally via the pre-existing `GLOBAL_INBOX_ROLE_NAMES`/`isSupervisorRole` mechanism, and both hold `audit:view` by role default (`scripts/rbac_seed/seed.py`) — neither role needs to be granted anything extra to reach both views.

This independence is directly covered by `unified-backend/tests/test_audit_view_vs_global_audit_log_separation.py` (Cases A–E: each permission alone grants only its own view and is refused for the other; both together grant both; neither grants either; Site Lead/Super Admin get the ticket-domain global view for free without the permission at all).

## Unified audit-event presentation (implemented)

A single audit event — whichever domain wrote it — renders through **one** shared component chain, confirmed in code:

```
Ticket Audit API (GET /tickets/audit-logs)
        |
        v
normalizeTicketAuditEvent()            <- Ticket Audit Adapter
        |
        v
   UnifiedAuditEvent  ------------->  AuditEventRow / AuditEventList / AuditEventDetailsDrawer
        ^                                   (Shared Audit Event UI)
        |
normalizeCentralizedAuditEvent()       <- Centralized Audit Adapter
        ^
        |
Centralized Audit API (GET /api/v1/audit-logs)
```

- `auditEvent.types.ts`'s `UnifiedAuditEvent` is the one shape both adapters produce and both presentation components consume — icon, tone, action badge label, entity label/meta, a `fields` diff list, timestamp, actor name/role, an optional impersonator name, an optional `metadata` list (domain-specific extras — a ticket's related-ticket title, a centralized row's IP address/email/status), and an optional `primaryAction` (the ticket domain's "View Ticket" button; the centralized domain supplies none).
- `AuditEventRow.tsx` and `AuditEventList.tsx` are the single row/list implementation both `AuditLogPage.tsx` (ticket view) and `CentralizedAuditLogPanel.tsx` (centralized view, whether reached via `/dashboard/audit-logs`'s toggle or the standalone `/audit-logs`) render through — same icon circle, badge, entity text, field-summary line, timestamp/actor block, hover state, and empty/loading states.
- `AuditEventDetailsDrawer.tsx` is the one details side-panel both views open a row into — it replaced two former, independently-drifting drawers (the ticket workspace's old `AuditLogDetailsDrawer` and the centralized view's old `CentralizedAuditLogDetailsDrawer`), per that component's own doc comment.
- Both row/list/drawer components deliberately use only design tokens that resolve identically inside `.tm-scope` (the ticket workspace's remapped tokens) and on the plain shell page, so the same markup renders pixel-for-pixel the same in both mounting contexts.

**This satisfies the "one source of truth for individual audit-event presentation" requirement — it is not a pending item.** A future backlog item exists only for the still-separate *toolbar/filter chrome* around each view (search box, entity/event/date filters, pagination), which is intentionally still per-domain since the two domains' filterable fields genuinely differ (see `docs/AUDIT_LOG_BACKLOG.md`).

## Business Rules
- Two systems, never conflated: RBAC's `audit_logs` vs. Ticketing's `ticket_audit_logs` (same class name, `AuditLog`, different tables, different domains) — this remains true; only the *presentation* layer is now shared, never the data.
- The Ticket Audit Log view is scoped-by-default (no permission required, role-accurate slice) with an opt-in global mode gated by `ticket:view_global_audit_log` — avoiding the trap of one permission requirement blocking the whole page for most roles.
- The Centralized Audit Log view is gated purely by `audit:view`, reachable either from inside the Ticket Audit Log page's own toggle or via the standalone `/audit-logs` deep link — same permission, same data, same component, two entry points.
- Several action types are deliberately not logged (mail draft save/delete, Reports/Settings actions) — checked and ruled out as out of scope, not overlooked. **Attachment download/delete is now partially logged** — `AttachmentService` writes `ATTACHMENT_DELETED` on delete (added alongside the pre-existing `ATTACHMENT_UPLOADED`); attachment *download* is still not logged.
- `RBAC`'s `POST /audit-logs` (manual create) remains gated by a hardcoded `role.name == "Super Admin"` check, by deliberate design — it's an administrative escape hatch, not the system's real audit-writing path (every real action logs itself server-side via the owning service), and has zero legitimate callers repo-wide. This is unrelated to, and should not be confused with, the list/get/export routes below, which now use the real permission system.
- `DELETE /api/v1/audit-logs/{id}` no longer exists — retired outright (audit rows are append-only by design; a repo-wide search found zero legitimate callers). `AuditLogService.delete_log`/`AuditLogRepository.delete` (RBAC side) were removed alongside it, since the route was their only caller.
- `GET /api/v1/audit-logs/export` requires **both** `audit:view` and `audit:export` — `audit:export` alone is not sufficient, since a personal permission override could in principle grant `audit:export` without `audit:view` (overrides have no cross-permission validation); requiring both prevents this route from becoming a second door into audit data that `audit:view` itself wouldn't already allow.

## Dependencies
Every service that performs a loggable mutation.

## Database Entities
`audit_logs` (RBAC), `ticket_audit_logs` (Ticketing).

## APIs
[07-api/organization-audit.md](../07-api/organization-audit.md) (RBAC), [07-api/tickets.md](../07-api/tickets.md) (`/audit-logs` endpoints, Ticketing).

## Important Classes/Services
`AuditLogService` (one per domain), `AuditLogRepository` (one per domain), `AuditEventRow`/`AuditEventList`/`AuditEventDetailsDrawer` (shared frontend presentation, both domains).

## External Integrations
None.

## Verification / Tests
- `unified-backend/tests/test_audit_view_vs_global_audit_log_separation.py` — the two permissions' independence (Cases A–E), plus a retrievability proof that a non-ticket-scoped write (an SLA Policy edit) deliberately lands in RBAC's `audit_logs` specifically because it would be permanently unreachable in `ticket_audit_logs` (see "Known Limitations" below).
- `unified-backend/tests/test_audit_log_list_permission.py` — `GET /audit-logs`'s hardcoded-role-check-to-`audit:view` fix.
- `unified-backend/tests/test_audit_export_permission.py` — the export route's dual `audit:view` + `audit:export` gate.
- `unified-backend/tests/test_audit_log_delete_retired.py` — proves the DELETE route, its service method, and its repository method are all fully removed (not just hidden), and that creation/listing are unaffected.
- All are DB-touching tests and must be run one file at a time (known `pytest-asyncio` event-loop-scope limitation shared with other suites in this repo — see root `CLAUDE.md`).
- The frontend unification (`AuditEventRow`/`AuditEventList`/`AuditEventDetailsDrawer`/`normalizeAuditEvent`) has not been confirmed via a live browser session in this documentation pass — verified by direct source-code reading only (both call sites' actual import/render code was read in full). Treat "renders identically in a running browser" as plausible-but-not-visually-confirmed until a manual/Playwright pass checks it.

## Known Limitations
- **`ticket_audit_logs` rows with no `ticket_id` are written but not retrievable through any current Audit Log view** — see `docs/AUDIT_LOG_BACKLOG.md` (BL-001) for the full explanation; this is a real, currently-unresolved gap, not fixed by the navigation/permission/UI work described above.
- RBAC's own `POST /audit-logs` create endpoint still checks a hardcoded role-name string rather than a permission — by design (see Business Rules above), not an oversight, and distinct from the list/get/export routes, which are now permission-gated.
- Two Alembic migrations in different chains once shared an identical revision id — harmless given separate `version_table`s, but a real gotcha if scripting against revision ids directly.
- Mail draft save/delete and Reports/Settings page actions remain unlogged (no backend endpoint exists for the latter to hook an audit call into).

## Related workflows
[03-business-workflows/audit/audit-workflow.md](../../03-business-workflows/audit/audit-workflow.md).

## Remaining work
See [`docs/AUDIT_LOG_BACKLOG.md`](../AUDIT_LOG_BACKLOG.md) for the current, actively-tracked list of what's still outstanding — this document describes only what's already built and verified.

## Change History
**2026-08-29**
- Updated documentation to reflect the final Audit Logs navigation architecture: one sidebar entry (`/dashboard/audit-logs`), two views (Ticket / Centralized) toggled in-page, plus the still-reachable-but-unlisted standalone `/audit-logs` deep link.
- Documented the confirmed separation of `ticket:view_global_audit_log` (ticket-domain scope widening) and `audit:view` (RBAC centralized view access) — independent permissions, never interchangeable, backed by `test_audit_view_vs_global_audit_log_separation.py`.
- Documented the current, already-implemented shared audit-event presentation layer (`UnifiedAuditEvent`, `AuditEventRow`/`AuditEventList`/`AuditEventDetailsDrawer`, `normalizeAuditEvent.ts`'s two adapters) — confirmed in source, not a pending item.
- Corrected the prior "hardcoded Super Admin role-name check" Known Limitation to reflect that `list`/`get`/`export` are now `audit:view`/`audit:export`-gated; only `create` (a no-legitimate-caller admin escape hatch) still uses the hardcoded check, by design, and `DELETE` was removed outright.
- Recorded the remaining retrievability gap (non-ticket-scoped `ticket_audit_logs` rows, e.g. `CLIENT_CREATED`/`DISTRIBUTION_LIST_*`) separately in the new `docs/AUDIT_LOG_BACKLOG.md`, rather than leaving it as an unstructured note here.
