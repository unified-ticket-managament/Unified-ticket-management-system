"""add ticket_assignments, ticket_categories, ticket_assignment_slas

Revision ID: b2d4f6a8c0e2
Revises: a1c3e5f7b9d1
Create Date: 2026-10-06 00:00:00.000002

Purely additive: three brand-new tables, no change to any existing
table or column. tickets.agent_id / assigned_by / ticket_type /
current_status stay exactly as they are and become compatibility
projections of these tables (see TicketAssignment's docstring).
Backfill lives in the next migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2d4f6a8c0e2'
down_revision: Union[str, None] = 'a1c3e5f7b9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ticket_status_enum = postgresql.ENUM(name="ticket_status_enum", create_type=False)
ticket_priority_enum = postgresql.ENUM(name="ticket_priority_enum", create_type=False)
sla_clock_status_enum = postgresql.ENUM(name="sla_clock_status_enum", create_type=False)


def upgrade() -> None:
    op.create_table(
        "ticket_assignments",
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", ticket_status_enum, nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.ticket_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["closed_by"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["removed_by"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("assignment_id"),
    )
    op.create_index("ix_ticket_assignments_ticket_id", "ticket_assignments", ["ticket_id"])
    op.create_index(
        "uq_ticket_assignments_active_user",
        "ticket_assignments",
        ["ticket_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "uq_ticket_assignments_one_active_primary",
        "ticket_assignments",
        ["ticket_id"],
        unique=True,
        postgresql_where=sa.text("is_primary AND removed_at IS NULL"),
    )
    op.create_index(
        "ix_ticket_assignments_active_user_status",
        "ticket_assignments",
        ["user_id", "status"],
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.create_table(
        "ticket_categories",
        sa.Column("ticket_category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.ticket_id"]),
        sa.ForeignKeyConstraint(["category_id"], ["categories.category_id"]),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("ticket_category_id"),
        sa.UniqueConstraint("ticket_id", "category_id", name="uq_ticket_categories_ticket_category"),
    )
    op.create_index("ix_ticket_categories_ticket_id", "ticket_categories", ["ticket_id"])
    op.create_index("ix_ticket_categories_category_id", "ticket_categories", ["category_id"])
    op.create_index(
        "uq_ticket_categories_one_primary",
        "ticket_categories",
        ["ticket_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "ticket_assignment_slas",
        sa.Column("assignment_sla_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("priority", ticket_priority_enum, nullable=False),
        sa.Column("status", sla_clock_status_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_target_minutes", sa.Integer(), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_paused_seconds", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_reason", sa.String(length=30), nullable=True),
        sa.Column("breached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["ticket_assignments.assignment_id"]),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.ticket_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("assignment_sla_id"),
        sa.UniqueConstraint("assignment_id", "run_number", name="uq_ticket_assignment_slas_run"),
    )
    op.create_index("ix_ticket_assignment_slas_assignment_id", "ticket_assignment_slas", ["assignment_id"])
    op.create_index("ix_ticket_assignment_slas_ticket_id", "ticket_assignment_slas", ["ticket_id"])
    op.create_index(
        "uq_ticket_assignment_slas_one_live_run",
        "ticket_assignment_slas",
        ["assignment_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'COMPLETED'"),
    )
    op.create_index(
        "ix_ticket_assignment_slas_status_due_at",
        "ticket_assignment_slas",
        ["status", "due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_assignment_slas_status_due_at", table_name="ticket_assignment_slas")
    op.drop_index("uq_ticket_assignment_slas_one_live_run", table_name="ticket_assignment_slas")
    op.drop_index("ix_ticket_assignment_slas_ticket_id", table_name="ticket_assignment_slas")
    op.drop_index("ix_ticket_assignment_slas_assignment_id", table_name="ticket_assignment_slas")
    op.drop_table("ticket_assignment_slas")

    op.drop_index("uq_ticket_categories_one_primary", table_name="ticket_categories")
    op.drop_index("ix_ticket_categories_category_id", table_name="ticket_categories")
    op.drop_index("ix_ticket_categories_ticket_id", table_name="ticket_categories")
    op.drop_table("ticket_categories")

    op.drop_index("ix_ticket_assignments_active_user_status", table_name="ticket_assignments")
    op.drop_index("uq_ticket_assignments_one_active_primary", table_name="ticket_assignments")
    op.drop_index("uq_ticket_assignments_active_user", table_name="ticket_assignments")
    op.drop_index("ix_ticket_assignments_ticket_id", table_name="ticket_assignments")
    op.drop_table("ticket_assignments")
