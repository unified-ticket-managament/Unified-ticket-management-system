"""add app_settings table (runtime settings, first key: read receipts)

Revision ID: f7a9c1e3b5d8
Revises: e5b7d9f1a3c8
Create Date: 2026-10-06 00:00:00.000001

Purely additive: one small key/value table. No row is inserted, so every
setting starts at its documented default (Read Receipts: OFF) until an
administrator changes it from the Settings UI.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f7a9c1e3b5d8"
down_revision: Union[str, None] = "e5b7d9f1a3c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
