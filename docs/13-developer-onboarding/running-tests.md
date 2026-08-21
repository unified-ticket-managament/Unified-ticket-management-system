# Running Tests

## Backend

```bash
cd unified-backend
pytest
```

Most of the 46 test files / 491 tests run safely together. **Three specific files hang if run in the same pytest process as each other**: `test_escalation_service.py`, `test_interaction_threading.py`, `test_get_current_user_cache.py` — a pre-existing `pytest-asyncio` event-loop-scope issue (a shared async engine's connection pool binds to whichever event loop existed first; a second test's fresh per-test loop can never complete queued operations against the first one's transport). If `pytest` hangs, run these files individually:

```bash
pytest tests/test_escalation_service.py
pytest tests/test_interaction_threading.py
pytest tests/test_get_current_user_cache.py
```

## A known, accepted flake against the shared dev database

`test_escalation_service.py::test_overdue_active_escalation_advances_without_touching_sla` may fail with a higher-than-expected count if run against a shared dev database with leftover `ACTIVE` escalation rows from prior manual testing — this is dev-data debris, not a real regression. See [11-testing/integration-testing.md](../11-testing/integration-testing.md).

## Frontend

**No test suite exists.** Use `npx tsc --noEmit` as the correctness gate:

```bash
cd unified-frontend
npx tsc --noEmit
```

## `shared_models`

```bash
cd shared_models
pytest tests/
```

One trivial import-smoke test (`test_import.py`) — confirms `Base`/`User`/`Role` import cleanly.

## Before assuming a test failure is a real bug

Check whether your local database is at the correct Alembic head for both chains (`alembic ... current` vs `heads`) — a stale schema has produced test failures that looked like logic bugs before, more than once, in this exact codebase.
