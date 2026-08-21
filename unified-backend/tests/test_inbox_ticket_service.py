# test_inbox_ticket_service.py
#
# Regression coverage for a real reported bug: clicking "Create Ticket"
# on an inbox email that has already been replied to (or was itself a
# fresh Compose, never a reply) always 400'd with "Interaction is not
# pending" — even though the frontend's own Create Ticket button
# (MessageDetailsView.tsx's `isTicketed` check) only ever gates on
# `ticket_id` being unset, never on `status`. InboxTicketService.
# _get_pending_interaction used to additionally require
# `status == PENDING`, which a replied-to root (moved to ASSIGNED by
# InteractionService.add_interaction_reply) or a Composed root (created
# as ASSIGNED by InteractionService.compose_email) can never satisfy
# again — permanently blocking ticket creation for either, despite
# ticket_id staying None the whole time. Fixed by dropping the
# `status == PENDING` requirement entirely; `ticket_id is None` is the
# one real "not yet on a ticket" signal, matching the frontend exactly.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_interaction_threading.py.

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket import TicketCreate
from app.ticketing.schemas.ticket_from_interaction import TicketFromInteractionCreate
from app.ticketing.services.assignment_service import AssignmentService
from app.ticketing.services.inbox_ticket_service import InboxTicketService

TEAM_LEAD_CATEGORY = "Eligibility"


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_team_lead(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if user.category is not None and user.category.category_name == TEAM_LEAD_CATEGORY:
            return user
    pytest.skip(f"No active seeded Team Lead found for category {TEAM_LEAD_CATEGORY!r}.")


async def _make_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="Inbox Ticket Test Client",
        inbox_email=f"inbox-ticket-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


async def _make_root_interaction(session, *, client_id, status: InteractionStatus) -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.OUTBOUND,
        status=status,
        payload={"message": "test"},
        parent_interaction_id=None,
        ticket_id=None,
        client_id=client_id,
        is_visible=True,
        subject="Test subject",
        received_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()
    return interaction


def _build_service(session) -> InboxTicketService:
    return InboxTicketService(
        ticket_repository=TicketRepository(session),
        interaction_repository=InteractionRepository(session),
        assignment_service=AssignmentService(UserRepository(session)),
        client_repository=ClientRepository(session),
    )


async def test_create_ticket_succeeds_for_already_replied_interaction(db_session):
    """
    The exact reported bug: an interaction that's already been replied
    to (status=ASSIGNED) but never actually put on a ticket
    (ticket_id=None) must still be convertible into a ticket — the
    frontend's own Create Ticket button is shown for exactly this case.
    """

    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["communication:convert_to_ticket"]
    client = await _make_client(db_session, account_manager_id=team_lead.manager_id or team_lead.user_id)
    interaction = await _make_root_interaction(
        db_session, client_id=client.client_id, status=InteractionStatus.ASSIGNED
    )

    service = _build_service(db_session)
    response = await service.create_ticket_from_interaction(
        TicketFromInteractionCreate(
            interaction_id=interaction.interaction_id,
            title="Ticket from replied email",
            ticket_type=TEAM_LEAD_CATEGORY,
            current_priority=TicketPriority.MEDIUM,
            agent_id=None,
        ),
        current_user=team_lead,
    )

    assert response.ticket_id is not None
    assert response.interaction_id == interaction.interaction_id

    ticket = await TicketRepository(db_session).get_by_id(response.ticket_id)
    assert ticket is not None
    assert ticket.client_company_id == client.client_id

    reloaded = await InteractionRepository(db_session).get_by_id(interaction.interaction_id)
    assert reloaded.ticket_id == ticket.ticket_id
    assert reloaded.status == InteractionStatus.ASSIGNED


async def test_create_ticket_succeeds_for_freshly_composed_interaction(db_session):
    """
    A brand-new Compose email (InteractionService.compose_email) is
    also created with status=ASSIGNED, ticket_id=None — the same shape
    as an already-replied-to root. Must be convertible too.
    """

    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["communication:convert_to_ticket"]
    client = await _make_client(db_session, account_manager_id=team_lead.manager_id or team_lead.user_id)
    interaction = await _make_root_interaction(
        db_session, client_id=client.client_id, status=InteractionStatus.ASSIGNED
    )

    service = _build_service(db_session)
    response = await service.create_ticket_from_interaction(
        TicketFromInteractionCreate(
            interaction_id=interaction.interaction_id,
            title="Ticket from composed email",
            ticket_type=TEAM_LEAD_CATEGORY,
            current_priority=TicketPriority.MEDIUM,
            agent_id=None,
        ),
        current_user=team_lead,
    )

    assert response.ticket_id is not None


async def test_create_ticket_still_rejects_already_ticketed_interaction(db_session):
    """
    The one real, still-enforced guard: an interaction that already has
    a ticket_id must still be rejected — this is the actual "already
    converted" signal, unaffected by this fix.
    """

    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["communication:convert_to_ticket"]
    client = await _make_client(db_session, account_manager_id=team_lead.manager_id or team_lead.user_id)
    interaction = await _make_root_interaction(
        db_session, client_id=client.client_id, status=InteractionStatus.ASSIGNED
    )

    existing_ticket = await TicketRepository(db_session).create(
        TicketCreate(
            client_id=None,
            client_company_id=client.client_id,
            agent_id=None,
            created_by=team_lead.user_id,
            title="Pre-existing ticket",
            ticket_type=TEAM_LEAD_CATEGORY,
            current_priority=TicketPriority.MEDIUM,
            custom_fields={},
        )
    )
    interaction.ticket_id = existing_ticket.ticket_id
    await db_session.flush()

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.create_ticket_from_interaction(
            TicketFromInteractionCreate(
                interaction_id=interaction.interaction_id,
                title="Should not be created",
                ticket_type=TEAM_LEAD_CATEGORY,
                current_priority=TicketPriority.MEDIUM,
                agent_id=None,
            ),
            current_user=team_lead,
        )
    assert exc_info.value.status_code == 400
