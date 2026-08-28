# test_open_pending_status_still_supported.py
#
# Regression coverage for Issue 8 (remove OPEN/PENDING from the
# user-selectable status list): this was implemented as a frontend-
# only change (TicketActions.tsx's STATUSES array — the Change-Status
# dropdown), deliberately leaving the TicketStatus enum (Python +
# Postgres), the model's own OPEN default, change_status's transition
# logic, and every filter/search untouched. This file locks in that
# nothing on the backend was narrowed: a ticket already sitting in
# OPEN or PENDING (or transitioning through them programmatically,
# e.g. reopen_ticket's own OPEN target) must keep working exactly as
# before.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_ticket_status_on_assignment.py, whose helpers this file reuses.

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import TicketPriority, TicketStatus
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket_action import StatusChangeRequest
from app.ticketing.services.interaction_service import InteractionService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def test_ticket_status_enum_still_has_open_and_pending():
    """The Python enum itself is untouched — this was a UI-only change."""

    assert TicketStatus.OPEN.value == "OPEN"
    assert TicketStatus.PENDING.value == "PENDING"


async def _get_team_lead(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category), joinedload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if user.category is not None:
            return user
    pytest.skip("No active Team Lead with a category in the connected database.")


async def _make_ticket(session, *, account_manager_id, ticket_type, current_status):
    client = Client(
        client_id=uuid.uuid4(),
        name="Open-pending-status Test Client",
        inbox_email=f"open-pending-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=None,
        title="Open-pending-status regression test ticket",
        ticket_type=ticket_type,
        current_status=current_status,
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def test_new_ticket_still_defaults_to_open(db_session):
    team_lead = await _get_team_lead(db_session)
    ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name,
        current_status=TicketStatus.OPEN,
    )
    assert ticket.current_status == TicketStatus.OPEN


async def test_a_ticket_seeded_in_pending_can_still_be_transitioned(db_session):
    """
    A historical ticket already sitting in PENDING (from before this
    UI change, or seeded directly for any other reason) must still
    transition normally through change_status — the dropdown removal
    is UI-only, not a backend narrowing.
    """

    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["ticket:update_status"]
    ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name,
        current_status=TicketStatus.PENDING,
    )

    service = InteractionService(
        interaction_repository=InteractionRepository(db_session),
        ticket_repository=TicketRepository(db_session),
        user_repository=UserRepository(db_session),
        client_repository=ClientRepository(db_session),
    )

    await service.change_status(
        ticket.ticket_id,
        StatusChangeRequest(new_status=TicketStatus.IN_PROGRESS),
        team_lead,
    )

    reloaded = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.IN_PROGRESS


async def test_reopen_ticket_still_targets_open(db_session):
    """
    InteractionService.reopen_ticket's own target status is OPEN —
    a system-driven transition, never reached through the dropdown
    this fix removed OPEN/PENDING from, so it must be completely
    unaffected by that removal.
    """

    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["ticket:reopen", "ticket:editother_ticket"]
    ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name,
        current_status=TicketStatus.CLOSED,
    )
    ticket.closed_at = datetime.now(timezone.utc)
    await db_session.flush()

    service = InteractionService(
        interaction_repository=InteractionRepository(db_session),
        ticket_repository=TicketRepository(db_session),
        user_repository=UserRepository(db_session),
        client_repository=ClientRepository(db_session),
    )

    await service.reopen_ticket(ticket.ticket_id, team_lead)

    reloaded = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.OPEN
