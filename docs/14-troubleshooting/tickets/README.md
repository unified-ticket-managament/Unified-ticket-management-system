# Troubleshooting: Tickets

## Problem: `TKT-<n>` numbers look wrong (huge gaps, or out of creation order)

**Symptoms**: A small number of real tickets show `TKT-01`...`TKT-06` then jump to something like `TKT-187`.

**Possible Causes**: The original `ticket_number_seq` backfill migration ranked every row present **at the moment it ran** — if that included since-deleted test/dev tickets, real tickets can inherit oddly large numbers reflecting that historical population, not the current one.

**Resolution** (already applied once): A one-time re-normalization migration (`c4d6e8f0a2b4_renumber_tickets_contiguous`) re-ranks the *current* live population only and resets the sequence. This has no meaningful `downgrade()` — treat it as a one-way data fix if it's ever needed again.

**Prevention**: `test_ticket_number.py`'s whole-table invariant test (`test_every_existing_ticket_number_rank_matches_creation_order`) guards against this recurring — it deliberately doesn't assert "zero gaps," since real ticket deletion is expected to reintroduce gaps legitimately.

**Related Documentation**: [06-database/migrations.md](../../06-database/migrations.md), [03-business-workflows/ticket/ticket-creation.md](../../03-business-workflows/ticket/ticket-creation.md).

---

## Problem: A ticket's attachment upload silently never authorizes correctly (historical)

**Symptoms** (fixed, historical): Any authenticated agent could upload to any ticket, regardless of category/client ownership.

**Possible Causes**: `AttachmentService.upload_attachment`'s authorization check was called without `await` — an async coroutine created and immediately discarded, silently never executing.

**Resolution**: Fixed during the 2026-07-14/15 RBAC compliance audit; `test_attachment_upload_authorization.py` now guards against a regression.

**Prevention**: When reviewing new code calling an `async def` authorization check, confirm `await` is present — this class of bug produces no error and no obvious symptom, only a silent security gap.

**Related Documentation**: [11-testing/regression-testing.md](../../11-testing/regression-testing.md), [15-architecture-decisions](../../15-architecture-decisions/README.md).

---

## Potential Issue: `Ticket.client_id` vs. `Ticket.client_company_id` confusion

**Symptoms**: New code referencing "the ticket's client" gets unexpected `None`/mismatched results.

**Possible Causes**: Both a legacy `client_id` (FK→`users`) and the current `client_company_id` (FK→`clients`) exist on the same model — this documentation pass could not fully confirm which is considered authoritative for all current code paths.

**How to Diagnose**: Grep for both fields in the specific service you're working in before assuming either is populated/authoritative.

**Related Documentation**: [06-database/er-diagram.md](../../06-database/er-diagram.md).
