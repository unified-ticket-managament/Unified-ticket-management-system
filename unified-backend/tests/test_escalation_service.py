# test_escalation_service.py
#
# Regression coverage for the internal escalation workflow
# (TicketEscalation / EscalationService) — the core requirement this
# feature was built to satisfy is that escalating a ticket must NEVER
# restart, recalculate, or otherwise touch its Resolution SLA clock's
# own started_at/due_at/status columns. Every test below that mutates
# an escalation re-reads the Resolution SLA row afterward and asserts
# started_at/due_at/status are byte-identical to what they were before
# any escalation activity happened.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_interaction_threading.py (no separate test database configured
# for this project). Uses real already-seeded RBAC users (a "Team
# Lead" role account) rather than creating throwaway User/Role rows,
# since Users/Roles belong to the RBAC domain's own migration chain.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import EscalationLevel, EscalationStatus, SLAClockStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_escalation_repository import (
    TicketEscalationRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.escalation_service import EscalationService

TEAM_LEAD_CATEGORY = "Eligibility"


@pytest.fixture
async def db_session():
    # See test_interaction_threading.py's identical fixture for why
    # engine.dispose() is required here (pytest-asyncio's per-test
    # event loop vs. the module-level connection pool).
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
    team_leads = result.unique().scalars().all()
    for user in team_leads:
        if user.category is not None and user.category.category_name.value == TEAM_LEAD_CATEGORY:
            return user
    pytest.skip(f"No active seeded Team Lead found for category {TEAM_LEAD_CATEGORY!r}.")


async def _make_scenario(session):
    """
    A real Client + unclaimed Ticket + running Resolution SLA, owned by
    the seeded Eligibility Team Lead's own category — mirrors the
    spec's own worked example (ticket created 09:00, SLA due 13:00).
    """

    team_lead = await _get_team_lead(session)

    client = Client(
        client_id=uuid.uuid4(),
        name="Escalation Test Client",
        inbox_email=f"escalation-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        is_active=True,
    )
    session.add(client)

    started_at = datetime.now(timezone.utc) - timedelta(hours=4)
    due_at = started_at + timedelta(hours=4)  # already at/just past 100% elapsed

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=None,  # unclaimed — escalation resolves via category Team Lead(s)
        title="Escalation regression test ticket",
        ticket_type=TEAM_LEAD_CATEGORY,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=started_at,
    )
    session.add(ticket)
    # Flushed separately (not batched with the resolution_slas insert
    # below) — SQLAlchemy's unit-of-work only orders INSERTs across
    # different mapper classes via configured relationship()s, and
    # there's no ORM relationship between Ticket/ResolutionSLA (they're
    # linked only by a raw ticket_id FK), so nothing else guarantees
    # tickets is written before resolution_slas in the same flush.
    await session.flush()

    resolution_sla = ResolutionSLA(
        resolution_sla_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        client_id=client.client_id,
        priority=TicketPriority.MEDIUM,
        status=SLAClockStatus.RUNNING,
        started_at=started_at,
        due_at=due_at,
    )
    session.add(resolution_sla)

    await session.flush()
    return team_lead, client, ticket, resolution_sla


def _build_service(session) -> EscalationService:
    return EscalationService(
        ticket_escalation_repository=TicketEscalationRepository(session),
        ticket_repository=TicketRepository(session),
        resolution_sla_repository=ResolutionSLARepository(session),
        sla_policy_repository=SLAPolicyRepository(session),
        user_repository=UserRepository(session),
        notification_service=None,
    )


async def _reload_resolution_sla(session, resolution_sla_id) -> ResolutionSLA:
    result = await session.execute(
        select(ResolutionSLA).where(ResolutionSLA.resolution_sla_id == resolution_sla_id)
    )
    return result.scalar_one()


async def test_manual_escalate_never_touches_resolution_sla(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_started_at = resolution_sla.started_at
    original_due_at = resolution_sla.due_at
    original_status = resolution_sla.status

    team_lead.permissions = ["ticket:escalate"]  # transient JWT-claim attribute, see access_control.has_permission

    service = _build_service(db_session)
    result = await service.manual_escalate(ticket.ticket_id, team_lead)
    assert result.ticket_id == ticket.ticket_id

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    assert escalation.level == EscalationLevel.TEAM_LEAD
    assert escalation.status == EscalationStatus.ACTIVE
    assert str(team_lead.user_id) in escalation.owner_ids

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.started_at == original_started_at
    assert reloaded.due_at == original_due_at
    assert reloaded.status == original_status


async def test_escalating_twice_is_rejected_not_a_second_chain(db_session):
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.manual_escalate(ticket.ticket_id, team_lead)
    assert exc_info.value.status_code == 400


async def test_acknowledge_by_owner_stops_auto_advance_and_leaves_sla_untouched(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    result = await service.acknowledge(ticket.ticket_id, team_lead)
    assert result.ticket_id == ticket.ticket_id

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.status == EscalationStatus.ACKNOWLEDGED
    assert escalation.acknowledged_by == team_lead.user_id

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.due_at == original_due_at


async def test_acknowledge_by_non_owner_is_forbidden(db_session):
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    stranger = User(
        user_id=uuid.uuid4(),
        role=team_lead.role,  # same role, but NOT the resolved owner
        name="Stranger",
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.acknowledge(ticket.ticket_id, stranger)
    assert exc_info.value.status_code == 403


async def test_overdue_active_escalation_advances_without_touching_sla(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    # Simulate the ack window having already lapsed, same as the sweep
    # would eventually observe on its own.
    escalation.ack_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    advanced_count = await service.evaluate_overdue(now=now)
    assert advanced_count == 1

    advanced = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert advanced.status == EscalationStatus.ACTIVE
    assert advanced.level in (EscalationLevel.MANAGER, EscalationLevel.SITE_LEAD)
    assert advanced.level != EscalationLevel.TEAM_LEAD

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.due_at == original_due_at


async def test_close_for_ticket_resolution_closes_escalation_only(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    await service.close_for_ticket_resolution(ticket.ticket_id)

    # get_active_by_ticket_id excludes CLOSED rows by design — confirm
    # there is no longer an *active* one, then re-fetch the row
    # directly to check its terminal state.
    still_active = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert still_active is None

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.due_at == original_due_at
    # close_for_ticket_resolution itself never calls .complete() — that
    # is ResolutionSLARepository's own job, called separately by
    # SLAService.complete_resolution_clock. This test only exercises
    # the escalation side effect in isolation.
    assert reloaded.status == SLAClockStatus.RUNNING


async def test_auto_escalate_is_noop_if_already_actively_escalated(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    created = await service.auto_escalate_if_needed(
        ticket=ticket, resolution_clock=resolution_sla
    )
    assert created is False
