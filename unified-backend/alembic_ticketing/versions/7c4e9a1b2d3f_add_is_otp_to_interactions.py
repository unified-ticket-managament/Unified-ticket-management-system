"""add is_otp to interactions

Revision ID: 7c4e9a1b2d3f
Revises: 02d1308a9f3c
Create Date: 2026-10-02 12:00:00.000000

Backs the Mail "OTPs" section: persists the existing semantic OTP
classifier's result (app/ticketing/services/otp_classifier.py) on each
inbound EMAIL interaction, so the Inbox can exclude OTP roots and the
OTP view can select them in SQL, before pagination. See
Interaction.is_otp's own docstring.

server_default keeps every pre-existing row False — no backfill runs
here. Historical rows are classified separately, and only on explicit
request, by scripts/backfill_interaction_is_otp.py.

The partial index covers the OTP view's own query shape (OTP thread
roots ordered by received_at) and stays tiny, since only OTP rows are
indexed.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c4e9a1b2d3f'
down_revision: Union[str, None] = '02d1308a9f3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interactions",
        sa.Column("is_otp", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_interactions_otp_roots_received_at",
        "interactions",
        ["received_at"],
        postgresql_where=sa.text("is_otp AND parent_interaction_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_interactions_otp_roots_received_at", table_name="interactions")
    op.drop_column("interactions", "is_otp")
