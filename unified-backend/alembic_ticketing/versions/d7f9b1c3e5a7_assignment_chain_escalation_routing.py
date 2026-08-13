"""assignment-chain escalation routing

Revision ID: d7f9b1c3e5a7
Revises: a4c6e8f0b2d4
Create Date: 2026-08-13 00:00:00.000000

Escalation routing no longer climbs a fixed TEAM_LEAD -> MANAGER ->
SITE_LEAD role ladder — it now follows the ticket's own assignment
history (who assigned it to the current owner, who assigned it to
*them*, and so on — see app/ticketing/services/escalation_rules.py's
build_chain_owner_ids/resolve_owners_for_chain and root CLAUDE.md's
"SLA & Escalation" section for the full design). SITE_LEAD stays a
real, literal terminal marker (the chain-exhausted safety net); every
non-terminal step is now the new ASSIGNMENT_CHAIN value. TEAM_LEAD/
MANAGER are retired — kept in the Postgres enum only so pre-existing
CLOSED rows still deserialize, nothing writes them going forward.

This migration only adds the new enum label and three purely additive
columns on ticket_escalations (owner_roles/chain_owner_ids/
chain_position, all server-defaulted so existing rows backfill
safely) — no data migration needed, since no existing ACTIVE escalation
depends on the new columns to keep functioning (a CLOSED row's history
is unaffected either way).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'd7f9b1c3e5a7'
down_revision: Union[str, None] = 'a4c6e8f0b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction
    # as a later statement that USES the new value — the column adds
    # below don't reference 'ASSIGNMENT_CHAIN' at all, so they're safe
    # to combine with the enum-add in this one migration (see
    # 9c4e6a8b1d3f's own docstring for the case where a split really
    # was required).
    op.execute("ALTER TYPE ticket_escalation_level_enum ADD VALUE IF NOT EXISTS 'ASSIGNMENT_CHAIN'")

    op.add_column(
        "ticket_escalations",
        sa.Column("owner_roles", JSONB, nullable=False, server_default="{}"),
    )
    op.add_column(
        "ticket_escalations",
        sa.Column("chain_owner_ids", JSONB, nullable=False, server_default="[]"),
    )
    op.add_column(
        "ticket_escalations",
        sa.Column("chain_position", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("ticket_escalations", "chain_position")
    op.drop_column("ticket_escalations", "chain_owner_ids")
    op.drop_column("ticket_escalations", "owner_roles")
    # Postgres has no DROP VALUE for enums — removing a label requires
    # rebuilding the type, which isn't worth it for a downgrade path.
    # Matches this project's other enum-widening migrations.
