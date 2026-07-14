# test_escalation_handling_sla.py
#
# Regression coverage for the escalation-handling SLA — a second,
# wholly independent clock (EscalationHandlingSLA) that starts when an
# escalation is acknowledged (or assignment is treated as acceptance)
# and measures time-to-actually-resolve, target = 25% of the ORIGINAL
# Resolution SLA's configured target duration. The load-bearing
# invariants asserted below: (1) the 25% formula is computed from the
# configured target, never from remaining/overdue time: (2) starting
# the clock is idempotent — acknowledging (or assigning) more than
# once must never create a second row or push due_at forward again;
# (3) none of this ever touches ResolutionSLA's own
# started_at/due_at/status, extending test_escalation_service.py's own
# central invariant to this new clock.
#
# DB-touching tests here follow the exact same convention as
# test_escalation_service.py (real dev DB, rolled back at the end of
# every test) — run this file standalone, not together with the other
# DB-touching test files (see root CLAUDE.md's pytest-asyncio/event-loop
# known issue).

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import EscalationLevel, EscalationStatus, SLAClockStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.escalation_handling_sla import EscalationHandlingSLA
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.escalation_handling_sla_repository import (
    EscalationHandlingSlaRepository,
)
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_escalation_repository import (
    TicketEscalationRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.escalation_handling_sla_service import (
    EscalationHandlingSlaService,
    build_escalation_handling_sla_service,
    compute_escalation_handling_target_seconds,
)
from app.ticketing.services.escalation_service import EscalationService

TEAM_LEAD_CATEGORY = "Eligibility"


# ---------------------------------------------------------
# Pure function — no DB, no event loop involved at all
# ---------------------------------------------------------


def test_compute_escalation_handling_target_is_25_percent_of_configured_target():
    # 4h Resolution SLA (HIGH-priority-shaped) -> 1h handling target.
    assert compute_escalation_handling_target_seconds(240) == 240 * 60 * 0.25
    # 8h -> 2h.
    assert compute_escalation_handling_target_seconds(480) == 480 * 60 * 0.25


def test_compute_escalation_handling_target_rounds_when_not_evenly_divisible():
    # 25 minutes * 60 * 0.25 = 375.0 seconds exactly; pick a value that
    # doesn't divide evenly to exercise round() rather than truncation.
    target = compute_escalation_handling_target_seconds(7)
    assert target == round(7 * 60 * 0.25)
    assert isinstance(target, int)


# ---------------------------------------------------------
# DB-integration tests — same fixture/scenario shape as
# test_escalation_service.py
# ---------------------------------------------------------


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
    team_leads = result.unique().scalars().all()
    for user in team_leads:
        if user.category is not None and user.category.category_name.value == TEAM_LEAD_CATEGORY:
            return user
    pytest.skip(f"No active seeded Team Lead found for category {TEAM_LEAD_CATEGORY!r}.")


async def _make_scenario(session, *, target_minutes: int = 240):
    team_lead = await _get_team_lead(session)

    client = Client(
        client_id=uuid.uuid4(),
        name="Escalation Handling SLA Test Client",
        inbox_email=f"escalation-handling-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        is_active=True,
    )
    session.add(client)

    started_at = datetime.now(timezone.utc) - timedelta(hours=5)
    due_at = started_at + timedelta(minutes=target_minutes)  # already past 100% elapsed

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=None,
        title="Escalation handling SLA regression test ticket",
        ticket_type=TEAM_LEAD_CATEGORY,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=started_at,
    )
    session.add(ticket)
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


def _build_escalation_service(session) -> EscalationService:
    return EscalationService(
        ticket_escalation_repository=TicketEscalationRepository(session),
        ticket_repository=TicketRepository(session),
        resolution_sla_repository=ResolutionSLARepository(session),
        sla_policy_repository=SLAPolicyRepository(session),
        user_repository=UserRepository(session),
        notification_service=None,
        escalation_handling_sla_service=build_escalation_handling_sla_service(session),
    )


async def _get_handling_sla(session, escalation_id) -> EscalationHandlingSLA | None:
    repo = EscalationHandlingSlaRepository(session)
    return await repo.get_by_escalation_id(escalation_id)


async def _reload_resolution_sla(session, resolution_sla_id) -> ResolutionSLA:
    result = await session.execute(
        select(ResolutionSLA).where(ResolutionSLA.resolution_sla_id == resolution_sla_id)
    )
    return result.scalar_one()


