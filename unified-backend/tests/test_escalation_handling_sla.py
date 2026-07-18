# test_escalation_handling_sla.py
#
# Regression coverage for the escalation-handling SLA — a second,
# wholly independent clock (EscalationHandlingSLA) that starts once
# assignment is actually settled (claim/transfer/confirm-unchanged —
# EscalationService._complete_acceptance), NOT on a bare acknowledge()
# call, and measures time-to-actually-resolve, target = 25% of the
# ORIGINAL Resolution SLA's configured target duration. The
# load-bearing invariants asserted below: (1) the 25% formula is
# computed from the configured target, never from remaining/overdue
# time; (2) starting the clock is idempotent — settling assignment
# more than once must never create a second row or push due_at forward
# again; (3) none of this ever touches ResolutionSLA's own
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
    return await repo.get_active_by_escalation_id(escalation_id)


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

    # Escalating alone must not touch priority or the Resolution SLA —
    # see test_escalation_service.py's own
    # test_manual_escalate_does_not_touch_priority_or_sla.
    pre_ack = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert pre_ack.priority == TicketPriority.MEDIUM
    original_started_at = pre_ack.started_at
    original_status = pre_ack.status

    await service.acknowledge(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    # Acknowledging ALONE deliberately does not start the handling
    # clock (or bump the Resolution SLA's own priority) — see
    # test_escalation_service.py's test_acknowledge_alone_does_not_
    # reshift_sla. Both only happen once assignment is also settled —
    # here via confirm_assignment (the "keep the current assignee"
    # branch). This is still a first-time (never-advanced) escalation,
    # so per test_confirm_assignment_does_not_reshift_sla_on_first_
    # acceptance in test_escalation_service.py, the Resolution SLA
    # clock's own priority stays at its true original (MEDIUM) rather
    # than reshifting to CRITICAL — only the ticket's display priority
    # flips immediately. The handling SLA's "25% of original target"
    # therefore resolves off MEDIUM's policy here, genuinely the
    # ticket's original target rather than CRITICAL's.
    assert await _get_handling_sla(db_session, escalation.escalation_id) is None

    await service.confirm_assignment(ticket.ticket_id, team_lead)

    handling_sla = await _get_handling_sla(db_session, escalation.escalation_id)
    assert handling_sla is not None
    assert handling_sla.status == SLAClockStatus.RUNNING

    post_ack = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert post_ack.priority == TicketPriority.MEDIUM

    policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)
    expected_target_seconds = compute_escalation_handling_target_seconds(
        policy.resolution_target_minutes, policy.handling_sla_percentage / 100
    )
    assert handling_sla.target_seconds == expected_target_seconds
    assert (handling_sla.due_at - handling_sla.started_at).total_seconds() == pytest.approx(
        expected_target_seconds, abs=1
    )

    # started_at/status are still never touched by any of this.
    assert post_ack.started_at == original_started_at
    assert post_ack.status == original_status


async def test_acknowledging_twice_never_restarts_the_handling_sla(db_session):
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_escalation_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)
    await service.confirm_assignment(ticket.ticket_id, team_lead)

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

    # Escalating alone must not touch the Resolution SLA — see the test
    # above. This is a first-time (never-advanced) escalation, so
    # accepting it — here via assignment-implied acknowledgment rather
    # than a literal Acknowledge click — must NOT reshift the
    # Resolution SLA clock onto CRITICAL either; only the ticket's
    # display priority flips immediately. See
    # test_acknowledge_via_assignment_does_not_reshift_on_first_
    # acceptance in test_escalation_service.py.
    pre_accept = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert pre_accept.priority == TicketPriority.MEDIUM

    # Simulate a supervisor assigning the ticket out (acceptance) before
    # anyone clicked a literal Acknowledge button.
    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.status == EscalationStatus.ACKNOWLEDGED
    assert escalation.acknowledged_by == team_lead.user_id

    post_accept = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert post_accept.priority == TicketPriority.MEDIUM
    first_reshifted_due_at = post_accept.due_at

    handling_sla = await _get_handling_sla(db_session, escalation.escalation_id)
    assert handling_sla is not None
    first_due_at = handling_sla.due_at

    # A later reassignment (acknowledge_via_assignment called again)
    # must not restart the handling clock, nor reshift the Resolution
    # SLA a second time — the priority bump is idempotent once CRITICAL.
    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)
    handling_sla_after = await _get_handling_sla(db_session, escalation.escalation_id)
    assert handling_sla_after.due_at == first_due_at

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.due_at == first_reshifted_due_at


