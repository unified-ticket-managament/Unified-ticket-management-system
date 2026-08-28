"""add one-ticket-draft-per-agent-per-type unique index on interactions

Revision ID: b7c1e4f6a9d2
Revises: 43fc7a437dc1
Create Date: 2026-08-26 00:00:00.000000

Adds Save Draft support for Ticket Reply / Internal Note (Mail's own
ticketed ReplyComposer, and TicketComposer.tsx's reply/note modes) —
previously there was no server-side draft architecture for anything
already attached to a ticket at all; only a bare (pre-ticket) Mail
thread could have a saved draft (see f4b6d8a0c2e5's own migration).

A ticket-scoped draft is a sibling shape to that pre-ticket one, not a
branch of it: `interaction_type` ("REPLY" or "INTERNAL_NOTE"),
`ticket_id` set, `parent_interaction_id` NULL, `is_draft`=true — there
is no "thread root" to attach a child draft row to the way a bare Mail
thread has, since the ticket itself is the scope. This index is the
ticket-scoped counterpart to ix_interactions_one_draft_per_thread_per_
agent: at most one active REPLY draft and one active INTERNAL_NOTE
draft per (ticket, agent) pair. `ticket_id IS NULL` (every pre-ticket
draft, including a Compose draft) never collides with this index —
Postgres never treats two NULLs as equal in a unique index — so this
is purely additive alongside the existing index, not a replacement.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c1e4f6a9d2'
down_revision: Union[str, None] = '43fc7a437dc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX ix_interactions_one_ticket_draft_per_agent_per_type
        ON interactions (ticket_id, performed_by, interaction_type)
        WHERE is_draft IS TRUE AND is_visible IS TRUE
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_interactions_one_ticket_draft_per_agent_per_type")