async def test_acknowledge_starts_handling_sla_at_25_percent_of_original_target(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_escalation_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    # Captured *after* escalating, not before — escalating itself now
    # permanently bumps the ticket's priority to CRITICAL and reshifts
    # due_at/priority once (see test_escalation_service.py's
    # test_manual_escalate_bumps_priority_to_critical_and_reshifts_due_at).
    # This test is only about whether ACKNOWLEDGE (starting the
    # handling clock) touches the Resolution SLA any further, and
    # "the original target" the handling clock is 25% of is now
    # CRITICAL's, since that's the effective priority at
    # acknowledgment time.
    post_escalate = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    original_started_at = post_escalate.started_at
    original_due_at = post_escalate.due_at
    original_status = post_escalate.status
    assert post_escalate.priority == TicketPriority.CRITICAL

    await service.acknowledge(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    handling_sla = await _get_handling_sla(db_session, escalation.escalation_id)
    assert handling_sla is not None
    assert handling_sla.status == SLAClockStatus.RUNNING

    policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.CRITICAL)
    expected_target_seconds = compute_escalation_handling_target_seconds(
        policy.resolution_target_minutes, policy.handling_sla_percentage / 100
    )
    assert handling_sla.target_seconds == expected_target_seconds
    assert (handling_sla.due_at - handling_sla.started_at).total_seconds() == pytest.approx(
        expected_target_seconds, abs=1
    )

    # ACKNOWLEDGE itself must not touch the Resolution SLA any further.
    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.started_at == original_started_at
    assert reloaded.due_at == original_due_at
    assert reloaded.status == original_status


async def test_acknowledging_twice_never_restarts_the_handling_sla(db_session):
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_escalation_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    first = await _get_handling_sla(db_session, escalation.escalation_id)
    assert first is not None
    first_started_at = first.started_at
    first_due_at = first.due_at

    # acknowledge() itself 400s on a second call (already ACKNOWLEDGED),
    # but the idempotency of start_if_not_started is the thing under
    # test here, not acknowledge()'s own rejection — call the handling
    # SLA start directly a second time, the same way a defensive
    # concurrent-request retry would.
    handling_service = build_escalation_handling_sla_service(db_session)
    ticket_row = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    second = await handling_service.start_if_not_started(
        escalation=escalation, ticket=ticket_row
    )

    assert second is not None
    assert second.escalation_handling_sla_id == first.escalation_handling_sla_id
    assert second.started_at == first_started_at
    assert second.due_at == first_due_at

    all_rows = await db_session.execute(
        select(EscalationHandlingSLA).where(
            EscalationHandlingSLA.escalation_id == escalation.escalation_id
        )
    )
    assert len(all_rows.scalars().all()) == 1


async def test_assignment_implied_acknowledgment_starts_handling_sla_exactly_once(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_escalation_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    # Captured *after* escalating — see the test above for why.
    original_due_at = (
        await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    ).due_at

    # Simulate a supervisor assigning the ticket out (acceptance) before
    # anyone clicked a literal Acknowledge button.
    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.status == EscalationStatus.ACKNOWLEDGED
    assert escalation.acknowledged_by == team_lead.user_id

    handling_sla = await _get_handling_sla(db_session, escalation.escalation_id)
    assert handling_sla is not None
    first_due_at = handling_sla.due_at

    # A later reassignment (acknowledge_via_assignment called again)
    # must not restart the clock.
    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)
    handling_sla_after = await _get_handling_sla(db_session, escalation.escalation_id)
    assert handling_sla_after.due_at == first_due_at

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.due_at == original_due_at


async def test_handling_sla_breach_advances_escalation_and_preserves_both_histories(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_escalation_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    # Captured *after* escalating — see the test above for why.
    original_due_at = (
        await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    ).due_at

    await service.acknowledge(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    handling_sla = await _get_handling_sla(db_session, escalation.escalation_id)

    # Force the handling clock into the past so the sweep's own breach
    # query picks it up.
    handling_sla.due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    handling_service = build_escalation_handling_sla_service(db_session)
    now = datetime.now(timezone.utc)
    breached = await handling_service.evaluate_breaches(now=now)
    assert any(row.escalation_handling_sla_id == handling_sla.escalation_handling_sla_id for row in breached)

    advanced = await service.advance_for_handling_sla_breach(ticket.ticket_id)
    assert advanced is True

    reloaded_escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert reloaded_escalation.status == EscalationStatus.ACTIVE
    assert reloaded_escalation.level != EscalationLevel.TEAM_LEAD

    # Both histories preserved: the handling clock stays breached (not
    # deleted/reset), and the original Resolution SLA is still untouched.
    reloaded_handling = await _get_handling_sla(db_session, escalation.escalation_id)
    assert reloaded_handling.breached_at is not None

    reloaded_resolution = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded_resolution.due_at == original_due_at


async def test_close_for_ticket_resolution_completes_handling_sla(db_session):
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_escalation_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    handling_sla = await _get_handling_sla(db_session, escalation.escalation_id)
    assert handling_sla.status == SLAClockStatus.RUNNING

    await service.close_for_ticket_resolution(ticket.ticket_id)

    reloaded_handling = await _get_handling_sla(db_session, escalation.escalation_id)
    assert reloaded_handling.status == SLAClockStatus.COMPLETED
    assert reloaded_handling.completed_at is not None
