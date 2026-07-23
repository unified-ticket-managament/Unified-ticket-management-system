# test_resolution_sla_resolved_transition.py
#
# Regression coverage for "Resolved status should stop the SLA timer":
# the Resolution SLA used to complete only on the dedicated Close
# Ticket action (entering CLOSED) — entering RESOLVED left the clock
# RUNNING (or PAUSED) until a supervisor later, separately, closed the
# ticket. Fixed by having InteractionService.change_status also call
# SLAService.complete_resolution_clock on entry into RESOLVED (passing
# close_escalation=False, since the separate internal escalation
# workflow must stay untouched by this transition — only an actual
# Close still closes it, via close_for_ticket_resolution).
# ResolutionSLARepository.complete() is itself idempotent (a no-op if
# already COMPLETED, preserving the original completed_at) — so a
# ticket Resolved now and Closed later completes its clock once, at
# the Resolved moment, satisfying "closing a ticket later must not
# affect SLA metrics" with no extra bookkeeping.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_escalation_service.py.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import AuditEventType, SLAClockStatus, TicketPriority
from app.ticketing.models.audit_log import AuditLog
from app.ticketing.models.client import Client
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_edit_access_repository import (
    TicketEditAccessRequestRepository,
)
from app.ticketing.repositories.ticket_escalation_repository import (
    TicketEscalationRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket_action import StatusChangeRequest
from app.ticketing.services.escalation_service import build_escalation_service
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.sla_service import build_sla_service

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


async def _make_scenario(session, *, agent_id, initial_status="IN_PROGRESS"):
    team_lead = await _get_team_lead(session)

    client = Client(
        client_id=uuid.uuid4(),
        name="Resolved-SLA Test Client",
        inbox_email=f"resolved-sla-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        is_active=True,
    )
    session.add(client)

    started_at = datetime.now(timezone.utc) - timedelta(hours=1)

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="Resolved-stops-SLA-timer regression test ticket",
        ticket_type=TEAM_LEAD_CATEGORY,
        current_status=initial_status,
        current_priority=TicketPriority.MEDIUM,
        created_at=started_at,
    )
    session.add(ticket)
    await session.flush()

    medium_policy = await SLAPolicyRepository(session).get_by_priority(TicketPriority.MEDIUM)

    resolution_sla = ResolutionSLA(
        resolution_sla_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        client_id=client.client_id,
        priority=TicketPriority.MEDIUM,
        status=SLAClockStatus.RUNNING,
        started_at=started_at,
        due_at=started_at + timedelta(hours=3),
        active_target_minutes=medium_policy.resolution_target_minutes,
    )
    session.add(resolution_sla)
    await session.flush()

    return team_lead, client, ticket, resolution_sla


def _build_interaction_service(session) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
        edit_access_repository=TicketEditAccessRequestRepository(session),
        sla_service=build_sla_service(session),
        escalation_service=build_escalation_service(session),
    )


async def _reload_resolution_sla(session, resolution_sla_id) -> ResolutionSLA:
    result = await session.execute(
        select(ResolutionSLA).where(ResolutionSLA.resolution_sla_id == resolution_sla_id)
    )
    return result.scalar_one()


async def test_resolved_transition_completes_the_sla_clock(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, agent_id=None, initial_status="IN_PROGRESS"
    )
    team_lead.permissions = ["ticket:update_status"]
    service = _build_interaction_service(db_session)

    reloaded_before = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded_before.status == SLAClockStatus.RUNNING
    assert reloaded_before.completed_at is None

    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="RESOLVED"), team_lead
    )

    reloaded_after = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded_after.status == SLAClockStatus.COMPLETED
    assert reloaded_after.completed_at is not None


async def test_sla_keeps_running_through_open_and_in_progress(db_session):
    """Sanity check that the fix is scoped to RESOLVED — earlier, non-terminal transitions must not complete the clock."""

    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, agent_id=None, initial_status="OPEN"
    )
    team_lead.permissions = ["ticket:update_status"]
    service = _build_interaction_service(db_session)

    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="IN_PROGRESS"), team_lead
    )

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.status == SLAClockStatus.RUNNING
    assert reloaded.completed_at is None


