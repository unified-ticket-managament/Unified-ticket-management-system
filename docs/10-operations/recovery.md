# Recovery

Recovery procedures for the specific incident classes this system has actually experienced, per its own documented history — not a generic disaster-recovery template.

## Stale/phantom backend process (Windows)

1. `Get-Process | Where-Object {$_.ProcessName -match "python|uvicorn"} | Stop-Process -Force` — kill **every** python/uvicorn process, not just the PID(s) the last `uvicorn` invocation printed.
2. Wait a few seconds, then confirm: `Get-NetTCPConnection -LocalPort 8000` (or the relevant port) returns nothing.
3. Start exactly one fresh process.
4. Confirm its start time postdates any file you expect it to have picked up.
5. Mint a real token and hit the actual route with `curl`/`httpx` (including the `Origin` header a browser would send) — not just the service method directly, which bypasses routing/CORS.

## `[WinError 10013]` on `uvicorn --reload` startup

Almost always means a previous process is still bound to the port, not a real permissions/firewall issue. `Get-NetTCPConnection -LocalPort 8000` to find the owning PID, cross-check it's a genuine process via `Get-Process -Id <pid>` (not a phantom stale entry), then follow the kill sequence above.

## Escalation/SLA data drift (CRITICAL priority missing on an escalated ticket)

There is **no ongoing reconciliation** between `Ticket.current_priority` and `ticket_escalations` — if the CRITICAL-bump logic is ever temporarily broken, a manual one-off backfill (query every escalated ticket not already CRITICAL, load via the ORM, call `EscalationService._bump_priority_to_critical` directly — reusing the real reshift+audit-log code path, not a hand-written `UPDATE`) is the documented recovery method, per how this was actually done once in this system's history.

## Corrupted `ticket_type` blocking the sweep

Identify the offending ticket (a `ticket_type` string not matching any real `CategoryName`) via direct query, and either correct or clear its value. The underlying validation gap (an invalid category crashing the query instead of degrading to "no one to find") has been fixed at the code level for this specific cause — but if a *new* error class produces the same "one ticket blocks the whole sweep tick" symptom, the per-ticket `SAVEPOINT` isolation is confirmed **not** to be a universal guarantee against every Postgres error class.

## Employee/user data cleanup (a precedent, not a routine procedure)

If a similar cleanup is ever needed again: **query Postgres's own `information_schema.key_column_usage`/`referential_constraints` catalogs directly to enumerate every foreign-key column referencing `users.user_id`** before attempting bulk deletes — a manual checklist missed one FK (`message_read_receipts.user_id`) the last time this was done, and self-referential FKs (`manager_id`/`teamlead_id` within the same deletion batch) need nulling before the per-row deletes, not after.

## Recovering from a bad migration

See [09-deployment/rollback.md](../09-deployment/rollback.md) — several migrations in this codebase have no meaningful `downgrade()`; check each one between current head and the target rollback point before running `alembic downgrade` blindly.
