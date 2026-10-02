"""add rule_runs and rule_run_items tables

Revision ID: 02d1308a9f3c
Revises: b7d9f1a3c5e7
Create Date: 2026-10-02 00:00:00.000000

Backs Mail Rules' "Run rule now" — a one-time, background, retroactive
execution of one rule over existing inbound mail. See RuleRun/
RuleRunItem's own docstrings (app/ticketing/models/rule_run.py).
Purely additive: two new tables, no changes to any existing table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '02d1308a9f3c'
down_revision: Union[str, None] = 'b7d9f1a3c5e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rules.rule_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rule_name", sa.String(length=255), nullable=False),
        sa.Column(
            "rule_owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "impersonator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column("impersonator_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("phase", sa.String(length=20), nullable=False, server_default="scan"),
        sa.Column("rule_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "precedence_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "scope",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cursor_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_interaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("already_applied_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("forwards_sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "skipped_by_reason",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "error_samples",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_rule_runs_rule_id", "rule_runs", ["rule_id"])
    op.create_index("ix_rule_runs_status", "rule_runs", ["status"])
    op.create_index("ix_rule_runs_rule_id_created_at", "rule_runs", ["rule_id", "created_at"])
    op.create_index(
        "uq_rule_runs_one_active_per_rule",
        "rule_runs",
        ["rule_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "rule_run_items",
        sa.Column("item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rule_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "interaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interactions.interaction_id"),
            nullable=False,
        ),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_index", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("skip_reason", sa.String(length=50), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "run_id", "interaction_id", "action_index",
            name="uq_rule_run_items_run_interaction_action",
        ),
    )
    op.create_index("ix_rule_run_items_run_id", "rule_run_items", ["run_id"])
    op.create_index(
        "ix_rule_run_items_interaction_action_status",
        "rule_run_items",
        ["interaction_id", "action_type", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_rule_run_items_interaction_action_status", table_name="rule_run_items")
    op.drop_index("ix_rule_run_items_run_id", table_name="rule_run_items")
    op.drop_table("rule_run_items")
    op.drop_index("uq_rule_runs_one_active_per_rule", table_name="rule_runs")
    op.drop_index("ix_rule_runs_rule_id_created_at", table_name="rule_runs")
    op.drop_index("ix_rule_runs_status", table_name="rule_runs")
    op.drop_index("ix_rule_runs_rule_id", table_name="rule_runs")
    op.drop_table("rule_runs")
