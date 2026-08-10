"""add ticket number sequence

Revision ID: 277b41c65b53
Revises: ea58ff19d541
Create Date: 2026-08-10 11:48:08.559203

Adds a permanent, human-readable ticket reference ("TKT-<ticket_number>")
alongside the existing UUID `ticket_id` primary key — additive only,
never a replacement for it.

Mechanism: a dedicated Postgres SEQUENCE (`ticket_number_seq`), not
`SERIAL`/`IDENTITY` on the column directly, since `tickets.ticket_id`
is already generated client-side (Python `default=uuid.uuid4`, no
`server_default`) — INSERTs always list an explicit column set, so a
plain `server_default=nextval(...)` on the new column composes cleanly
with that existing insert shape (TicketRepository.create's generic
`Ticket(**data.model_dump())` / `self.db.add(ticket)`) with zero
changes needed there. `nextval()` on a Postgres sequence is atomic
under concurrent transactions by construction — no `SELECT MAX(...)+1`
race, matching the project's own "no in-app counter" requirement.

Backfill order is deterministic (`created_at ASC, ticket_id ASC` as
the tie-breaker) via a single windowed UPDATE — not `nextval()` calls
inside the UPDATE itself, since Postgres gives no ordering guarantee
for when each row's SET clause evaluates a volatile function like
nextval() relative to any ORDER BY. Assigning plain 1..N via
ROW_NUMBER() first, then advancing the sequence's own counter to N via
`setval()`, keeps this migration a single, deterministic pass with no
per-row nextval() call — the sequence only starts actually being drawn
from once real ticket creation resumes after this migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '277b41c65b53'
down_revision: Union[str, None] = 'ea58ff19d541'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE ticket_number_seq")

    op.add_column(
        "tickets",
        sa.Column("ticket_number", sa.BigInteger(), nullable=True),
    )

    # Deterministic backfill for every pre-existing ticket, oldest
    # first — assigned once here, permanent from this point on. A
    # bare `UPDATE ... SET ticket_number = nextval(...)` (no ORDER BY
    # possible on an UPDATE) would not guarantee assignment order
    # matches creation order, so this uses ROW_NUMBER() over an
    # explicit ORDER BY instead, then advances the real sequence past
    # the highest assigned value.
    op.execute(
        """
        WITH ordered AS (
            SELECT
                ticket_id,
                ROW_NUMBER() OVER (ORDER BY created_at ASC, ticket_id ASC) AS rn
            FROM tickets
            WHERE ticket_number IS NULL
        )
        UPDATE tickets
        SET ticket_number = ordered.rn
        FROM ordered
        WHERE tickets.ticket_id = ordered.ticket_id
        """
    )

    # Advance the sequence's own counter to the highest backfilled
    # value (0 if the table was empty) so the very next nextval() call
    # — the first real ticket created after this migration — continues
    # immediately after the last backfilled number, with no gap and no
    # collision.
    op.execute(
        "SELECT setval('ticket_number_seq', COALESCE((SELECT MAX(ticket_number) FROM tickets), 0), true)"
    )

    op.alter_column("tickets", "ticket_number", nullable=False)
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN ticket_number SET DEFAULT nextval('ticket_number_seq')"
    )
    op.execute("ALTER SEQUENCE ticket_number_seq OWNED BY tickets.ticket_number")
    op.create_unique_constraint("uq_tickets_ticket_number", "tickets", ["ticket_number"])


def downgrade() -> None:
    op.drop_constraint("uq_tickets_ticket_number", "tickets", type_="unique")
    op.execute("ALTER TABLE tickets ALTER COLUMN ticket_number DROP DEFAULT")
    op.drop_column("tickets", "ticket_number")
    op.execute("DROP SEQUENCE IF EXISTS ticket_number_seq")
