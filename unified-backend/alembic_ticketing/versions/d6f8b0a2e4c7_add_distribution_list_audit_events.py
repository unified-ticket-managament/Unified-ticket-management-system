"""add DISTRIBUTION_LIST entity type and its audit event types

Revision ID: d6f8b0a2e4c7
Revises: c5e7a9f1d3b6
Create Date: 2026-08-22 00:00:00.000003

The Python AuditEntityType/AuditEventType enums gained a new
DISTRIBUTION_LIST entity type and five new event types for the
Distribution List feature (create/update/member-add/member-remove/
deactivate) — the actual Postgres enum types (audit_entity_type_enum,
audit_event_type_enum) must be altered to match, or the first
DistributionListService mutation would 500 with an invalid-enum-label
error. Adds the new labels only; nothing to backfill.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd6f8b0a2e4c7'
down_revision: Union[str, None] = 'c5e7a9f1d3b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_entity_type_enum ADD VALUE IF NOT EXISTS 'DISTRIBUTION_LIST'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'DISTRIBUTION_LIST_CREATED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'DISTRIBUTION_LIST_UPDATED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'DISTRIBUTION_LIST_MEMBER_ADDED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'DISTRIBUTION_LIST_MEMBER_REMOVED'")
    op.execute("ALTER TYPE audit_event_type_enum ADD VALUE IF NOT EXISTS 'DISTRIBUTION_LIST_DEACTIVATED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — left as a no-op, matching
    # every other enum-widening migration in this chain (e.g. b3d5f7a9c1e2).
    pass
