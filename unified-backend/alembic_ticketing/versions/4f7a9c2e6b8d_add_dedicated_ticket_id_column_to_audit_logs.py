"""add dedicated indexed ticket_id column to ticket_audit_logs, backfill, retire JSONB-extraction index

Revision ID: 4f7a9c2e6b8d
Revises: 9d2e4f6a8c1b
Create Date: 2026-07-13 00:00:00.000000

Production-scale follow-up to the functional index added earlier
(`ix_audit_new_values_ticket_id`, migration 6a1d3f5b7c9e). That index
works and is proven via EXPLAIN, but at millions of rows a real column
is strictly better: native UUID equality (not a JSONB ->> text
extraction/compare) on every read, a real FK for referential
integrity, and no per-row expression evaluation to maintain the index
on every write. `new_values` (the full audit detail JSONB) is left
completely untouched — this column is purely an additive, derived
mirror of data that's already there, kept in sync going forward by
AuditLogRepository.create().

Backfill logic (matches AuditLogRepository.create()'s new derivation
exactly): entity_type='TICKET' rows use their own entity_id; every
other row uses new_values->>'ticket_id' if present and shaped like a
UUID; CLIENT/USER rows (never ticket-related) stay NULL.

Safe with no downtime: additive column (NULL default), backfill is a
single UPDATE guarded to only touch rows that need it, and the old
functional index is dropped only after the new column/index exist
and the read path (list_by_ticket/list_by_ticket_ids) no longer
depends on it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4f7a9c2e6b8d'
down_revision: Union[str, None] = '9d2e4f6a8c1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ticket_audit_logs",
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_ticket_audit_logs_ticket_id",
        "ticket_audit_logs",
        "tickets",
        ["ticket_id"],
        ["ticket_id"],
    )

    # Backfill from existing data — deterministic, no ambiguity:
    # TICKET rows carry the ticket id as their own entity_id; every
    # other entity_type stamps it into new_values (when applicable).
    # The regex guard mirrors the fact that `.astext` values here were
    # always written by this app's own str(uuid) calls — this is a
    # defensive backstop for the migration, not a behavior change.
    op.execute(
        """
        UPDATE ticket_audit_logs
        SET ticket_id = CASE
            WHEN entity_type = 'TICKET' THEN entity_id
            WHEN new_values ? 'ticket_id'
                 AND (new_values ->> 'ticket_id') ~
                     '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                THEN (new_values ->> 'ticket_id')::uuid
            ELSE NULL
        END
        WHERE ticket_id IS NULL
        """
    )

    op.create_index(
        "idx_audit_ticket_id",
        "ticket_audit_logs",
        ["ticket_id", sa.text("created_at DESC")],
    )

    # Superseded by the real column + index above — the read path
    # (AuditLogRepository.list_by_ticket/list_by_ticket_ids) is updated
    # in this same change to query `ticket_id` directly, so this index
    # has no remaining reader.
    op.execute("DROP INDEX IF EXISTS ix_audit_new_values_ticket_id")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX ix_audit_new_values_ticket_id "
        "ON ticket_audit_logs ((new_values->>'ticket_id'))"
    )
    op.drop_index("idx_audit_ticket_id", table_name="ticket_audit_logs")
    op.drop_constraint(
        "fk_ticket_audit_logs_ticket_id", "ticket_audit_logs", type_="foreignkey"
    )
    op.drop_column("ticket_audit_logs", "ticket_id")
