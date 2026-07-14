"""add TICKET_CLOSED and TICKET_REOPENED to audit_event_type_enum

Revision ID: f2e2950742ad
Revises: a2c4e6f8b0d3
Create Date: 2026-07-15 00:00:00.000000

Closing/reopening a ticket used to be logged as a generic
STATUS_CHANGED event (the CLOSED-ness recoverable only by inspecting
old_values/new_values.current_status). Now that Close/Reopen are their
own dedicated actions (InteractionService.close_ticket/reopen_ticket),
they get their own AuditEventType members so the audit trail and
synthesized Timeline row can label them distinctly instead of as a
plain status change.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2e2950742ad'
down_revision: Union[str, None] = 'a2c4e6f8b0d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that uses the new value, but each can run
    # on its own — Postgres 12+ allows this without AUTOCOMMIT as long
    # as it's the only DDL in the transaction, which it is here.
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'TICKET_CLOSED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'TICKET_REOPENED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — removing a label requires
    # rebuilding the type, which isn't worth it for a downgrade path.
    # Left as a no-op, matching the project's other enum-widening
    # migrations.
    pass
