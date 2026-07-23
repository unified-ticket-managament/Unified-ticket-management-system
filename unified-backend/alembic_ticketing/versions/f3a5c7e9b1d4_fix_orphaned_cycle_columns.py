"""fix orphaned cycle columns on resolution_slas / sla_breach_notifications

Revision ID: f3a5c7e9b1d4
Revises: d2a4c6e8f0b3
Create Date: 2026-07-23 00:00:00.000000

`resolution_slas.escalation_cycle` and `sla_breach_notifications.cycle`
exist on the live (shared dev) database but were never created by any
migration in this chain, and were never added to the SQLAlchemy models
either — both columns were added out-of-band (raw DDL against the
shared database, not through Alembic), the same "manual/live-testing
session leaves debris behind" pattern this repo's CLAUDE.md already
documents elsewhere. Confirmed live: neither column name appears
anywhere in this codebase's Python (models or services) before this
migration.

This broke every new `resolution_slas` INSERT outright:
`escalation_cycle` is NOT NULL with no default, and since the ORM model
doesn't know the column exists, it never supplies a value — Postgres
has nothing to fill it with. This is what was surfacing as "network
error" when creating a ticket from an inbound email: every ticket
creation starts a fresh Resolution SLA clock
(InboxTicketService.create_ticket_from_interaction ->
SLAService.start_resolution_clock), which failed 100% of the time.

`sla_breach_notifications.cycle` already had a DB-level default (0) —
plain inserts were fine — but its accompanying unique index had been
widened to 4 columns (clock_type, clock_id, threshold, cycle) out of
band too, while SLABreachNotificationRepository's ON CONFLICT clause
still targeted the original 3. Postgres requires an exact match between
an ON CONFLICT target and a real unique constraint, so
try_record/try_record_many raised "no unique or exclusion constraint
matching the ON CONFLICT specification" the moment a sweep/completion
path actually needed to write a breach-notification row (see
CLAUDE.md's own note on this exact error under complete_first_response_clock).

Idempotent both ways: add_column only runs if the column is genuinely
absent (a fresh database that predates this drift), otherwise only the
default/index is (re)applied to match what's already live here. Neither
column gets any new business meaning in this migration — that's a
future feature (see the ticket_escalations model's own "how many real
accept-assign-breach cycles" comment); this migration only makes the
already-existing columns safely insertable, matching the isolated
sla_breach_notifications.cycle fix that had already been applied here.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3a5c7e9b1d4'
down_revision: Union[str, None] = 'd2a4c6e8f0b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    resolution_slas_columns = {c["name"] for c in inspector.get_columns("resolution_slas")}
    if "escalation_cycle" not in resolution_slas_columns:
        op.add_column(
            "resolution_slas",
            sa.Column("escalation_cycle", sa.Integer(), nullable=False, server_default="0"),
        )
    else:
        op.alter_column("resolution_slas", "escalation_cycle", server_default="0")

    breach_notification_columns = {
        c["name"] for c in inspector.get_columns("sla_breach_notifications")
    }
    if "cycle" not in breach_notification_columns:
        op.add_column(
            "sla_breach_notifications",
            sa.Column("cycle", sa.Integer(), nullable=False, server_default="0"),
        )
    else:
        op.alter_column("sla_breach_notifications", "cycle", server_default="0")

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("sla_breach_notifications")}
    if "ix_sla_breach_notifications_unique" in existing_indexes:
        op.drop_index("ix_sla_breach_notifications_unique", table_name="sla_breach_notifications")
    op.create_index(
        "ix_sla_breach_notifications_unique",
        "sla_breach_notifications",
        ["clock_type", "clock_id", "threshold", "cycle"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_sla_breach_notifications_unique", table_name="sla_breach_notifications")
    op.create_index(
        "ix_sla_breach_notifications_unique",
        "sla_breach_notifications",
        ["clock_type", "clock_id", "threshold"],
        unique=True,
    )

    op.drop_column("sla_breach_notifications", "cycle")
    op.drop_column("resolution_slas", "escalation_cycle")