async def test_closing_a_ticket_after_resolved_does_not_change_sla_metrics(db_session):
    """
    'Closing the ticket later should NOT affect SLA timing' —
    ResolutionSLARepository.complete()'s own pre-existing idempotency
    (a no-op once already COMPLETED) is what guarantees this; this test
    is the regression coverage proving it actually holds through the
    real Resolved -> Closed call sequence, not just in isolation.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, agent_id=None, initial_status="IN_PROGRESS"
    )
    team_lead.permissions = [
        "ticket:update_status",
        "ticket:close_ticket",
        "ticket:archive_attachment",
    ]
    service = _build_interaction_service(db_session)

    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="RESOLVED"), team_lead
    )
    resolved_clock = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    completed_at_when_resolved = resolved_clock.completed_at
    assert completed_at_when_resolved is not None

    await service.close_ticket(ticket.ticket_id, team_lead)

    closed_clock = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert closed_clock.status == SLAClockStatus.COMPLETED
    # The exact same timestamp — close_ticket's own complete_resolution_clock
    # call is a genuine no-op against an already-completed clock.
    assert closed_clock.completed_at == completed_at_when_resolved


async def test_waiting_for_client_to_resolved_resumes_then_completes(db_session):
    """
    A ticket resolved directly out of WAITING_FOR_CLIENT must genuinely
    resume first (so the pre-existing SLA_RESUMED audit log stays
    accurate) and only then complete — not complete against a clock
    that's still PAUSED, which would make that resume call a silent
    no-op behind a misleading audit row. Regression test for the
    ordering bug this exact fix could have introduced.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, agent_id=None, initial_status="WAITING_FOR_CLIENT"
    )
    resolution_sla.status = SLAClockStatus.PAUSED
    resolution_sla.paused_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    await db_session.flush()

    team_lead.permissions = ["ticket:update_status"]
    service = _build_interaction_service(db_session)

    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="RESOLVED"), team_lead
    )

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.status == SLAClockStatus.COMPLETED
    assert reloaded.completed_at is not None

    audit_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == ticket.ticket_id,
            AuditLog.event_type == AuditEventType.SLA_RESUMED,
        )
    )
    assert audit_result.scalars().first() is not None


async def test_resolved_transition_does_not_close_an_active_escalation(db_session):
    """
    The Resolution SLA measures time-to-resolve and completes on
    RESOLVED, but the separate internal escalation/ownership workflow
    must stay untouched by that same transition — only an actual Close
    still closes it (close_escalation=False is passed from the
    RESOLVED branch specifically to guarantee this).
    """

    staff_agent = None
    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, agent_id=staff_agent, initial_status="IN_PROGRESS"
    )

    team_lead.permissions = [
        "ticket:escalate",
        "ticket:update_status",
        "ticket:editother_ticket",
    ]
    escalation_service = build_escalation_service(db_session)
    await escalation_service.manual_escalate(ticket.ticket_id, team_lead)

    # Accept the escalation first (acknowledge + confirm the ticket
    # stays with its current — unclaimed — assignment) so the ticket
    # isn't itself frozen (see test_escalation_read_only_access.py) by
    # the time change_status runs below — this test is specifically
    # about escalation state surviving a RESOLVED transition, not about
    # the freeze itself.
    await escalation_service.acknowledge(ticket.ticket_id, team_lead)
    await escalation_service.confirm_assignment(ticket.ticket_id, team_lead)

    escalation_repo = TicketEscalationRepository(db_session)
    escalation_before = await escalation_repo.get_active_by_ticket_id(ticket.ticket_id)
    assert escalation_before is not None

    service = _build_interaction_service(db_session)
    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="RESOLVED"), team_lead
    )

    escalation_after = await escalation_repo.get_active_by_ticket_id(ticket.ticket_id)
    assert escalation_after is not None
    assert escalation_after.escalation_id == escalation_before.escalation_id

    reloaded_clock = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded_clock.status == SLAClockStatus.COMPLETED
