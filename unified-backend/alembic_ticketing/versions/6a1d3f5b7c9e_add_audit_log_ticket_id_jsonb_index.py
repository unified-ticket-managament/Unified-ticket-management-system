"""add functional index on ticket_audit_logs.new_values->>'ticket_id'

Revision ID: 6a1d3f5b7c9e
Revises: 5c8a2f4e6d91
Create Date: 2026-07-12 00:00:00.000000

AuditLogRepository.list_by_ticket/list_by_ticket_ids (the Interactions
page and every ticket's Timeline tab both call one of these on every
load) filter on `AuditLog.new_values["ticket_id"].astext`, a JSONB
text-extraction expression none of this table's existing indexes
(entity_type/entity_id, actor_id, event_type) cover — every such query
was a full sequential scan of ticket_audit_logs. A plain functional
B-tree index on the extracted expression lets Postgres index-scan the
same `->> 'ticket_id' = / IN (...)` predicate instead. Purely additive,
no data changes, safe with no downtime.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6a1d3f5b7c9e'
down_revision: Union[str, None] = '5c8a2f4e6d91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_audit_new_values_ticket_id "
        "ON ticket_audit_logs ((new_values->>'ticket_id'))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_audit_new_values_ticket_id")
