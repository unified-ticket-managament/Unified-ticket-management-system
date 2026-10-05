"""add message_marks table for per-user Flag / Pin

Revision ID: 9e3a5c7b2d4f
Revises: 8d2f4b6a1c3e
Create Date: 2026-10-05 00:00:00.000001

Purely additive: a brand-new table, no changes to any existing table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '9e3a5c7b2d4f'
down_revision: Union[str, None] = '8d2f4b6a1c3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_marks",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["interaction_id"], ["interactions.interaction_id"]),
        sa.PrimaryKeyConstraint("user_id", "interaction_id"),
    )
    op.create_index(
        "idx_message_marks_interaction_id",
        "message_marks",
        ["interaction_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_message_marks_interaction_id", table_name="message_marks")
    op.drop_table("message_marks")
