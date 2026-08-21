# Testing Strategy

## What actually exists

All real, substantive test coverage in this repository lives in **`unified-backend/tests/`** — 48 files as of the 2026-08-21 commit (491+ test functions, plus the OTP classifier's own suite added in that commit). No test strategy document was found; the strategy below is reconstructed from what's actually there.

## The split: pure-logic vs. DB-touching

- **Pure-logic tests** (fake repositories, no real database — e.g. `test_notification_email_dispatch.py`, `test_sla_clock_math.py`, `test_rule_conditions.py`, `test_escalation_rules.py`) run safely together, fast, and are the majority of the suite by test count.
- **DB-touching tests** (real Postgres, rolled-back transactions — e.g. `test_escalation_service.py`, `test_interaction_threading.py`, `test_get_current_user_cache.py`, `test_ticket_number.py`) each pass individually but **three specific files hang if run together** in the same pytest process, per a pre-existing `pytest-asyncio` event-loop-scope issue. See [integration-testing.md](integration-testing.md).

## What's covered, at a glance

Every major business workflow documented in [03-business-workflows](../03-business-workflows/README.md) has at least one corresponding test file: escalation (`test_escalation_service.py` — 39 tests, the largest single file), SLA (`test_sla_clock_math.py` — 30 tests, `test_sla_sweep_service.py`, `test_sla_escalation_rules.py` — 27 tests), ticket lifecycle (`test_ticket_status_on_assignment.py`, `test_ticket_number.py`, `test_assigned_by.py`), Mail/Graph integration (`test_graph_mail_integration.py` — 55 tests, the largest overall), RBAC/permissions (`test_user_creation_role_matrix.py`, `test_scoped_ticket_access_visibility.py`, `test_permission_request_ticket_owner_routing.py`), and notifications (`test_notification_email_dispatch.py`, `test_notification_clear_all.py`).

## What's NOT covered

- **No frontend tests exist at all** — neither `unified-frontend` nor `ticketing-service/frontend` has a test file, a test framework config, or a `__tests__` directory. `npx tsc --noEmit` is the only automated correctness signal for the frontend.
- **No end-to-end/browser tests** (Playwright/Cypress) anywhere in the repository.
- **No load/performance test suite** — the one confirmed performance fix in this system (the SLA overview N+1 elimination) was measured manually, not via an automated benchmark.
- **No API contract tests** beyond what FastAPI's own OpenAPI schema generation implicitly enforces.

## Philosophy inferred from the test suite's own shape

Tests cluster tightly around the areas that have had real, confirmed bugs (escalation acceptance timing, SLA clock math, Graph attachment handling) — suggesting a reactive-but-thorough pattern: when a bug is found and fixed, a regression test is added for that exact class of failure. See [regression-testing.md](regression-testing.md).
