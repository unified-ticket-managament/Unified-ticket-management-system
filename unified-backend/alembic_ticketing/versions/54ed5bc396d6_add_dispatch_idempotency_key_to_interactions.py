"""add dispatch idempotency key to interactions

Revision ID: 54ed5bc396d6
Revises: 0941a80891de
Create Date: 2026-08-25 00:00:00.000000

Client-generated idempotency key for Send/Retry-Send (Compose/Reply/
Reply-All/Forward) — a repeated request with the same key returns the
existing interaction instead of creating a second one. Scoped
(performed_by, dispatch_idempotency_key) via a partial unique index
(only rows with a non-NULL key are constrained) rather than a bare
global unique column, so one user's key can never collide with (or be
guessed to read) another user's interaction — the same "this is your
own action" scoping cancel_pending_send already uses.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54ed5bc396d6'
down_revision: Union[str, None] = '0941a80891de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interactions",
        sa.Column("dispatch_idempotency_key", sa.String(length=255), nullable=True),
    )

    op.create_index(
        "ux_interactions_performed_by_idempotency_key",
        "interactions",
        ["performed_by", "dispatch_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("dispatch_idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_interactions_performed_by_idempotency_key", table_name="interactions"
    )
    op.drop_column("interactions", "dispatch_idempotency_key")
