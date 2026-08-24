"""add shared_distribution_list_ids to rules

Revision ID: b2d4f6a8c0e3
Revises: e61eab76fb7d
Create Date: 2026-08-24 00:00:00.000001

Extends the Mail/OTP Rule "Shared With" model (see the shared_user_ids
migration, a1b3c5d7e9f2) to also accept Distribution Lists: any
current, active member of a list named here gets the same view/manage
access a directly-shared employee gets, resolved fresh on every
request rather than snapshotted. Purely additive — existing rows all
get `[]`, identical to today's "no Distribution List sharing"
behavior.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c0e3'
down_revision: Union[str, None] = 'e61eab76fb7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rules",
        sa.Column(
            "shared_distribution_list_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("rules", "shared_distribution_list_ids")
