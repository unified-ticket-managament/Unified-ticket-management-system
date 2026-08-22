"""add shared_user_ids to rules

Revision ID: a1b3c5d7e9f2
Revises: f6b8d0a2c4e6
Create Date: 2026-08-22 00:00:00.000001

Backs the new Mail/OTP Rule ownership + visibility model: a rule with
an empty `shared_user_ids` is private to its own `created_by`; adding
a user's id here (via the Rule Builder's "Shared With" picker) grants
that user the same view/manage access as the owner. Purely additive —
existing rows all get `[]`, which is exactly correct under the new
model (a pre-existing rule becomes private to whoever created it,
matching this feature's own stated business rule that an empty list
means private, never "visible to everyone").
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b3c5d7e9f2'
down_revision: Union[str, None] = 'f6b8d0a2c4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rules",
        sa.Column(
            "shared_user_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("rules", "shared_user_ids")
