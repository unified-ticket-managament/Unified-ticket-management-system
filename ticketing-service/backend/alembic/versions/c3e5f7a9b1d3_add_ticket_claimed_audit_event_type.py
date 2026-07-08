"""add TICKET_CLAIMED to audit_event_type_enum

Revision ID: c3e5f7a9b1d3
Revises: d4f6a8b0c2e4
Create Date: 2026-07-08 00:00:00.000000

claim_ticket previously reused AGENT_TRANSFERRED for its audit log entry,
making a self-service claim indistinguishable from a supervisor-initiated
transfer in the Audit Log UI. This migration only adds the new label;
nothing to backfill since no rows could have used it before.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3e5f7a9b1d3'
down_revision: Union[str, None] = 'd4f6a8b0c2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but it can run on
    # its own — Postgres 12+ allows this without AUTOCOMMIT as long as
    # it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'TICKET_CLAIMED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label
    # requires rebuilding the type, which isn't worth it for a
    # downgrade path. Left as a no-op, matching the project's other
    # enum-widening migrations.
    pass
