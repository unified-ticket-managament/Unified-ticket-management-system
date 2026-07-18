"""allow multiple escalation_handling_slas rows per escalation (one active at a time)

Revision ID: a3c5e7f9b1d5
Revises: f4b6d8a0c2e5
Create Date: 2026-07-17 00:00:00.000000

Implements the requested rule: the escalation-handling clock started on
the FIRST acceptance of an escalation runs under the ticket's *original*
priority target (already how EscalationHandlingSlaService._resolve_policy
reads ResolutionSLA.priority, and already correct as of the previous
reshift-gating fix). If that original-priority handling clock itself
breaches (the owner didn't resolve it in time, so the escalation
advances a level), the NEXT acceptance should start a genuinely fresh
handling clock under CRITICAL's target — not silently keep reusing the
first, already-breached one forever.

`escalation_handling_slas.escalation_id` was unique — at most one row
per escalation, ever — which made this impossible:
EscalationHandlingSlaService.start_if_not_started's idempotency check
(get_by_escalation_id) found the existing (breached) row and always
returned it unchanged, regardless of whether the escalation had since
advanced. This migration relaxes that to "at most one ACTIVE
(un-breached, un-completed) row per escalation at a time" — a breached
row falls outside the new partial unique index's predicate, freeing up
the escalation_id for a fresh row once accepted again at the new level.
The breached row itself is kept as permanent history, never deleted or
mutated.

No existing data violates this (the old constraint was strictly
tighter, so every escalation_id currently has at most one row already)
— this is a pure constraint relaxation, no backfill/cleanup needed.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3c5e7f9b1d5'
down_revision: Union[str, None] = 'f4b6d8a0c2e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        'ix_escalation_handling_slas_escalation_id',
        table_name='escalation_handling_slas',
    )
    op.create_index(
        'ix_escalation_handling_slas_escalation_id',
        'escalation_handling_slas',
        ['escalation_id'],
        unique=False,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ix_escalation_handling_slas_one_active_per_escalation
        ON escalation_handling_slas (escalation_id)
        WHERE breached_at IS NULL AND completed_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_escalation_handling_slas_one_active_per_escalation"
    )
    op.drop_index(
        'ix_escalation_handling_slas_escalation_id',
        table_name='escalation_handling_slas',
    )
    op.create_index(
        'ix_escalation_handling_slas_escalation_id',
        'escalation_handling_slas',
        ['escalation_id'],
        unique=True,
    )
