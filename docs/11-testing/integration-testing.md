# Integration Testing

Tests that hit a real Postgres database (rolled-back transaction convention — each test's changes are undone at teardown, not left in the shared dev database).

## Representative files

| File | Tests | Focus |
|---|---|---|
| `test_escalation_service.py` | 39 | Core `EscalationService` behavior — manual/auto escalate, acknowledge, confirm-assignment, SLA reshift, authorization. The single largest test file in the suite. |
| `test_interaction_threading.py` | 6 | Thread-root resolution and descendant listing |
| `test_get_current_user_cache.py` | 4 | RBAC cache hit/miss, stale `permission_version` rejection, deactivated-user rejection |
| `test_ticket_number.py` | 16 | Ticket number generation, uniqueness, immutability, `TKT-` search |
| `test_internal_note_recipients.py` | 15 | Internal-note recipient resolution across every role pair |
| `test_view_escalated_permission.py` | 15 | Viewer role's widened access while an escalation is active |
| `test_organization_chart_hierarchy.py` | 14 | Org chart traversal (ancestors/direct reports, deactivated exclusion) |
| `test_graph_mail_integration.py` | 55 | The largest file overall — webhook `clientState` validation, provider client construction, auth |

## The known, confirmed constraint: three files can't run together

`test_escalation_service.py`, `test_interaction_threading.py`, and `test_get_current_user_cache.py` each pass individually but **hang** if more than one runs in the same `pytest` process. Root cause: a module-level async engine's connection pool binds to whichever event loop existed when it was first used; `pytest-asyncio`'s default per-test event-loop scope means a second test's fresh loop can never complete operations queued against the first loop's transport. This is a **pre-existing `pytest-asyncio` issue**, not introduced by any specific feature work.

**Practical implication**: run these three files individually (`pytest tests/test_escalation_service.py`, then separately `pytest tests/test_interaction_threading.py`, etc.) rather than `pytest tests/` as one invocation, until `asyncio_default_fixture_loop_scope` is configured or a per-test engine is introduced (neither has been done as of this pass).

## A known, accepted test flake (not the same issue as above)

`test_escalation_service.py::test_overdue_active_escalation_advances_without_touching_sla` asserts `evaluate_overdue` advances exactly 1 escalation, but the method's own query scans the *entire* `ticket_escalations` table — real leftover `ACTIVE` rows from earlier manual/live-testing sessions in the shared dev database inflate the count (documented as 2 leftover rows initially, ~40 by a later session). This is dev-data debris, not a regression — not fixed as of this pass (would require either scoping the assertion to the test's own created ticket_id, or cleaning up the leftover rows).

## Recommendation

Adding `asyncio_default_fixture_loop_scope = "session"` (or a per-test engine fixture) to `pytest.ini` would likely resolve the three-file hang — a reasonable, scoped fix that hasn't been attempted as of this documentation pass.
