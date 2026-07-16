"""add one-draft-per-thread-per-agent unique index on interactions

Revision ID: f4b6d8a0c2e5
Revises: e5a7c9f1b3d6
Create Date: 2026-07-16 20:45:00.000000

Fixes a real, reproducible bug: InteractionService._get_or_create_draft
does a check-then-insert (get_draft, then create if none found) with no
database-level guard, so two near-simultaneous debounced draft-save
requests (the frontend calls this continuously as the user types) can
both observe "no existing draft" and both insert one — leaving two
`is_draft=True` rows for the same (parent_interaction_id, performed_by)
pair. InteractionRepository.get_draft's own docstring assumed "always
at most one row" and called scalar_one_or_none(), which raises
MultipleResultsFound the moment a thread hits this — surfacing to the
user as a 500 on GET /inbox/{id} (opening the message), which the
browser reports as a CORS failure since the error response bypasses
the CORS middleware — not an actual CORS problem.

Three real threads in this database already hit this before the fix.
Since a duplicate group has no way to know which row is authoritative,
this migration keeps each group's most-recently-created row and
soft-deletes (is_visible=false, removed_at=now()) the rest — the same
soft-delete shape InteractionService.hide_interaction already uses,
and the same choice InteractionRepository.get_draft's own read-side fix
(ORDER BY created_at DESC) makes for any duplicate this migration
doesn't yet know about. The unique index below (mirroring
ix_ticket_escalations_one_active_per_ticket's partial-unique-index
pattern) then makes it impossible to create a second one going
forward — the app-level fix to InteractionService catches the
resulting IntegrityError on a lost race and re-fetches the winner
instead of failing that request.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f4b6d8a0c2e5'
down_revision: Union[str, None] = 'e5a7c9f1b3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE interactions
        SET is_visible = false, removed_at = now()
        WHERE interaction_id IN (
            SELECT interaction_id FROM (
                SELECT
                    interaction_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY parent_interaction_id, performed_by
                        ORDER BY created_at DESC, interaction_id DESC
                    ) AS rn
                FROM interactions
                WHERE is_draft IS TRUE AND is_visible IS TRUE
            ) ranked
            WHERE rn > 1
        )
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_interactions_one_draft_per_thread_per_agent
        ON interactions (parent_interaction_id, performed_by)
        WHERE is_draft IS TRUE AND is_visible IS TRUE
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_interactions_one_draft_per_thread_per_agent")
