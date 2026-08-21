# SLA Calculation Workflow

## 1. Purpose
Compute each clock's due date/elapsed-fraction correctly across priority changes, pauses, and escalations — the single area with the most dedicated test coverage in the codebase (`test_sla_clock_math.py`, 30 tests).

## 2. Trigger
Ticket creation (initial target), priority change (`POST /tickets/{id}/priority`, or the system's own CRITICAL bump), and every sweep tick (elapsed-fraction re-evaluation).

## 3. Actors
The system; any agent/supervisor changing priority.

## 4. Preconditions
An `SLAPolicy` row exists for the relevant priority.

## 5. High-Level Flow
Target minutes looked up from `SLAPolicy` by priority → `due_at` computed/reshifted → elapsed fraction computed at sweep time against `warning_1_percentage`/`warning_2_percentage`/100%/(escalation threshold).

## 6. Detailed Workflow
- **Initial target**: `due_at = started_at + policy.resolution_target_minutes` (or `first_response_target_minutes`).
- **Priority change reshift** (`SLAService.reshift_resolution_clock_for_priority_change`): recomputes `due_at` proportionally to the new priority's target, accounting for time already elapsed — not simply restarting the clock from now, and not leaving the old target in place either.
- **CRITICAL bump**: `EscalationService._bump_priority_to_critical` calls this exact same reshift function (via a deferred import to avoid a circular import with `sla_service.py`) — manual Change Priority and the automatic escalation bump share one code path, so the clock math is guaranteed consistent between the two triggers.
- **Elapsed-fraction evaluation** (sweep time): `fraction = elapsed / active_target_minutes`, compared against `half_elapsed=warning_1_percentage/100`, `at_risk=warning_2_percentage/100`, `breached=1.0`, `escalated=` (an implicit higher threshold — see [sla-breach.md](sla-breach.md)).
- **Escalation Handling SLA target** (a related but separate calculation): `round(original_resolution_target_minutes * 60 * 0.25)` — always 25% of the **original** target, computed once in `EscalationHandlingSlaService.compute_escalation_handling_target_seconds`, never derived from remaining/overdue time.

## 7. Business Rules
- **CRITICAL priority is never a valid input to a manual priority change** — the only writer is the escalation-creation path, and it's idempotent (a no-op if the ticket is already CRITICAL) so re-escalating after an ack-window advance never double-reshifts the clock.
- **The Handling SLA's 25% figure is fixed to the *original* target, not a moving target** — an escalation cycle doesn't get a shrinking or growing handling window based on how overdue the ticket already was.

## 8. Decision Points
- Priority increases vs. decreases → reshift direction differs (a downgrade can move `due_at` later relative to elapsed time, an upgrade moves it earlier).
- Is this the first time CRITICAL was set on this ticket? → idempotency check before the bump/reshift runs.

## 9. Database Changes
`resolution_slas.due_at`, `.active_target_minutes`, `.priority`; `escalation_handling_slas.target_seconds`, `.due_at`.

## 10. APIs Involved
`POST /tickets/{id}/priority`, `PATCH /sla/policies/{id}` (changes the inputs to future calculations, not past ones).

## 11. Services / Components Involved
`SLAService.reshift_resolution_clock_for_priority_change`, `EscalationService._bump_priority_to_critical`, `EscalationHandlingSlaService.compute_escalation_handling_target_seconds`, `SLASweepService`.

## 12. External Integrations
N/A.

## 13. Notifications
Not itself — this is pure computation; see [sla-breach.md](sla-breach.md) for the notification side.

## 14. Audit Events
`PRIORITY_CHANGED` (attributed to `ActorRole.SYSTEM` for the automatic CRITICAL bump, to the real user for a manual change).

## 15. Failure Scenarios
A `SLAPolicy` row missing for a priority tier would fail this calculation — all four tiers (LOW/MEDIUM/HIGH/CRITICAL) are seeded, so this should not occur in a correctly-migrated database.

## 16. Edge Cases
- The frontend's SLA Timing Matrix page's own `PRIORITY_ORDER` constant was never updated to include `"CRITICAL"` — it works today only because `Array.indexOf` returns `-1` for an unlisted value, which happens to sort first; flagged as fragile in `unified-frontend/CLAUDE.md`.
- `test_sla_clock_math.py`'s 30 tests are the authoritative reference for exact reshift-math edge cases (pause during a priority change, downgrade after upgrade, etc.) — read that file directly for precise formulas rather than relying on this document's prose summary.

## 17. Postconditions
`resolution_slas.due_at` and `.active_target_minutes` are internally consistent with the ticket's current priority and elapsed/paused history.

## 18. Relevant Source Files
- `unified-backend/app/ticketing/services/{sla_service,escalation_service,escalation_handling_sla_service}.py`
- `unified-backend/tests/test_sla_clock_math.py`
- `unified-backend/app/ticketing/models/sla_policy.py`

## 19. Example Scenario
A MEDIUM ticket (48h resolution target) is 24 hours in (50% elapsed) when a supervisor upgrades it to HIGH (24h target). The reshift computes a new `due_at` that accounts for the 24 hours already spent against the *new*, tighter target — not simply "now + 24h," and not "original due_at unchanged."
