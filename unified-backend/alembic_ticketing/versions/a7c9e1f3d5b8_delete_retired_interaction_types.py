"""backfill-delete retired interaction types

Revision ID: a7c9e1f3d5b8
Revises: f1a3c5e7b9d2
Create Date: 2026-07-11 00:00:01.000000

One-time cleanup: STATUS_CHANGE/PRIORITY_CHANGE/AGENT_TRANSFER/CLAIM/
EDIT_ACCESS_REQUESTED/EDIT_ACCESS_APPROVED/EDIT_ACCESS_REJECTED no
longer get created as Interaction rows (see
services/audit_to_interaction.py) — their data is already fully
preserved in ticket_audit_logs, and the Timeline/Interactions-list
endpoints synthesize a display row back from that audit trail. This
removes the now-redundant historical rows.

ATTACHMENT is deliberately excluded — Attachment.interaction_id is a
plain FK with no ON DELETE CASCADE, and ticket_audit_logs'
ATTACHMENT_UPLOADED rows don't carry storage_key/bucket_name (the
only way to ever generate a presigned download URL again). Deleting
ATTACHMENT rows would either fail outright (FK violation, wherever a
real file was ever uploaded) or silently orphan real files. ATTACHMENT
rows stay in `interactions` forever — they simply stop being created,
same as the other 5, just not backfill-deleted.

This migration is irreversible by design — do not run it until the
code change that stopped creating these rows (and the Timeline-merge
synthesis that replaces them) has been live and verified for a full
deploy cycle with no rollback. See root CLAUDE.md's guidance on
irreversible destructive DB operations before running this against
any environment with real data — confirm explicitly, and consider a
dry-run COUNT first.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c9e1f3d5b8'
down_revision: Union[str, None] = 'f1a3c5e7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM interactions
        WHERE interaction_type IN (
            'STATUS_CHANGE', 'PRIORITY_CHANGE', 'AGENT_TRANSFER',
            'CLAIM', 'EDIT_ACCESS_REQUESTED', 'EDIT_ACCESS_APPROVED',
            'EDIT_ACCESS_REJECTED'
        )
        """
    )
    # ATTACHMENT excluded — see module docstring.


def downgrade() -> None:
    raise NotImplementedError(
        "This is a one-time destructive cleanup; the deleted rows' data "
        "is preserved in ticket_audit_logs, not recoverable back into "
        "interactions. There is no downgrade path by design."
    )
