# Troubleshooting: SLA

## Problem: A local fix to SLA/escalation timing "isn't taking effect" no matter how many times the server is restarted

**Symptoms**: Code changes to escalation-acceptance timing (or any SLA-sweep-adjacent logic) appear to have zero effect, reproducibly, across multiple restarts.

**Possible Causes**: A developer's local backend and a deployed instance can share the exact same Neon database, each running an **independent in-process SLA scheduler** — the deployed instance keeps ticking and "wins" the race against local testing often enough to look like the local fix isn't real.

**How to Diagnose**: Add throwaway instrumentation to the suspected local code path and confirm whether it fires at all while the bug keeps reproducing — if it never fires, the deployed instance is the one actually processing the ticket.

**Resolution**: Either ask whoever manages the deployment to check its logs for `Scheduled SLA sweep completed` lines and suspend it during testing, or — the better fix — create a Neon **branch** and point local `.env` at it, isolating local testing entirely.

**Prevention**: Default to a Neon branch for local development from the start of any SLA/escalation-related work.

**Related Documentation**: [09-deployment/environments.md](../../09-deployment/environments.md), [10-operations/system-health.md](../../10-operations/system-health.md).

---

## Problem: The entire SLA sweep tick fails, blocking every other ticket's escalation/notification for that tick

**Symptoms**: No new escalations, breach notifications, or Escalated-tab entries appear for an entire sweep cycle, across multiple unrelated tickets.

**Possible Causes** (historical, fixed for the specific cause found): A ticket with a corrupted `ticket_type` (not matching any real `CategoryName`) triggered `InvalidTextRepresentationError` when compared against a native Postgres enum column inside `UserRepository.list_active_by_role_and_category`/`list_active_staff_by_category`. The sweep's per-ticket `SAVEPOINT` isolation was believed to fully contain this — confirmed **not** to hold for this error class, cascading into a `MissingGreenlet` error on a later, unrelated ticket in the same tick.

**How to Diagnose**: Look for `InvalidTextRepresentationError`/`MissingGreenlet` in sweep-related logs; query for any ticket with a `ticket_type` not matching a real `CategoryName` value.

**Resolution**: Fixed by validating `category_name` in Python before the query reaches Postgres. If a *new* error class produces this same "one ticket blocks the whole tick" symptom, know that the SAVEPOINT isolation is not a universal guarantee.

**Related Documentation**: [16-known-limitations/performance-limitations.md](../../16-known-limitations/performance-limitations.md), [03-business-workflows/sla/sla-breach.md](../../03-business-workflows/sla/sla-breach.md).

---

## Problem: A reported SLA/escalation bug turns out not to be a logic bug at all

**Symptoms**: Every escalation-acceptance code path 500s with `UndefinedColumnError` / similar.

**Possible Causes**: The database is behind the current Alembic head for `alembic_ticketing` — missing columns the current code genuinely depends on.

**How to Diagnose**: `alembic -c alembic_ticketing/alembic.ini current` vs. `heads`, **before** investigating application code.

**Resolution**: `alembic -c alembic_ticketing/alembic.ini upgrade head` — confirmed to fix this exact scenario with zero application-code changes in this project's own history.

**Related Documentation**: [06-database/migrations.md](../../06-database/migrations.md).
