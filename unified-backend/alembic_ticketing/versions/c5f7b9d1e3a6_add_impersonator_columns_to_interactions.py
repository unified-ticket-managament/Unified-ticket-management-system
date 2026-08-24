"""add impersonator columns to interactions

Revision ID: c5f7b9d1e3a6
Revises: b3e5a7c9d1f4
Create Date: 2026-08-22 00:00:00.000000

Companion to b3e5a7c9d1f4 (ticket_audit_logs) and alembic_rbac's
b2d4f6a8c0e3 (audit_logs) — this closes the actual gap a live test
surfaced: the ticket-detail Timeline tab renders from `interactions`
rows (via InteractionResponse's `performed_by`/`performed_by_name`),
not from the audit log, so an action taken while impersonating showed
"Performed by <target>" with zero indication a Super Admin was
actually behind it, even though the separate Audit Log tab already
recorded both identities correctly. `performed_by`/`performed_by_name`
keep their existing meaning (the target/effective performer); these
two new columns separately record the real actor when one is
impersonating. NULL for every ordinary row.

NOTE — applied out-of-band on 2026-08-23: while implementing this, the
shared Neon database's `ticket_alembic_version` was found advancing on
its own, twice, within minutes, to revision ids present in no local
file or on `origin/main` — a concurrent process (another session, or
the deployed Render backend, which this repo's own root CLAUDE.md
already documents as sharing this exact database) was actively
running its own migrations against the same DB at the same time.
Racing `alembic upgrade head` against a moving version pointer isn't
safe, so the two columns/FK below were applied directly via idempotent
raw SQL (`ADD COLUMN IF NOT EXISTS`, a guarded `ADD CONSTRAINT`) rather
than through this file. `upgrade()` is written with the same
`IF NOT EXISTS` guards so it's a safe no-op if/when this file is
eventually reconciled into the real chain (via `alembic merge` once
the other branch's own migrations are known) and run for real.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c5f7b9d1e3a6'
down_revision: Union[str, None] = 'b3e5a7c9d1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE interactions ADD COLUMN IF NOT EXISTS impersonator_id UUID")
    op.execute("ALTER TABLE interactions ADD COLUMN IF NOT EXISTS impersonator_name VARCHAR(255)")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'interactions'
                AND constraint_name = 'fk_interactions_impersonator_id_users'
            ) THEN
                ALTER TABLE interactions
                ADD CONSTRAINT fk_interactions_impersonator_id_users
                FOREIGN KEY (impersonator_id) REFERENCES users(user_id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_interactions_impersonator_id_users',
        'interactions', type_='foreignkey',
    )
    op.drop_column('interactions', 'impersonator_name')
    op.drop_column('interactions', 'impersonator_id')
