"""add escalation handling slas

Revision ID: d33a0758e3c4
Revises: b3d5f7a9c1e2
Create Date: 2026-07-14 07:10:29.340732

NOTE: this file was hand-trimmed after autogenerate. The raw
`--autogenerate` diff also proposed dropping several unrelated
indexes/columns on `interactions`/`tickets` (ix_tickets_updated_at,
ix_tickets_pool_view, ix_tickets_title_trgm, the interactions inbox/
subject-trgm indexes, and interactions.snoozed_until) — all genuine,
deliberately-added prior work (see root CLAUDE.md's performance-pass
notes) that simply isn't declared in the current SQLAlchemy models
(raw-SQL indexes and an already-dropped column the model still
mapped). That drift is real but predates and is unrelated to this
migration; removed those statements from both upgrade()/downgrade()
here rather than silently dropping working indexes as a side effect
of an unrelated feature migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd33a0758e3c4'
down_revision: Union[str, None] = 'b3d5f7a9c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# sla_clock_status_enum already exists (created by an earlier
# migration) — create_type=False so this table's column reuses it
# instead of trying (and failing, DuplicateObject) to CREATE TYPE
# again, same fix as every other table that reuses this enum.
_SLA_CLOCK_STATUS_ENUM = postgresql.ENUM(
    "PENDING", "RUNNING", "PAUSED", "COMPLETED",
    name="sla_clock_status_enum",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        'escalation_handling_slas',
        sa.Column('escalation_handling_sla_id', sa.UUID(), nullable=False),
        sa.Column('escalation_id', sa.UUID(), nullable=False),
        sa.Column('ticket_id', sa.UUID(), nullable=False),
        sa.Column('status', _SLA_CLOCK_STATUS_ENUM, nullable=False),
        sa.Column('target_seconds', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('breached_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['escalation_id'], ['ticket_escalations.escalation_id']),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.ticket_id']),
        sa.PrimaryKeyConstraint('escalation_handling_sla_id'),
    )
    op.create_index(
        op.f('ix_escalation_handling_slas_due_at'),
        'escalation_handling_slas', ['due_at'], unique=False,
    )
    op.create_index(
        op.f('ix_escalation_handling_slas_escalation_id'),
        'escalation_handling_slas', ['escalation_id'], unique=True,
    )
    op.create_index(
        op.f('ix_escalation_handling_slas_status'),
        'escalation_handling_slas', ['status'], unique=False,
    )
    op.create_index(
        'ix_escalation_handling_slas_status_due_at',
        'escalation_handling_slas', ['status', 'due_at'], unique=False,
    )
    op.create_index(
        op.f('ix_escalation_handling_slas_ticket_id'),
        'escalation_handling_slas', ['ticket_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_escalation_handling_slas_ticket_id'),
        table_name='escalation_handling_slas',
    )
    op.drop_index(
        'ix_escalation_handling_slas_status_due_at',
        table_name='escalation_handling_slas',
    )
    op.drop_index(
        op.f('ix_escalation_handling_slas_status'),
        table_name='escalation_handling_slas',
    )
    op.drop_index(
        op.f('ix_escalation_handling_slas_escalation_id'),
        table_name='escalation_handling_slas',
    )
    op.drop_index(
        op.f('ix_escalation_handling_slas_due_at'),
        table_name='escalation_handling_slas',
    )
    op.drop_table('escalation_handling_slas')
