"""add is_bounce to interactions

Revision ID: 96ab43631616
Revises: 54ed5bc396d6
Create Date: 2026-08-25 10:48:55.844459

Phase 2 hardening: bounce/NDR detection (see
app/ticketing/services/bounce_detection.py, EmailService._receive_
bounce). A real column, not payload-only, matching this table's own
existing convention for a field a query filters on directly (see
Interaction.client_id's docstring) — though today nothing queries it
independently; it exists to distinguish these rows for anyone
inspecting the table directly. server_default keeps every pre-existing
row (all real correspondence, since this feature didn't exist before)
correctly False with no backfill needed.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '96ab43631616'
down_revision: Union[str, None] = '54ed5bc396d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interactions",
        sa.Column("is_bounce", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("interactions", "is_bounce")