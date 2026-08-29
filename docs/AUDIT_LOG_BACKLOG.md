# Audit Logs — Current Backlog

## Purpose

This document contains only **remaining, unresolved, or intentionally deferred work** for the Audit Logs feature. It is deliberately separate from [`docs/04-functional-modules/audit-management.md`](04-functional-modules/audit-management.md) (what's built, why, and how it was verified) and [`docs/03-business-workflows/audit/audit-workflow.md`](03-business-workflows/audit/audit-workflow.md) (the full workflow detail) — those two documents describe the completed, current state; this one describes what's left. Do not duplicate their content here.

## Current Status

| Area | Status |
|---|---|
| Single sidebar navigation entry (`/dashboard/audit-logs`) | **Completed** |
| Two in-page views (Ticket Audit Log / Centralized Audit Log) | **Completed** |
| Permission separation (`ticket:view_global_audit_log` vs `audit:view`) | **Completed** — independence proven by `test_audit_view_vs_global_audit_log_separation.py` |
| RBAC `audit_logs` list/get/export real permission gating | **Completed** — `list`/`get`/`user`/`export` moved off the hardcoded role-name check onto `audit:view`/`audit:export` |
| `DELETE /audit-logs/{id}` removal | **Completed** — route, service method, and repository method all removed |
| Unified individual audit-event presentation (`UnifiedAuditEvent` + shared `AuditEventRow`/`AuditEventList`/`AuditEventDetailsDrawer`) | **Completed** — confirmed in source; both domains render through the same components |
| Non-ticket-scoped audit-event retrievability (`CLIENT_CREATED`, `DISTRIBUTION_LIST_*`) | **Pending** — see BL-001 |
| Shared filter/toolbar chrome across the two views | **Pending** (intentionally out of the unification's original scope — see BL-002) |
| Live browser verification of the unified UI | **Pending** — see BL-003 |
| Attachment download logging | **Deferred** (see Known Limitations) |
| Mail draft save/delete, Reports/Settings action logging | **Deferred** (see Known Limitations) |

## Priority Definitions

- **P0 — Critical**: actively breaks a compliance/audit guarantee the product claims to provide.
- **P1 — High**: a real, reproducible gap with a plausible near-term compliance or support-escalation impact.
- **P2 — Medium**: a real gap, but narrow blast radius or a known, low-frequency trigger.
- **P3 — Low**: cosmetic, verification-only, or a deliberately deferred nice-to-have.

## Backlog Items

### BL-001 — Non-ticket-scoped `ticket_audit_logs` rows are written but never retrievable

**Status**: Pending — confirmed still present in the current codebase.
**Priority**: P1.
**Area**: Backend (`app/ticketing/repositories/audit_log_repository.py`, `app/ticketing/services/*`).

**Current problem**: Several `AuditEventType` values are written against entities that have no `ticket_id` at all — confirmed for `CLIENT_CREATED` (`client_service.py`) and every `DISTRIBUTION_LIST_*` event (`distribution_list_service.py`): `DISTRIBUTION_LIST_CREATED`, `DISTRIBUTION_LIST_UPDATED`, `DISTRIBUTION_LIST_MEMBER_ADDED`, `DISTRIBUTION_LIST_MEMBER_REMOVED`, `DISTRIBUTION_LIST_DEACTIVATED`, `DISTRIBUTION_LIST_DELETED`. These rows are written successfully to `ticket_audit_logs` (`AuditLogRepository.create`, via `AuditLogRepository._derive_ticket_id`, which returns `None` when `entity_type != TICKET` and no `ticket_id` key is present in `new_values`) but are then permanently unreachable through every existing read path:

- `list_visible_page` (the query backing both the Ticket Audit Log's scoped view and its `centralized=true` global mode) hard-filters `conditions = [AuditLog.ticket_id.isnot(None)]` and inner-joins to `tickets` — a `NULL`-`ticket_id` row can never match this join.
- `list_by_ticket` filters on `AuditLog.ticket_id == ticket_id` — no ticket id to match against.
- `list_by_ticket_ids` filters on `AuditLog.ticket_id.in_(ticket_ids)` — same problem.

This is already acknowledged directly in the codebase, not a newly discovered issue: `app/ticketing/enums/audit_enums.py`'s own comment on `DISTRIBUTION_LIST_DELETED` states "this event's rows have no ticket_id and are therefore not retrievable through any existing Audit Log view."

**Why it matters**: A Distribution List or Client creation/mutation/deletion is a real, potentially compliance-relevant action that the system represents as "audited" (the row exists, survives forever, and would show up in a raw SQL query) but which no user — including Super Admin — can actually see through the product's own Audit Log UI. This is a silent gap between "we log this" and "you can review this," which is worse than not logging it at all if anyone relies on the UI as a complete record.

**Current behavior**: The row is written and permanently stored; every list/read endpoint that backs the Audit Log UI silently excludes it. No error, no partial result indicator — the event simply never appears.

**Expected behavior**: Either (a) these events become retrievable through a new or extended query path, or (b) if genuinely out of scope for a ticket-shaped audit view, they should be exposed through a different, explicit surface (e.g. a Client/Distribution-List-specific admin history view) rather than silently vanishing from every path a user could reasonably look.

**Recommended approach** (not implemented — do not build this from this note alone without re-scoping): Extend `AuditLogRepository` with a query path that does not require `ticket_id IS NOT NULL` — e.g. a separate `list_entity_scoped_page(entity_type, entity_id, ...)` for Client/Distribution-List detail views, or a broadened `list_visible_page` mode that `LEFT JOIN`s `tickets` instead of inner-joining, with ticket-specific columns (`ticket_title`, `client_company_name`) nulled out for rows with no ticket. The latter has wider blast radius (touches the query every existing view already depends on) and needs its own visibility-scoping review, since `account_manager_id`/`ticket_types` scoping is currently expressed entirely in terms of the `tickets` join.

**Files/components likely involved**: `app/ticketing/repositories/audit_log_repository.py`, `app/ticketing/services/ticket_service.py` (`list_all_audit_logs`), `app/ticketing/services/client_service.py`, `app/ticketing/services/distribution_list_service.py`, and whichever frontend view is chosen to surface the result (`AuditLogPage.tsx` or a new page).

**Acceptance criteria**:
- A `CLIENT_CREATED` or `DISTRIBUTION_LIST_*` event is retrievable through at least one product surface, by a user holding the relevant permission, without a raw SQL query.
- Existing ticket-scoped visibility/permission scoping is not weakened for any existing caller.
- No fabricated `ticket_title`/`client_company_name` for a row that genuinely has neither.

**Dependencies**: None blocking — can be scoped independently.

**Risk**: Touching `list_visible_page` risks regressing the ticket-scoped views every existing role depends on daily; a narrower, additive query path is lower-risk than modifying the shared one.

**Out of scope for this item**: Merging RBAC's `audit_logs` and Ticketing's `ticket_audit_logs` into one table — explicitly rejected elsewhere in this documentation set; not revisited here.

---

### BL-002 — Toolbar/filter chrome is still separate per view (informational, not a defect)

**Status**: Pending — by original design, not an oversight, but worth tracking explicitly since Part 9-style requests ("unify the two audit views") could otherwise be mistaken as already fully done.
**Priority**: P3.
**Area**: Frontend (`AuditLogPage.tsx`, `CentralizedAuditLogPanel.tsx`).

**Current problem**: The individual **event row/card** is already fully unified (see the completed document) — but the surrounding toolbar (search box, entity/event-type filters, date range, pagination style) is still two separate implementations: `AuditLogPage.tsx`'s ticket-domain filter bar (entity type, event type, agent, client, date range, server pagination) and `CentralizedAuditLogPanel.tsx`'s own toolbar (search, date range, TanStack Table client pagination).

**Why it matters**: This is a much smaller inconsistency than the row-level one already fixed, since the two domains' genuinely-filterable fields differ (a centralized RBAC row has no "entity type" filter menu that makes sense the same way a ticket event's does). Listed here only so a future request to "make the two audit views fully identical" is evaluated against an accurate current baseline, not against the mistaken assumption that only the row UI needed fixing.

**Current behavior**: Two independent toolbar/filter implementations, no shared component.

**Expected behavior**: Not prescribed — this is a judgment call for whoever picks this up, since full toolbar unification may not be worth the cost given the domains' different filterable fields.

**Recommended approach**: If pursued, extract only the genuinely shared controls (search input, date-range pair, Refresh button, "Read-only" badge) into a shared toolbar shell, leaving domain-specific filter controls as slotted children — mirroring how `AuditEventList`'s `footer` prop already lets pagination differ per domain without duplicating the list/row implementation.

**Files/components likely involved**: `AuditLogPage.tsx`, `CentralizedAuditLogPanel.tsx`.

**Acceptance criteria**: Not defined — scope this properly before starting; do not treat this note as a finished spec.

**Dependencies**: None.

**Risk**: Low — additive/refactor-only, no data or permission changes.

**Out of scope**: Changing either view's actual filter *capabilities* (adding new filters) — this item is about shared chrome, not new functionality.

---

### BL-003 — Unified audit-event UI not yet confirmed via a live browser session

**Status**: Pending.
**Priority**: P2.
**Area**: Verification only — no code change.

**Current problem**: The claim "Ticket Audit Log and Centralized Audit Log render individual events identically" is confirmed by direct source-code reading (both call sites' render code, the shared components' implementation, and the shared design-token usage), but has not been confirmed by actually running the app and visually comparing the two views side by side in a browser.

**Why it matters**: Source-code confirmation rules out the two views diverging in *code*, but not a runtime-only discrepancy (a CSS specificity conflict, a `.tm-scope` token that doesn't actually resolve the same in both mounting contexts, a console error swallowed silently).

**Recommended approach**: A short manual or Playwright pass — open `/dashboard/audit-logs` in Ticket view, open the same page's Centralized toggle, open the standalone `/audit-logs`, and visually compare one row and one details-drawer open from each, plus check the browser console for errors.

**Files/components involved**: None to change — verification only.

**Acceptance criteria**: A screenshot or explicit written confirmation that all three renders are visually identical for an equivalent event.

**Dependencies**: A running dev environment with seeded audit data in both tables.

**Risk**: None — read-only verification.

## Known Limitations

These are accepted, deliberate scope boundaries — not backlog items, and not expected to change without a new, separate decision:

- **Attachment download is not audit-logged** (attachment *delete* now is, via `ATTACHMENT_DELETED`). Deliberately checked and ruled out as out of scope, per root `CLAUDE.md`.
- **Mail draft save/delete is not audit-logged.** Same deliberate scope decision.
- **Reports/Settings page actions are not audit-logged** — there is no backend endpoint for either to hook an audit call into at all, so this isn't a logging gap so much as "there's no mutation to log."
- **RBAC's `POST /audit-logs` (manual create) remains gated by a hardcoded role-name check, not a permission** — intentional, since it's an administrative escape hatch with zero legitimate callers, not the system's real audit-writing path. Not a backlog item unless a real caller for this route ever emerges.
- **Two Alembic migrations in different chains once shared an identical revision id** — harmless operationally (separate `version_table`s per chain); only relevant if someone scripts against revision ids directly across chains.

## Deferred / Future Improvements

- **Merging the two audit tables into one schema** — explicitly rejected as a goal; the two domains (identity/access management vs. ticket lifecycle) are different enough in shape and access-control model that a shared table would need to fake structure neither side actually has. Not reconsidered unless a future requirement makes a compelling case.
- **A dedicated Client/Distribution-List admin history surface** — one possible resolution path for BL-001, deferred pending a decision on whether that's the right shape versus extending the existing Audit Log views.
