"""add mail_reminders table for per-user "Remind me" on a mail thread

Revision ID: 0c6db321ee79
Revises: 444b9869dc1b
Create Date: 2026-10-07 00:00:00.000001

Purely additive: a brand-new table, no changes to any existing table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0c6db321ee79'
down_revision: Union[str, None] = '444b9869dc1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mail_reminders",
        sa.Column("reminder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("snooze_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["interactions.interaction_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("reminder_id"),
    )
    op.create_index(
        "uq_mail_reminders_active_user_interaction",
        "mail_reminders",
        ["user_id", "interaction_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "idx_mail_reminders_active_remind_at",
        "mail_reminders",
        ["remind_at"],
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "idx_mail_reminders_user_status",
        "mail_reminders",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_mail_reminders_user_status", table_name="mail_reminders")
    op.drop_index("idx_mail_reminders_active_remind_at", table_name="mail_reminders")
    op.drop_index(
        "uq_mail_reminders_active_user_interaction", table_name="mail_reminders"
    )
    op.drop_table("mail_reminders")