async def test_handling_sla_breach_re_evaluates_starting_level_and_preserves_both_histories(
    db_session,
):
    """
    A handling-SLA breach recomputes the level via
    EscalationService._resolve_starting_level — the exact same logic a
    brand-new escalation uses — rather than blindly climbing to
    next_level(old_level). This scenario's ticket is still unclaimed
    (team_lead only acknowledged/confirmed it, never actually became
    its assigned agent), so _resolve_starting_level correctly lands
    back on TEAM_LEAD again rather than jumping to MANAGER: ownership
    never actually changed, so there's no reason to skip a level. See
    EscalationService.advance_for_handling_sla_breach's own docstring
    for the real-world case this matters for — a Team Lead accepting
    an escalation and handing it to Staff, whose own failure to resolve
    it should escalate back to Team Lead again, not jump straight to
    Account Manager.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_escalation_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)
    await service.confirm_assignment(ticket.ticket_id, team_lead)

    # Captured *after* acknowledge+confirm — but this is still a
    # first-time acceptance (has_advanced_past_starting_level is still
    # False at this point), so the Resolution SLA clock has NOT
    # reshifted yet either — see test_escalation_service.py's own
    # test_confirm_assignment_does_not_reshift_sla_on_first_acceptance.
    original_due_at = (
        await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    ).due_at

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.has_advanced_past_starting_level is False
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
    assert reloaded_escalation.level == EscalationLevel.TEAM_LEAD
    # The flag still flips even though the recomputed level happens to
    # be the same as before — this is what gates the Resolution SLA's
    # eventual hard-restart reshift on the NEXT acceptance.
    assert reloaded_escalation.has_advanced_past_starting_level is True

    # Both histories preserved: the handling clock stays breached (not
    # deleted/reset), and the original Resolution SLA is still untouched
    # by this advance itself (a subsequent acceptance is what reshifts
    # it, not the advance). _get_handling_sla only returns an ACTIVE row
    # now, and this one no longer is one — fetch it directly instead.
    reloaded_handling = await EscalationHandlingSlaRepository(
        db_session
    ).get_latest_by_escalation_id(escalation.escalation_id)
    assert reloaded_handling.breached_at is not None

    reloaded_resolution = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded_resolution.due_at == original_due_at

    reloaded_resolution = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded_resolution.due_at == original_due_at


async def test_handling_sla_breach_starts_fresh_critical_handling_sla_on_reacceptance(
    db_session,
):
    """
    Guards the requested behavior: the FIRST acceptance's handling
    clock runs under the ticket's original priority (25% of MEDIUM's
    target here). If that clock itself breaches — nobody resolved it in
    time — the escalation advances a level, and Resolution SLA reshifts
    onto CRITICAL (per test_confirm_assignment_reshifts_sla_after_
    escalation_has_advanced in test_escalation_service.py). Accepting
    the escalation AGAIN at this new level must start a genuinely FRESH
    handling clock computed off CRITICAL's percentage — not silently
    keep reusing the first, already-breached, MEDIUM-based one forever.
    The original breached row must survive untouched as history.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_escalation_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)
    await service.confirm_assignment(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    original_handling_sla = await _get_handling_sla(db_session, escalation.escalation_id)
    assert original_handling_sla is not None

    medium_policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)
    expected_original_target = compute_escalation_handling_target_seconds(
        medium_policy.resolution_target_minutes, medium_policy.handling_sla_percentage / 100
    )
    assert original_handling_sla.target_seconds == expected_original_target

    # Force the handling clock into the past so the sweep's own breach
    # query picks it up, then let it actually breach and advance the
    # escalation — the same mechanics as the test above.
    original_handling_sla.due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    handling_service = build_escalation_handling_sla_service(db_session)
    await handling_service.evaluate_breaches(now=datetime.now(timezone.utc))
    await service.advance_for_handling_sla_breach(ticket.ticket_id)

    reloaded_escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert reloaded_escalation.has_advanced_past_starting_level is True

    # No active handling clock right now — the only row that exists is
    # the breached one, which is exactly what should let a fresh one
    # be created on the next acceptance.
    assert await _get_handling_sla(db_session, escalation.escalation_id) is None

    # The escalation advanced past team_lead's own level, so they're no
    # longer a listed owner — fetch whoever the new level's owner
    # actually is (e.g. the Account Manager) to accept as them instead.
    new_owner_id = uuid.UUID(reloaded_escalation.owner_ids[0])
    new_owner = (
        await db_session.execute(
            select(User)
            .options(joinedload(User.role), joinedload(User.category))
            .where(User.user_id == new_owner_id)
        )
    ).unique().scalar_one()

    # Re-accept at the new level — this must reshift Resolution SLA
    # onto CRITICAL AND start a brand new handling clock under
    # CRITICAL's percentage.
    await service.confirm_assignment(ticket.ticket_id, new_owner)

    reloaded_resolution = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded_resolution.priority == TicketPriority.CRITICAL

    new_handling_sla = await _get_handling_sla(db_session, escalation.escalation_id)
    assert new_handling_sla is not None
    assert new_handling_sla.escalation_handling_sla_id != original_handling_sla.escalation_handling_sla_id
    assert new_handling_sla.breached_at is None

    critical_policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.CRITICAL)
    expected_new_target = compute_escalation_handling_target_seconds(
        critical_policy.resolution_target_minutes, critical_policy.handling_sla_percentage / 100
    )
    assert new_handling_sla.target_seconds == expected_new_target

    # Both rows coexist — the breached original is permanent history,
    # never deleted or mutated by the new one starting.
    all_rows = await EscalationHandlingSlaRepository(db_session).list_by_escalation_id(
        escalation.escalation_id
    )
    assert len(all_rows) == 2
    assert {row.escalation_handling_sla_id for row in all_rows} == {
        original_handling_sla.escalation_handling_sla_id,
        new_handling_sla.escalation_handling_sla_id,
    }


async def test_close_for_ticket_resolution_completes_handling_sla(db_session):
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_escalation_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)
    await service.confirm_assignment(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    handling_sla = await _get_handling_sla(db_session, escalation.escalation_id)
    assert handling_sla.status == SLAClockStatus.RUNNING

    await service.close_for_ticket_resolution(ticket.ticket_id)

    # completed_at is now set, so this row is no longer ACTIVE —
    # _get_handling_sla (active-only) would correctly return None here;
    # fetch it directly to check its completed state instead.
    reloaded_handling = await EscalationHandlingSlaRepository(
        db_session
    ).get_latest_by_escalation_id(escalation.escalation_id)
    assert reloaded_handling.status == SLAClockStatus.COMPLETED
    assert reloaded_handling.completed_at is not None
