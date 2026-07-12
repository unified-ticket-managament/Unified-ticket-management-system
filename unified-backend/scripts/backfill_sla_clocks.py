# backfill_sla_clocks.py
#
# One-off data backfill for the SLA feature — creates SLA clocks for
# work that already existed before this feature shipped:
#   - A ResolutionSLA for every currently-open (not RESOLVED/CLOSED)
#     ticket that doesn't already have one, using started_at =
#     ticket.created_at (NOT "now") — an already-old open ticket
#     honestly shows up as already at-risk/breached, matching "we're
#     turning on SLA tracking for what's already open", not "the
#     clock starts today for everyone".
#   - A FirstResponseSLA for every still-PENDING, pre-ticket thread-
#     root Interaction that doesn't already have one, using
#     received_at as started_at.
#
# Deliberately skips RESOLVED/CLOSED tickets and non-pending/already-
# ticketed interactions — backfilling those would just generate
# meaningless breach noise for work that's already done.
#
# Idempotent — safe to re-run; skips anything that already has a
# clock row rather than creating a second one.
#
# NOTE: expect a burst of AT_RISK/BREACHED notifications on the very
# next sweep tick after running this against a real backlog of open
# tickets — that's the honest signal about existing work, not a bug.
# Consider running this during a quiet window.
#
# Usage (from unified-backend/, with the venv active):
#   python -m scripts.backfill_sla_clocks

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from app.database.session import AsyncSessionLocal
from app.ticketing.enums import InteractionStatus, TicketPriority, TicketStatus
from app.ticketing.models.first_response_sla import FirstResponseSLA
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.first_response_sla_repository import (
    FirstResponseSLARepository,
)
from app.ticketing.repositories.resolution_sla_repository import (
    ResolutionSLARepository,
)
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository

TERMINAL_TICKET_STATUSES = (TicketStatus.RESOLVED, TicketStatus.CLOSED)


@dataclass
class BackfillStats:
    resolution_clocks_created: int = 0
    resolution_clocks_skipped_terminal: int = 0
    resolution_clocks_skipped_existing: int = 0
    resolution_clocks_skipped_no_policy: int = 0
    first_response_clocks_created: int = 0
    first_response_clocks_skipped_existing: int = 0
    first_response_clocks_skipped_no_policy: int = 0


async def backfill(session) -> BackfillStats:
    stats = BackfillStats()

    sla_policy_repository = SLAPolicyRepository(session)
    resolution_sla_repository = ResolutionSLARepository(session)
    first_response_sla_repository = FirstResponseSLARepository(session)

    # ---------------------------------------------------------
    # Resolution clocks for currently-open tickets
    # ---------------------------------------------------------

    open_tickets = (
        await session.execute(
            select(Ticket).where(Ticket.current_status.notin_(TERMINAL_TICKET_STATUSES))
        )
    ).scalars().all()

    for ticket in open_tickets:
        existing = await resolution_sla_repository.get_by_ticket_id(ticket.ticket_id)
        if existing is not None:
            stats.resolution_clocks_skipped_existing += 1
            continue

        policy = await sla_policy_repository.get_by_priority(ticket.current_priority)
        if policy is None:
            stats.resolution_clocks_skipped_no_policy += 1
            continue

        await resolution_sla_repository.create(
            ticket_id=ticket.ticket_id,
            client_id=ticket.client_company_id,
            priority=ticket.current_priority,
            started_at=ticket.created_at,
            due_at=ticket.created_at + timedelta(minutes=policy.resolution_target_minutes),
        )
        stats.resolution_clocks_created += 1

    # ---------------------------------------------------------
    # First Response clocks for still-pending thread-root interactions
    # ---------------------------------------------------------

    pending_roots = (
        await session.execute(
            select(Interaction).where(
                Interaction.ticket_id.is_(None),
                Interaction.parent_interaction_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
                Interaction.interaction_type == "EMAIL",
            )
        )
    ).scalars().all()

    # Priority isn't known for a pre-ticket interaction — see
    # FirstResponseSLA's own docstring for why MEDIUM is the accepted
    # v1 default for policy lookup.
    default_policy = await sla_policy_repository.get_by_priority(TicketPriority.MEDIUM)

    for interaction in pending_roots:
        existing = await first_response_sla_repository.get_by_interaction_id(
            interaction.interaction_id
        )
        if existing is not None:
            stats.first_response_clocks_skipped_existing += 1
            continue

        if default_policy is None:
            stats.first_response_clocks_skipped_no_policy += 1
            continue

        started_at = interaction.received_at or interaction.created_at
        await first_response_sla_repository.create(
            interaction_id=interaction.interaction_id,
            client_id=interaction.client_id,
            priority=TicketPriority.MEDIUM,
            started_at=started_at,
            due_at=started_at
            + timedelta(minutes=default_policy.first_response_target_minutes),
        )
        stats.first_response_clocks_created += 1

    await session.commit()
    return stats


async def main() -> None:
    async with AsyncSessionLocal() as session:
        stats = await backfill(session)

    print("SLA clock backfill complete.")
    print(f"  Resolution clocks created:            {stats.resolution_clocks_created}")
    print(f"  Resolution clocks skipped (existing):  {stats.resolution_clocks_skipped_existing}")
    print(f"  Resolution clocks skipped (no policy): {stats.resolution_clocks_skipped_no_policy}")
    print(f"  First Response clocks created:            {stats.first_response_clocks_created}")
    print(f"  First Response clocks skipped (existing):  {stats.first_response_clocks_skipped_existing}")
    print(f"  First Response clocks skipped (no policy): {stats.first_response_clocks_skipped_no_policy}")


if __name__ == "__main__":
    asyncio.run(main())
