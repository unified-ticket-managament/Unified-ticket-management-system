"""reconcile orphaned dev-DB revision stamp

Revision ID: c8e0a2b4d6f8
Revises: b7c1e4f6a9d2
Create Date: 2026-08-27 00:00:00.000000

Placeholder, not a real schema change. The shared dev DB's
`ticket_alembic_version` table was found stamped at this exact
revision ID with no corresponding migration file anywhere in this
repo's history (checked the local head, origin/main, and every
unreachable/dangling commit — genuinely absent, not merely unpulled).
`alembic current`/`upgrade` refuse to run at all against an unknown
current revision, which blocked adding any further ticketing
migration.

Investigated before creating this file, not assumed: every ticketing
table's live column count matches its SQLAlchemy model exactly
(spot-checked attachments 15/15, interactions 33/33, tickets 18/18),
and the one schema object the true local head (b7c1e4f6a9d2) itself
adds — `ix_interactions_one_ticket_draft_per_agent_per_type` — is
already present. The RBAC Alembic chain's own `alembic_version` table,
by contrast, matches its local head with no drift at all, narrowing
the problem to this one chain. Most likely explanation: someone ran
`alembic revision`+`upgrade` locally (possibly an empty/no-op
autogenerate, or an experiment) and never committed the generated
file. This migration's only job is to make the checked-in history
match what the shared DB already believes its own current revision
is, with zero DDL, so normal `alembic upgrade head` work can resume;
if the missing file ever resurfaces, replay its real change as a new,
later revision rather than editing this one.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'c8e0a2b4d6f8'
down_revision: Union[str, None] = 'b7c1e4f6a9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
