# ticket_number_counter.py
from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class TicketNumberCounter(Base):
    """
    A transactional, gapless counter — deliberately not a Postgres
    SEQUENCE, because a SEQUENCE's nextval() is never rolled back, so a
    failed ticket-creation transaction would still permanently burn a
    number. `TicketRepository._allocate_current_ticket_number` locks
    this row with SELECT ... FOR UPDATE and increments `next_number` in
    the SAME transaction as the new ticket's INSERT: if that
    transaction rolls back for any reason, the increment rolls back
    with it, and the next successful attempt gets the same number
    again — no gaps, no reuse, no duplicates, ever, for successful
    (committed) ticket creations.

    One row per numbering series. Today only `'current'` (tickets
    created after the dual-series cutover) ever allocates from this
    table — `'legacy'` tickets keep whatever `ticket_number` they
    already had and never touch this table at all. See
    Ticket.ticket_number_series.
    """

    __tablename__ = "ticket_number_counters"

    series: Mapped[str] = mapped_column(String(20), primary_key=True)
    next_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
