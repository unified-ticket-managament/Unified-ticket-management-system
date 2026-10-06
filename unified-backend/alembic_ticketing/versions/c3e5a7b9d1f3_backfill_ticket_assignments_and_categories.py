"""backfill ticket_assignments / ticket_categories / ticket_assignment_slas

Revision ID: c3e5a7b9d1f3
Revises: b2d4f6a8c0e2
Create Date: 2026-10-06 00:00:00.000003

Data-only, idempotent (every INSERT is guarded by NOT EXISTS, so a
re-run inserts nothing twice):

1. tickets.agent_id  -> one PRIMARY ticket_assignments row carrying the
   ticket's current_status (closed_at/closed_by copied for CLOSED
   tickets). assigned_at = the newest AGENT_TRANSFERRED/TICKET_CLAIMED
   audit row that put this agent on the ticket, else the ticket's
   created_at.
2. tickets.ticket_type -> one PRIMARY ticket_categories row, matched by
   categories.category_name (a ticket whose ticket_type matches no
   category simply gets no row — ticket_type itself is untouched).
3. The ticket's own resolution_slas row -> run 1 of the primary
   assignment's ticket_assignment_slas, copied field-for-field so the
   existing single assignee's SLA state is exactly equivalent. Forced
   COMPLETED for a CLOSED ticket (a closed ticket must never carry a
   live assignment clock).

No existing table/column is modified. downgrade() removes only the rows
this migration could have created (all rows, since the tables were
created empty one revision earlier).
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'c3e5a7b9d1f3'
down_revision: Union[str, None] = 'b2d4f6a8c0e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BACKFILL_ASSIGNMENTS_SQL = """
        INSERT INTO ticket_assignments (
            assignment_id, ticket_id, user_id, is_primary, status,
            assigned_by, assigned_at, status_changed_at,
            closed_at, closed_by, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), t.ticket_id, t.agent_id, true, t.current_status,
            t.assigned_by,
            COALESCE(
                (
                    SELECT max(a.created_at)
                    FROM ticket_audit_logs a
                    WHERE a.ticket_id = t.ticket_id
                      AND a.event_type IN ('AGENT_TRANSFERRED', 'TICKET_CLAIMED')
                      AND a.new_values ->> 'agent_id' = t.agent_id::text
                ),
                t.created_at
            ),
            NULL,
            CASE WHEN t.current_status = 'CLOSED' THEN t.closed_at END,
            CASE WHEN t.current_status = 'CLOSED' THEN t.closed_by END,
            now(), now()
        FROM tickets t
        WHERE t.agent_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM ticket_assignments x
              WHERE x.ticket_id = t.ticket_id AND x.removed_at IS NULL
          )
        """

BACKFILL_CATEGORIES_SQL = """
        INSERT INTO ticket_categories (
            ticket_category_id, ticket_id, category_id, is_primary,
            assigned_by, assigned_at, updated_at
        )
        SELECT gen_random_uuid(), t.ticket_id, c.category_id, true,
               NULL, t.created_at, now()
        FROM tickets t
        JOIN categories c ON c.category_name = t.ticket_type
        WHERE NOT EXISTS (
            SELECT 1 FROM ticket_categories x WHERE x.ticket_id = t.ticket_id
        )
        """

BACKFILL_ASSIGNMENT_SLAS_SQL = """
        INSERT INTO ticket_assignment_slas (
            assignment_sla_id, assignment_id, ticket_id, user_id, run_number,
            priority, status, started_at, due_at, active_target_minutes,
            paused_at, total_paused_seconds, completed_at, completion_reason,
            breached_at, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), ta.assignment_id, ta.ticket_id, ta.user_id, 1,
            r.priority,
            CASE WHEN t.current_status = 'CLOSED' THEN 'COMPLETED'::sla_clock_status_enum
                 ELSE r.status END,
            r.started_at, r.due_at, r.active_target_minutes,
            CASE WHEN t.current_status = 'CLOSED' THEN NULL ELSE r.paused_at END,
            r.total_paused_seconds,
            CASE WHEN t.current_status = 'CLOSED'
                 THEN COALESCE(r.completed_at, t.closed_at, now())
                 ELSE r.completed_at END,
            CASE
                WHEN t.current_status = 'CLOSED' THEN 'TICKET_CLOSED'
                WHEN r.status = 'COMPLETED' THEN 'RESOLVED'
            END,
            CASE WHEN r.due_at < COALESCE(r.completed_at, now())
                      AND r.status <> 'PAUSED'
                 THEN r.due_at END,
            now(), now()
        FROM ticket_assignments ta
        JOIN tickets t ON t.ticket_id = ta.ticket_id
        JOIN resolution_slas r ON r.ticket_id = ta.ticket_id
        WHERE ta.is_primary AND ta.removed_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM ticket_assignment_slas x WHERE x.assignment_id = ta.assignment_id
          )
        """

# Module-level so tests/test_multi_assignment.py can run exactly this SQL
# against a legacy-shaped ticket inside its own rolled-back transaction.
BACKFILL_STATEMENTS = (BACKFILL_ASSIGNMENTS_SQL, BACKFILL_CATEGORIES_SQL, BACKFILL_ASSIGNMENT_SLAS_SQL)


def upgrade() -> None:
    for statement in BACKFILL_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DELETE FROM ticket_assignment_slas")
    op.execute("DELETE FROM ticket_categories")
    op.execute("DELETE FROM ticket_assignments")
