"""drop snoozed_until from interactions

Revision ID: c3e5a7f9b1d4
Revises: a7c9e1f3d5b8
Create Date: 2026-07-11 00:00:02.000000

The Snooze mail feature was removed end-to-end earlier (backend
routes, service methods, repository methods, frontend UI) but this
column was deliberately left in place at the time as a precaution.
Confirmed by a fresh repo-wide check: no route, service method,
repository filter, or UI anywhere reads or writes it today — the only
remaining references were two read-only passthroughs into response
schemas that no frontend surface ever displayed. Safe to drop.

Irreversible (the column's historical values, whatever they were, are
gone after this) but low-risk — nothing currently depends on this
data, unlike the retired-interaction-types cleanup which had a
verified audit-log backup.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3e5a7f9b1d4'
down_revision: Union[str, None] = 'a7c9e1f3d5b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_interactions_snoozed_until", table_name="interactions")
    op.drop_column("interactions", "snoozed_until")


def downgrade() -> None:
    import sqlalchemy as sa

    op.add_column(
        "interactions",
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_interactions_snoozed_until", "interactions", ["snoozed_until"]
    )
