"""add dispatch columns to interactions

Revision ID: 0941a80891de
Revises: b201554c1537
Create Date: 2026-08-24 00:00:00.000002

Promotes dispatch_status/dispatch_error/send_after/provider_message_id
from payload-JSONB-only keys (set by InteractionService._dispatch_and_
record/_schedule_delayed_send/cancel_pending_send since the Undo-Send
feature landed) to real, indexed columns. `payload` remains the
source of truth every existing read site (cancel_pending_send,
undo_send's own re-check) keeps reading unchanged — these columns are
a queryable mirror, populated going forward by interaction_service.
_dispatch_columns_from_payload, and backfilled here for every
already-existing row that has them in payload today.

dispatch_status stays a plain String, not a native Postgres enum —
its value set has already grown once (CANCELED/NO_RECIPIENT/DRAFT
added after the original PENDING_SEND/SENT/FAILED/QUEUED trio) and a
native enum would need its own migration each time it grows again
(see this repo's own "add-postgres-enum-value" gotcha for
AuditEventType/SLAClockStatus/EscalationLevel/EscalationStatus).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0941a80891de'
down_revision: Union[str, None] = 'b201554c1537'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interactions",
        sa.Column("dispatch_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "interactions",
        sa.Column("dispatch_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "interactions",
        sa.Column("send_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "interactions",
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
    )

    op.create_index(
        "ix_interactions_dispatch_status",
        "interactions",
        ["dispatch_status"],
    )
    op.create_index(
        "ix_interactions_provider_message_id",
        "interactions",
        ["provider_message_id"],
    )

    # Backfill from the existing payload JSONB for every row that
    # already carries these keys — a one-time reconciliation, not an
    # ongoing dual-source-of-truth mechanism (going forward, the app
    # writes both at once).
    op.execute(
        """
        UPDATE interactions
        SET
            dispatch_status = payload->>'dispatch_status',
            dispatch_error = payload->>'dispatch_error',
            send_after = CASE
                WHEN payload->>'send_after' IS NOT NULL
                THEN (payload->>'send_after')::timestamptz
                ELSE NULL
            END,
            provider_message_id = payload->>'provider_message_id'
        WHERE payload ? 'dispatch_status'
           OR payload ? 'provider_message_id'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_interactions_provider_message_id", table_name="interactions")
    op.drop_index("ix_interactions_dispatch_status", table_name="interactions")
    op.drop_column("interactions", "provider_message_id")
    op.drop_column("interactions", "send_after")
    op.drop_column("interactions", "dispatch_error")
    op.drop_column("interactions", "dispatch_status")
