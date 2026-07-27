import asyncio
from app.database.session import AsyncSessionLocal, engine
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from app.ticketing.models.ticket_escalation import TicketEscalation
from app.ticketing.models.ticket import Ticket
from app.ticketing.enums import EscalationStatus, TicketStatus
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_escalation_repository import TicketEscalationRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.escalation_service import EscalationService
from app.ticketing.services.escalation_handling_sla_service import build_escalation_handling_sla_service

async def close_one(ticket_id, title):
    for attempt in range(5):
        try:
            async with AsyncSessionLocal() as session:
                ticket_repository = TicketRepository(session)
                escalation_service = EscalationService(
                    ticket_escalation_repository=TicketEscalationRepository(session),
                    ticket_repository=ticket_repository,
                    resolution_sla_repository=ResolutionSLARepository(session),
                    sla_policy_repository=SLAPolicyRepository(session),
                    user_repository=UserRepository(session),
                    notification_service=None,
                    escalation_handling_sla_service=build_escalation_handling_sla_service(session),
                )
                await escalation_service.close_for_ticket_resolution(ticket_id)
                await session.commit()
                print(f"  closed ticket={ticket_id} title={title!r} (attempt {attempt+1})")
                return True
        except DBAPIError as e:
            if "Deadlock" in str(e.orig) or "deadlock" in str(e):
                wait = 1.5 * (attempt + 1)
                print(f"  deadlock on ticket={ticket_id}, retrying in {wait}s (attempt {attempt+1})")
                await asyncio.sleep(wait)
                continue
            print(f"  FAILED ticket={ticket_id}: {e}")
            return False
    print(f"  GAVE UP on ticket={ticket_id} after 5 attempts")
    return False

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TicketEscalation.ticket_id, Ticket.title)
            .join(Ticket, Ticket.ticket_id == TicketEscalation.ticket_id)
            .where(TicketEscalation.status != EscalationStatus.CLOSED, Ticket.current_status == TicketStatus.CLOSED)
        )
        rows = result.all()
    print(f"Found {len(rows)} orphaned escalations to close.\n")

    succeeded = 0
    failed = 0
    for ticket_id, title in rows:
        ok = await close_one(ticket_id, title)
        if ok:
            succeeded += 1
        else:
            failed += 1

    print(f"\nDone. succeeded={succeeded} failed={failed}")
    await engine.dispose()

asyncio.run(main())
