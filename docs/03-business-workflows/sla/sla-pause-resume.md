# SLA Pause/Resume Workflow

## 1. Purpose
Ensure a ticket isn't penalized for time spent waiting on the client, while preserving a full, auditable history of exactly when and why the clock was paused.

## 2. Trigger
Automatic: `InteractionService.change_status` transitioning a ticket into/out of `WAITING_FOR_CLIENT`. Manual: `POST /tickets/{id}/sla/pause` / `POST /tickets/{id}/sla/resume`.

## 3. Actors
The system (automatic path); supervisors (manual override path — role-restricted in `SLAService`).

## 4. Preconditions
Resolution SLA clock exists and is currently `RUNNING` (pause) or `PAUSED` (resume).

## 5. High-Level Flow
Status/manual trigger → `SLAService.pause_resolution_clock`/`resume_resolution_clock` → `resolution_sla_pause_intervals` row opened/closed → audit event logged.

## 6. Detailed Workflow
1. **Automatic pause**: entering `WAITING_FOR_CLIENT` calls `pause_resolution_clock` unconditionally — always logs `SLA_PAUSED`.
2. **Automatic resume**: leaving `WAITING_FOR_CLIENT` to `IN_PROGRESS` or `RESOLVED` specifically calls `resume_resolution_clock` — logs `SLA_RESUMED`. Leaving to `CLOSED` does **not** — that transition is already covered by resolution/closure semantics.
3. **Manual override** (`SLAService.manual_pause`/`manual_resume`): same two event types, distinguished only by a `"trigger": "manual_override"` key in the audit event's `new_values` — one event type covers both triggers.
4. Every pause opens a new `resolution_sla_pause_intervals` row (`paused_at` set, `resumed_at` null); every resume fills `resumed_at` on the open interval. This is an **append-only ledger** — a ticket paused and resumed five times has five rows, not one overwritten row.

## 7. Business Rules
- **`SLA_PAUSED`/`SLA_RESUMED` used to be silent for the automatic path** — only the manual-override endpoints ever logged an event, even though the clock itself was pausing/resuming correctly; this was a real audit-trail gap, fixed by making `change_status` log unconditionally too. The two prior event names (`SLA_MANUALLY_PAUSED`/`SLA_MANUALLY_RESUMED`) were renamed in-place (`ALTER TYPE ... RENAME VALUE`) to the current, trigger-agnostic names.
- A dedicated `SlaTimeline.tsx` frontend component that used to be the only place these events surfaced was **removed entirely** once the Audit Log tab already showed them — avoiding two redundant UIs for the same data.

## 8. Decision Points
- Automatic (status-driven) vs. manual (explicit endpoint) — same event types, different `trigger` tag.
- Resume target status `IN_PROGRESS`/`RESOLVED` vs. `CLOSED` — only the former two log `SLA_RESUMED`.

## 9. Database Changes
`resolution_slas.status`, `.paused_at`, `.total_paused_seconds`; `resolution_sla_pause_intervals` (new row per pause, `resumed_at` filled per resume); `ticket_audit_logs` — `SLA_PAUSED`/`SLA_RESUMED`.

## 10. APIs Involved
`POST /tickets/{id}/status` (automatic path), `POST /tickets/{id}/sla/pause`, `POST /tickets/{id}/sla/resume`.

## 11. Services / Components Involved
`InteractionService.change_status`, `SLAService.{pause_resolution_clock,resume_resolution_clock,manual_pause,manual_resume}`.

## 12. External Integrations
N/A.

## 13. Notifications
Not independently confirmed whether pause/resume itself notifies anyone — verify in `SLAService` call sites.

## 14. Audit Events
`SLA_PAUSED`, `SLA_RESUMED` — both triggers, distinguished by `new_values.trigger`.

## 15. Failure Scenarios
Attempting to pause an already-paused clock, or resume a running one — exact validation behavior **not independently confirmed** in this pass.

## 16. Edge Cases
- Manual pause/resume is role-restricted (`SLAService`) — the exact allowed role set was **not independently re-verified** letter-for-letter in this pass; treat as supervisor-level and confirm in code before relying on it for an access decision.

## 17. Postconditions
`resolution_sla_pause_intervals` gives a complete, queryable history of every pause/resume cycle for the ticket, independent of the clock's current live state.

## 18. Relevant Source Files
- `unified-backend/app/ticketing/services/{interaction_service,sla_service}.py`
- `unified-backend/app/ticketing/models/resolution_sla_pause_interval.py`
- `unified-backend/alembic_ticketing/versions/a2c4e6f8b0d3_rename_sla_manually_paused_resumed.py`

## 19. Example Scenario
A supervisor manually pauses a ticket's SLA clock for an internal reason unrelated to client status (e.g. awaiting a vendor). The event logs as `SLA_PAUSED` with `new_values.trigger = "manual_override"`, distinguishing it in the Audit Log from an automatic `WAITING_FOR_CLIENT`-driven pause, even though both share the same event type.
