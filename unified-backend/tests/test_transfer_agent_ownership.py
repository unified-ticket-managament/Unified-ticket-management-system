# test_transfer_agent_ownership.py
#
# Regression coverage for InteractionService.transfer_agent's
# candidate-resolution rules, focused on the self-assignment bug fixed
# in this session: a Team Lead/Account Manager/Site Lead/Super Admin
# selecting "Myself" during Acknowledge & Assign used to be rejected
# outright ("New agent must be an active Staff member, or an active
# Team Lead when transferred by an Account Manager, Site Lead, or
# Super Admin.") because the candidate-resolution branches only ever
# considered *other* named agents, never the caller themselves — see
# InteractionService.transfer_agent's own comments for the fix (a
# dedicated self-assignment branch, checked first, for any of the four
# supervisor roles).
#
# Also covers the new Super Admin -> Site Lead transfer branch, and a
# smoke check that the tightened Account-Manager-target role
# restriction (Site Lead/Super Admin only, per the Acknowledge & Assign
# role table) still rejects a Team Lead attempting the same transfer.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_escalation_service.py.

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket_action import TransferAgentRequest
from app.ticketing.services.interaction_service import InteractionService

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
        if user.category is not None and user.category.category_name.value == TEAM_LEAD_CATEGORY:
            return user
    pytest.skip(f"No active seeded Team Lead found for category {TEAM_LEAD_CATEGORY!r}.")


async def _get_staff(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if user.category is not None and user.category.category_name.value == TEAM_LEAD_CATEGORY:
            return user
    pytest.skip(f"No active seeded Staff found for category {TEAM_LEAD_CATEGORY!r}.")


async def _get_user_by_role(session, role_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == role_name, User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip(f"No active seeded {role_name!r} found.")


async def _make_ticket(session, *, account_manager_id, agent_id=None):
    client = Client(
        client_id=uuid.uuid4(),
        name="Transfer Test Client",
        inbox_email=f"transfer-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="Transfer regression test ticket",
        ticket_type=TEAM_LEAD_CATEGORY,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return client, ticket


def _build_service(session) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
    )


async def test_team_lead_can_assign_escalated_ticket_to_self(db_session):
    """
    The reported bug: a Team Lead selecting "Myself" after acknowledging
    an escalation used to 400 with "New agent must be an active Staff
    member...". Assigning to self must always succeed.
    """

    team_lead = await _get_team_lead(db_session)
    staff = await _get_staff(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    response = await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=team_lead.user_id, reason="Taking this on myself"),
        team_lead,
    )

    assert response.ticket_id == ticket.ticket_id
    updated = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert updated.agent_id == team_lead.user_id


async def test_account_manager_can_assign_escalated_ticket_to_self(db_session):
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    staff = await _get_staff(db_session)
    _client, ticket = await _make_ticket(
        db_session, account_manager_id=account_manager.user_id, agent_id=staff.user_id
    )

    service = _build_service(db_session)
    response = await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=account_manager.user_id, reason="Taking this on myself"),
        account_manager,
    )

    assert response.ticket_id == ticket.ticket_id
    updated = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert updated.agent_id == account_manager.user_id


async def test_site_lead_can_assign_escalated_ticket_to_self(db_session):
    site_lead = await _get_user_by_role(db_session, "Site Lead")
    staff = await _get_staff(db_session)
    _client, ticket = await _make_ticket(
        db_session, account_manager_id=site_lead.user_id, agent_id=staff.user_id
    )

    service = _build_service(db_session)
    response = await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=site_lead.user_id, reason="Taking this on myself"),
        site_lead,
    )

    assert response.ticket_id == ticket.ticket_id
    updated = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert updated.agent_id == site_lead.user_id


async def test_super_admin_can_assign_escalated_ticket_to_self(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    staff = await _get_staff(db_session)
    _client, ticket = await _make_ticket(
        db_session, account_manager_id=super_admin.user_id, agent_id=staff.user_id
    )

    service = _build_service(db_session)
    response = await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=super_admin.user_id, reason="Taking this on myself"),
        super_admin,
    )

    assert response.ticket_id == ticket.ticket_id
    updated = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert updated.agent_id == super_admin.user_id


async def test_super_admin_can_assign_ticket_to_a_site_lead(db_session):
    """
    New candidate branch: only Super Admin may hand a ticket directly
    to a Site Lead (see the Acknowledge & Assign role table).
    """

    super_admin = await _get_user_by_role(db_session, "Super Admin")
    site_lead = await _get_user_by_role(db_session, "Site Lead")
    staff = await _get_staff(db_session)
    _client, ticket = await _make_ticket(
        db_session, account_manager_id=super_admin.user_id, agent_id=staff.user_id
    )

    service = _build_service(db_session)
    response = await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=site_lead.user_id, reason="Escalating to Site Lead"),
        super_admin,
    )

    assert response.ticket_id == ticket.ticket_id
    updated = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert updated.agent_id == site_lead.user_id


async def test_team_lead_cannot_assign_ticket_to_an_account_manager(db_session):
    """
    Per the Acknowledge & Assign role table, a Team Lead may only hand a
    ticket to themselves or to Staff — never to an Account Manager or a
    Site Lead. Smoke check for the tightened role restriction added
    alongside the self-assignment fix.
    """

    team_lead = await _get_team_lead(db_session)
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    _client, ticket = await _make_ticket(
        db_session, account_manager_id=team_lead.manager_id or team_lead.user_id
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.transfer_agent(
            ticket.ticket_id,
            TransferAgentRequest(new_agent_id=account_manager.user_id, reason="Invalid"),
            team_lead,
        )
    assert exc_info.value.status_code == 400
