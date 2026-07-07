---
name: add-postgres-enum-value
description: Add a new value to one of this repo's Python enums that map to a native Postgres ENUM column (AuditEventType, AuditEntityType, ActorRole, TicketStatus, TicketPriority, InteractionStatus, InteractionDirection). Use whenever a task adds a new status/type/event-type constant, since editing the Python enum alone is not enough and will crash in production.
---

# Add a value to a Postgres-backed enum

Several enums in `backend/app/enums/` are mapped via SQLAlchemy's `SQLEnum(EnumClass, name="...")`,
which creates (and constrains column values to) a **native Postgres ENUM type** — not just a
CHECK constraint on a string column. Editing the Python `Enum` class is necessary but not
sufficient: the deployed database's enum type must be widened too, or the first `INSERT`/`UPDATE`
using the new value crashes with `InvalidTextRepresentationError`.

Enums that need this treatment (grep `SQLEnum(` under `backend/app/models/` to confirm the
current list): `AuditEventType` → `audit_event_type_enum`, `AuditEntityType` →
`audit_entity_type_enum`, `ActorRole` → `audit_actor_role_enum`, `TicketStatus` →
`ticket_status_enum`, `TicketPriority` → `ticket_priority_enum`, `InteractionStatus` →
`interaction_status_enum`, `InteractionDirection` → `interaction_direction_enum`.
`interaction_type` on `Interaction` is a plain `String` column, NOT one of these — free-form
values need no migration. `TicketCategory` (`app/enums/ticket_enums.py`, constraining
`Ticket.ticket_type`) is a deliberate counter-example: it's a plain Python enum used only
for Pydantic request validation, not wired into the column via `SQLEnum` — extending its
value list needs no migration either. Don't convert it to a `SQLEnum` without a real reason;
that would turn a migration-free constant list into one that needs this skill every time.

## Steps

1. Add the new member to the Python enum class in `backend/app/enums/*.py`.
2. Find the enum's Postgres type name from its model's `SQLEnum(..., name="...")` call.
3. Create a new Alembic migration in `backend/alembic/versions/` with `down_revision` set to
   the current head (check via `alembic history` or `alembic heads`). Copy
   `backend/alembic/versions/7a2d4e9f1c3b_add_email_received_audit_event_type.py` verbatim as
   the template:

   ```python
   def upgrade() -> None:
       # ALTER TYPE ... ADD VALUE cannot run inside the same transaction as a later
       # statement that uses the new value, but it can run on its own.
       op.execute("ALTER TYPE <enum_type_name> ADD VALUE IF NOT EXISTS '<NEW_VALUE>'")

   def downgrade() -> None:
       # Postgres has no DROP VALUE for enums — left as a no-op.
       pass
   ```
4. Mirror the new value into the corresponding frontend TypeScript union in
   `frontend/src/types/index.ts` (e.g. `AuditEventType`, `TicketStatus`) if the frontend
   references it.
5. If it's an `AuditEventType` or interaction-timeline-visible status, add a matching entry to
   `frontend/src/lib/auditLogMeta.ts` and/or `frontend/src/lib/interactionMeta.ts` so it renders
   with a proper icon/label instead of a generic fallback.

## Verification

- `alembic history` — confirm the new migration is the head and chains from the correct
  `down_revision` (no forked history).
- `alembic upgrade head` against the target database — confirm it applies cleanly.
- Query `pg_enum`/`pg_type` to confirm the label landed:
  ```sql
  SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid
  WHERE t.typname = '<enum_type_name>' ORDER BY e.enumsortorder;
  ```
- Only after the migration is applied, exercise the code path that writes the new value.
