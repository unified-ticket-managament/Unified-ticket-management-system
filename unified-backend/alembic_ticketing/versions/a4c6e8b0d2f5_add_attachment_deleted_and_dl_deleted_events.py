"""add ATTACHMENT_DELETED and DISTRIBUTION_LIST_DELETED audit event types

Revision ID: a4c6e8b0d2f5
Revises: e5a2c4f6b8d1
Create Date: 2026-08-29 00:00:00.000000

Two audit-coverage gaps closed together (see root CLAUDE.md's
audit-log separation section): AttachmentService.delete_attachment and
DistributionListService.delete both previously deleted their row with
no audit trail at all, unlike every sibling mutation on the same
entity type (ATTACHMENT_UPLOADED, DISTRIBUTION_LIST_CREATED/UPDATED/
MEMBER_ADDED/MEMBER_REMOVED/DEACTIVATED), which are all already
logged. The Python AuditEventType enum gained both new members —
the actual Postgres enum type (audit_event_type_enum) must be altered
to match, or the first call using either new value would 500 with an
invalid-enum-label error. Adds the new labels only; nothing to
backfill. Mirrors d6f8b0a2e4c7's exact pattern.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a4c6e8b0d2f5'
down_revision: Union[str, None] = 'e5a2c4f6b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'ATTACHMENT_DELETED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'DISTRIBUTION_LIST_DELETED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — left as a no-op, matching
    # every other enum-widening migration in this chain (e.g. d6f8b0a2e4c7).
    pass
