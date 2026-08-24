"""add ticket number series and counter

Revision ID: b201554c1537
Revises: d4f7b9c1e3a8
Create Date: 2026-08-24 00:00:00.000000

Introduces a second, independent "current" ticket-numbering series
that starts at 1 and is gapless, alongside every pre-existing
("legacy") ticket's number, unchanged.

Why not just reset/reuse `ticket_number_seq`: this migration never
renumbers a single existing ticket and never touches `ticket_number`
on any pre-existing row — the two migrations that already ran
(277b41c65b53_add_ticket_number_sequence,
c4d6e8f0a2b4_renumber_tickets_contiguous) assigned real tickets
contiguous numbers starting at 1, so a brand-new counter that also
starts at 1 WILL collide with those existing values under a single,
table-wide UNIQUE constraint. The resolution: tag every row with which
numbering generation it belongs to (`ticket_number_series`, backfilled
to 'legacy' for everything that exists today) and scope uniqueness to
(ticket_number, ticket_number_series) instead of ticket_number alone —
the same integer may now legitimately exist once per series, never
twice within one. This is a deliberate, product-level decision: the
displayed "TKT-<n>" label is not required to be globally unique across
eras, only within one.

Why a counter table instead of a second Postgres SEQUENCE: a
SEQUENCE's nextval() is NOT transactional — it is never rolled back,
so a failed ticket-creation transaction would still permanently burn a
number and leave a gap. Zero gaps in the new "current" series is a
hard requirement here, so `ticket_number_counters` is a plain table
whose single 'current' row is locked with SELECT ... FOR UPDATE and
incremented by application code (TicketRepository.
_allocate_current_ticket_number) in the SAME transaction as the new
ticket's INSERT — a rollback undoes the increment right along with the
insert. See that method's docstring for the full mechanism.

This migration deliberately never touches: `ticket_number`'s own
column default (still `nextval('ticket_number_seq')`, now only a
fallback for code that constructs a Ticket row directly without going
through the repository — several test fixtures do this for unrelated
SLA/escalation/attachment setup), `ticket_number_seq` itself, or any
existing row's `ticket_number`/`ticket_id` value.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b201554c1537'
down_revision: Union[str, None] = 'd4f7b9c1e3a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("ticket_number_series", sa.String(length=20), nullable=True),
    )

    # Every ticket that exists at this point predates the dual-series
    # cutover — tag it 'legacy' once, permanently. Touches only this
    # new column; ticket_number itself is never written here.
    op.execute(
        "UPDATE tickets SET ticket_number_series = 'legacy' "
        "WHERE ticket_number_series IS NULL"
    )

    op.alter_column("tickets", "ticket_number_series", nullable=False)
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN ticket_number_series SET DEFAULT 'legacy'"
    )
    op.create_check_constraint(
        "ck_tickets_ticket_number_series",
        "tickets",
        "ticket_number_series IN ('legacy', 'current')",
    )

    # Replace the old single-column uniqueness (which is exactly what
    # would forbid a 'current' ticket from ever reusing a 'legacy'
    # number) with one scoped per series. Every existing row is
    # (ticket_number, 'legacy') at this point, which is trivially
    # unique since uq_tickets_ticket_number already guaranteed
    # ticket_number was globally unique before this statement runs.
    op.drop_constraint("uq_tickets_ticket_number", "tickets", type_="unique")
    op.create_unique_constraint(
        "uq_tickets_ticket_number_series",
        "tickets",
        ["ticket_number", "ticket_number_series"],
    )

    # The gapless, transactional counter for the 'current' series only
    # — see TicketNumberCounter's docstring. Seeded so the very first
    # allocation after this migration returns 1.
    op.create_table(
        "ticket_number_counters",
        sa.Column("series", sa.String(length=20), primary_key=True),
        sa.Column("next_number", sa.BigInteger(), nullable=False),
    )
    op.execute(
        "INSERT INTO ticket_number_counters (series, next_number) VALUES ('current', 1)"
    )


def downgrade() -> None:
    op.drop_table("ticket_number_counters")
    op.drop_constraint("uq_tickets_ticket_number_series", "tickets", type_="unique")

    # Only safe to run before any 'current'-series ticket has ever been
    # created — once one exists, its ticket_number may legitimately
    # collide with a 'legacy' one (that's the entire point of this
    # migration), and recreating a single-column UNIQUE constraint over
    # both series will raise a UniqueViolation and abort. This is the
    # same honest, unresolved irreversibility
    # c4d6e8f0a2b4_renumber_tickets_contiguous.py's own downgrade()
    # already accepts for this table.
    op.create_unique_constraint("uq_tickets_ticket_number", "tickets", ["ticket_number"])

    op.drop_constraint("ck_tickets_ticket_number_series", "tickets", type_="check")
    op.drop_column("tickets", "ticket_number_series")
