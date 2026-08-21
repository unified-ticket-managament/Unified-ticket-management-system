# Incident Response

No formal incident-response runbook exists in the repository. This page distills the actual, repeated diagnostic patterns from this codebase's own documented incident history (root `CLAUDE.md`) into a practical first-response guide.

## First move for almost any confusing symptom: check schema and process freshness before code

1. **Is the database schema actually at head?** `alembic -c alembic_rbac/alembic.ini current` / `alembic -c alembic_ticketing/alembic.ini current`, compared against `heads`. A stale schema has repeatedly produced 500s that looked exactly like logic bugs.
2. **Is the running process actually the one you think it is?** Compare the worker process's start time against the mtime of any recently-edited file. A `--reload` log line saying "Reloading..." is not proof the new code is live.
3. **Is a second process (local vs. deployed) racing on the same database?** Especially for anything SLA/escalation-timing related.

## "It looks like a CORS error" → check for an unhandled backend 500 first

An unhandled exception's response carries no `Access-Control-Allow-Origin` header, so the browser reports a CORS failure rather than surfacing the real 500. **Confirmed three separate times in this codebase's history** (a Python enum missing a Postgres enum value that already existed; a missing `selectinload` import; the mirror-image enum gap for `CRITICAL` priority). Reproduce the suspected service-layer call directly in a throwaway script, bypassing FastAPI/HTTP entirely, to get the real traceback — don't debug CORS configuration first.

## SLA/escalation timing looks wrong

1. Check for the shared-database racing-scheduler scenario (local + deployed both ticking).
2. Check schema freshness (see above) — this exact symptom class has been a stale-schema issue, not a logic bug, at least once.
3. Check for a corrupted `ticket_type` on any ticket that might be crashing the sweep tick before it reaches the ticket you actually care about (a real historical failure mode, since fixed for the specific cause found — but worth ruling out again if it recurs with new data).

## A specific business rule "isn't working" (e.g. an OTP rule, a notification)

Check the rule/policy's own configuration for an exact-match condition that's silently too narrow (e.g. a `client` condition scoped to the wrong client) before assuming the underlying mechanism is broken — this has been the actual root cause more than once.

## Escalating within the team

No documented escalation path/on-call rotation was found in the repository — this is organizational information outside what source code can confirm. Establish and document one if it doesn't already exist elsewhere.

## After the incident

Update the relevant [14-troubleshooting](../14-troubleshooting/README.md) document with the new symptom/cause/fix — this documentation set's own value depends on that habit continuing.
