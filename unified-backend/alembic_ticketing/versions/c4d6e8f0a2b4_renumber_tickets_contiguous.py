"""renumber tickets contiguous by creation order

Revision ID: c4d6e8f0a2b4
Revises: 277b41c65b53
Create Date: 2026-08-10 19:00:00.000000

The original ticket_number backfill (277b41c65b53) assigned 1..N over
every row that existed in `tickets` at the moment it ran, including a
large batch of test/dev tickets that were later deleted. The surviving
real tickets kept whichever rank they happened to land on at that
point in time, so a handful of real tickets ended up sparsely
numbered (e.g. 1-6 then 187) even though only 7 tickets exist today —
technically stable/non-reused, but not what "chronological sequential
numbering" is supposed to look like to a user.

This migration re-normalizes: it renumbers the *current* ticket
population contiguously from 1, purely by `created_at ASC` (ticket_id
ASC tie-break for identical timestamps), completely ignoring whatever
ticket_number values already exist. This is a one-time reset of the
existing dataset only — it does not change the no-reuse guarantee
going forward: after this migration runs, a ticket_number is again
permanent for the life of that ticket, and deleting a ticket in the
future will not trigger another renumbering pass.

UUIDs (`ticket_id`) and every foreign key referencing them are
untouched — only the `ticket_number` column's values change.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4d6e8f0a2b4'
down_revision: Union[str, None] = '277b41c65b53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the unique constraint first — the renumbering below
    # temporarily produces a mix of old and new numbers that can
    # collide mid-UPDATE (e.g. a ticket being renumbered to 3 while
    # another still-unprocessed row already holds 3).
    op.drop_constraint("uq_tickets_ticket_number", "tickets", type_="unique")

    op.execute(
        """
        WITH ordered AS (
            SELECT
                ticket_id,
                ROW_NUMBER() OVER (ORDER BY created_at ASC, ticket_id ASC) AS rn
            FROM tickets
        )
        UPDATE tickets
        SET ticket_number = ordered.rn
        FROM ordered
        WHERE tickets.ticket_id = ordered.ticket_id
        """
    )

    op.create_unique_constraint("uq_tickets_ticket_number", "tickets", ["ticket_number"])

    # Reset the sequence to the new highest value so the next real
    # ticket creation continues immediately after it, not from
    # whatever stale high-water mark the sequence was previously at.
    # When the table is empty, setval(..., 1, false) is used instead
    # of setval(..., 0, true) — 0 is out of range for a sequence whose
    # minimum value is 1.
    op.execute(
        """
        SELECT setval(
            'ticket_number_seq',
            COALESCE((SELECT MAX(ticket_number) FROM tickets), 1),
            (SELECT MAX(ticket_number) FROM tickets) IS NOT NULL
        )
        """
    )


def downgrade() -> None:
    # Not meaningfully reversible — the original per-ticket numbers
    # this overwrites are the exact stale values this migration exists
    # to correct, so there is nothing sensible to restore them to.
    raise NotImplementedError(
        "c4d6e8f0a2b4 renumbers tickets destructively and has no reverse migration"
    )
