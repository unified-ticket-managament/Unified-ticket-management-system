# test_escalation_service.py
#
# Regression coverage for the internal escalation workflow
# (TicketEscalation / EscalationService). Two deliberate exceptions to
# "escalating must never restart/recalculate the Resolution SLA clock,"
# split into two separate moments on purpose:
#
# 1. The ticket's priority permanently becomes CRITICAL the instant it
#    escalates — manual_escalate/auto_escalate_if_needed, via
#    EscalationService._set_ticket_priority_to_critical. Plain
#    Ticket.current_priority write; the Resolution SLA clock itself is
#    NOT touched here — test_manual_escalate_bumps_priority_but_leaves_
#    sla_untouched below is the test that guards this split.
# 2. Acknowledging alone (acknowledge()) only stops the ack-window
#    auto-advance — it does NOT reshift the Resolution SLA clock and
#    does NOT advance the handling stage. Only once a supervisor has
#    ALSO settled who the ticket is assigned to —
#    acknowledge_via_assignment() (claim_ticket/transfer_agent) or
#    confirm_assignment() (the "keep the current assignee" case) — does
#    EscalationService._complete_acceptance advance the handling stage
#    AND reshift the Resolution SLA clock, to
#    original_priority.resolution_target_minutes x
#    handling_stage_percentages[stage]. See
#    test_acknowledge_alone_does_not_reshift_sla below.
#
# As of the 2026-07-20 handling-stage redesign: ResolutionSLA.priority
# is NEVER forced to CRITICAL (it stays at the escalation's own
# original_priority for the ticket's whole life — only
# Ticket.current_priority, the visible badge, becomes CRITICAL).
# handling_stage/handling_stage_started_at/handling_stage_due_at are
# genuinely independent of has_advanced_past_starting_level (which
# only tracks ownership-ladder movement) — an acknowledgment-window
# timeout (evaluate_overdue) must NEVER advance the handling stage or
# reshift the clock; only a genuine accept -> assign ->
# (handling-stage-window-elapses) -> re-accept cycle does. See
# test_ack_timeout_ladder_advance_does_not_advance_handling_stage below
# for the regression test covering exactly this distinction.
#
# started_at/status are still never touched by ANYTHING in this file.
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
from shared_models.models import Category, Role, User

from app.database.session import AsyncSessionLocal, engine
from app.notifications.models import Notification
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.rbac.models.reporting_manager_team import ReportingManagerTeam
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.ticketing.enums import (
    TRIGGERED_BY_MANUAL,
    AuditEventType,
    EscalationLevel,
    EscalationStatus,
    SLAClockStatus,
    TicketPriority,
)
from app.ticketing.models.audit_log import AuditLog
from app.ticketing.models.client import Client
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_escalation import TicketEscalation
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


async def _make_scenario(session, *, agent_id=None):
    """
    A real Client + Ticket + running Resolution SLA, owned by the
    seeded Eligibility Team Lead's own category — mirrors the spec's
    own worked example (ticket created 09:00, SLA due 13:00).
    `agent_id` defaults to None (unclaimed — escalation resolves via
    category Team Lead(s)); pass the Team Lead's or an Account
    Manager's own user_id to exercise _resolve_starting_level's
    skip-a-level behavior for a ticket they already own themselves.
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
        agent_id=agent_id,
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

    # active_target_minutes is read from the real seeded MEDIUM policy
    # rather than hardcoded, so every stage-based assertion below (which
    # also reads the same policy at test time) stays self-consistent
    # even if the seeded target/percentages are ever retuned.
    medium_policy = await SLAPolicyRepository(session).get_by_priority(TicketPriority.MEDIUM)

    resolution_sla = ResolutionSLA(
        resolution_sla_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        client_id=client.client_id,
        priority=TicketPriority.MEDIUM,
        status=SLAClockStatus.RUNNING,
        started_at=started_at,
        due_at=due_at,
        active_target_minutes=medium_policy.resolution_target_minutes,
    )
    session.add(resolution_sla)

    await session.flush()
    return team_lead, client, ticket, resolution_sla


def _build_service(session, *, with_notifications: bool = False) -> EscalationService:
    return EscalationService(
        ticket_escalation_repository=TicketEscalationRepository(session),
        ticket_repository=TicketRepository(session),
        resolution_sla_repository=ResolutionSLARepository(session),
        sla_policy_repository=SLAPolicyRepository(session),
        user_repository=UserRepository(session),
        notification_service=(
            NotificationService(NotificationRepository(session)) if with_notifications else None
        ),
    )


async def _reload_resolution_sla(session, resolution_sla_id) -> ResolutionSLA:
    result = await session.execute(
        select(ResolutionSLA).where(ResolutionSLA.resolution_sla_id == resolution_sla_id)
    )
    return result.scalar_one()


async def _get_account_manager(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Account Manager", User.is_active.is_(True))
    )
    account_managers = result.unique().scalars().all()
    if account_managers:
        return account_managers[0]
    pytest.skip("No active seeded Account Manager found.")


async def _get_site_lead(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Site Lead", User.is_active.is_(True))
    )
    site_leads = result.unique().scalars().all()
    if site_leads:
        return site_leads[0]
    pytest.skip("No active seeded Site Lead found.")


async def _get_staff_in_category(session, category_name: str) -> list[User]:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    staff = result.unique().scalars().all()
    return [
        u for u in staff if u.category is not None and u.category.category_name.value == category_name
    ]


async def test_escalation_of_team_lead_owned_ticket_starts_at_manager_level(db_session):
    """
    A ticket the Team Lead already owns themselves must escalate
    straight to MANAGER (their own Account Manager) — re-notifying the
    same Team Lead who already has it and isn't acting on it would be
    pointless. See EscalationService._resolve_starting_level.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(
        db_session, agent_id=None
    )
    # Assign the ticket to the Team Lead themselves *after* scenario
    # creation, so the fixture's own client/resolution-sla setup stays
    # identical to every other test — only ownership changes.
    ticket.agent_id = team_lead.user_id
    await db_session.flush()

    team_lead.permissions = ["ticket:escalate"]
    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    assert escalation.level == EscalationLevel.MANAGER
    assert str(team_lead.manager_id) in escalation.owner_ids
    # Confirms the Team Lead themselves is NOT re-notified as an owner
    # of their own escalation.
    assert str(team_lead.user_id) not in escalation.owner_ids


async def test_escalation_of_account_manager_owned_ticket_starts_at_site_lead_level(db_session):
    """
    A ticket an Account Manager already owns themselves must escalate
    straight to SITE_LEAD — the next (and only remaining) level above
    them. See EscalationService._resolve_starting_level.
    """

    account_manager = await _get_account_manager(db_session)
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(
        db_session, agent_id=account_manager.user_id
    )

    account_manager.permissions = ["ticket:escalate"]
    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, account_manager)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    assert escalation.level == EscalationLevel.SITE_LEAD
    assert str(account_manager.user_id) not in escalation.owner_ids


async def test_manual_escalate_bumps_priority_but_leaves_sla_untouched(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_started_at = resolution_sla.started_at
    original_due_at = resolution_sla.due_at
    original_status = resolution_sla.status
    assert ticket.current_priority == TicketPriority.MEDIUM

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

    # Escalation CREATION itself bumps the ticket's own priority to
    # CRITICAL immediately (a plain display/filter field)...
    reloaded_ticket = await service.ticket_repository.get_by_id(ticket.ticket_id)
    assert reloaded_ticket.current_priority == TicketPriority.CRITICAL

    # ...but the Resolution SLA clock itself must stay completely
    # untouched — it only reshifts onto CRITICAL's target once a
    # supervisor actually acknowledges or assigns the escalation (see
    # the acknowledge tests below).
    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    assert reloaded.started_at == original_started_at
    assert reloaded.status == original_status
    assert reloaded.due_at == original_due_at


async def test_acknowledge_alone_does_not_reshift_sla(db_session):
    """
    Acknowledging alone (no assignment decision yet) must leave the
    Resolution SLA clock completely untouched — it only stops the
    ack-window auto-advance. This is the core "Resolution SLA starts
    only after Acknowledge AND Assign" requirement: a supervisor who
    acknowledges and then never gets around to assigning anyone must
    never have silently started the clock in the meantime.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_started_at = resolution_sla.started_at
    original_due_at = resolution_sla.due_at
    original_status = resolution_sla.status
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    # Priority is already CRITICAL from escalating alone (see the test
    # above) — the clock itself is still on its original target until
    # assignment is also settled.
    pre_ack = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert pre_ack.priority == TicketPriority.MEDIUM
    assert pre_ack.due_at == original_due_at

    await service.acknowledge(ticket.ticket_id, team_lead)

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    assert reloaded.started_at == original_started_at
    assert reloaded.status == original_status
    assert reloaded.due_at == original_due_at


async def test_confirm_assignment_reshifts_sla_to_stage_1_on_first_acceptance(db_session):
    """
    The "keep the current assignee" branch: Acknowledge (step 1) is
    clicked first — leaving the clock untouched (see the test above) —
    and confirm_assignment (step 2's no-reassignment branch) completes
    acceptance. As of the handling-stage redesign, even a first-time
    acceptance now reshifts the Resolution SLA — onto
    handling_stage=1's target (original_priority's resolution_target
    x handling_stage_percentages[0]), never CRITICAL's — since the
    clock's target is no longer tied to `priority` at all
    (active_target_minutes carries it directly). priority itself stays
    at original_priority (MEDIUM here) for the ticket's whole life.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)

    still_untouched = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert still_untouched.due_at == original_due_at

    result = await service.confirm_assignment(ticket.ticket_id, team_lead)
    assert result.ticket_id == ticket.ticket_id

    policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)
    expected_target_minutes = round(
        policy.resolution_target_minutes * policy.handling_stage_percentages[0] / 100
    )

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    assert reloaded.due_at != original_due_at
    assert reloaded.active_target_minutes == expected_target_minutes

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.handling_stage == 1
    assert escalation.handling_stage_started_at is not None
    assert escalation.handling_stage_due_at is not None


async def test_confirm_assignment_advances_to_stage_2_after_stage_1_elapses(db_session):
    """
    A genuine "second time" acceptance — stage 1 already ran and its
    window elapsed (simulated by clearing handling_stage_due_at back to
    NULL directly, exactly what the sweep does on a real breach — see
    test_advance_for_handling_sla_breach_clears_stage_due_at_and_
    advances_ladder for that side in isolation) — reshifts the
    Resolution SLA onto stage 2's (smaller) percentage of the SAME
    original priority's target, and increments handling_stage to 2.
    Deliberately NOT driven via has_advanced_past_starting_level (the
    escalation-ladder flag) at all — handling-stage progression is
    independent of it by design; see the ack-timeout test below for the
    case that flag WOULD be set without any real handling-stage
    advance happening.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)
    await service.confirm_assignment(ticket.ticket_id, team_lead)

    stage_1 = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    stage_1_due_at = stage_1.due_at

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.handling_stage == 1
    # Simulate stage 1's window having elapsed with nobody resolving it
    # — the sweep would clear this same field the same way (see
    # advance_for_handling_sla_breach).
    escalation.handling_stage_due_at = None
    await db_session.flush()

    result = await service.confirm_assignment(ticket.ticket_id, team_lead)
    assert result.ticket_id == ticket.ticket_id

    policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)
    expected_target_minutes = round(
        policy.resolution_target_minutes * policy.handling_stage_percentages[1] / 100
    )

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    assert reloaded.due_at != stage_1_due_at
    assert reloaded.active_target_minutes == expected_target_minutes

    reloaded_escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert reloaded_escalation.handling_stage == 2


async def test_confirm_assignment_requires_no_active_escalation_to_400(db_session):
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.confirm_assignment(ticket.ticket_id, team_lead)
    assert exc_info.value.status_code == 400


async def test_confirm_assignment_by_non_owner_is_forbidden(db_session):
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
        await service.confirm_assignment(ticket.ticket_id, stranger)
    assert exc_info.value.status_code == 403


async def test_acknowledge_by_site_lead_before_their_level_is_forbidden(db_session):
    """
    Guards the removal of the old GLOBAL_INBOX_ROLE_NAMES "company-wide
    overseer" bypass in acknowledge()/confirm_assignment(): escalation
    must progress one level at a time, so a Site Lead/Super Admin must
    NOT be able to acknowledge a TEAM_LEAD-level escalation just
    because their role is a global overseer everywhere else in this
    codebase — they only become a real owner (owner_ids) once the
    chain actually reaches SITE_LEAD.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]
    site_lead = await _get_site_lead(db_session)

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.acknowledge(ticket.ticket_id, site_lead)
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        await service.confirm_assignment(ticket.ticket_id, site_lead)
    assert exc_info.value.status_code == 403


async def test_acknowledge_via_assignment_reshifts_sla_to_stage_1_on_first_acceptance(db_session):
    """
    Simulates a supervisor assigning the ticket out (acceptance) before
    ever clicking a literal Acknowledge button. The ticket's priority
    label becomes CRITICAL immediately (escalating alone always does
    that) — but ResolutionSLA.priority itself stays at original_priority
    (MEDIUM), never CRITICAL; only its due_at/active_target_minutes
    reshift, onto handling_stage=1's target.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    reloaded_ticket = await service.ticket_repository.get_by_id(ticket.ticket_id)
    assert reloaded_ticket.current_priority == TicketPriority.CRITICAL

    policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)
    expected_target_minutes = round(
        policy.resolution_target_minutes * policy.handling_stage_percentages[0] / 100
    )

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    assert reloaded.due_at != original_due_at
    assert reloaded.active_target_minutes == expected_target_minutes

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.handling_stage == 1


async def test_escalation_owner_ids_are_not_refreshed_by_a_plain_acceptance(db_session):
    """
    Regression coverage for the root cause of "current owner not
    receiving the SLA Breached notification": TicketEscalation.
    owner_ids is only ever rewritten by an explicit ladder advance
    (TicketEscalationRepository.advance — the ack-timeout or
    handling-SLA-breach paths) — a plain accept-and-assign
    (EscalationService._complete_acceptance, reached here via
    acknowledge_via_assignment) never touches it. This is exactly why
    sla_escalation_rules.resolve_current_owner can no longer trust
    escalation_owner_ids once acceptance has completed — see that
    function's own regression tests in test_sla_escalation_rules.py
    for the fix built on top of this data-level fact.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation_before = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    owner_ids_before = set(escalation_before.owner_ids)
    assert str(team_lead.user_id) in owner_ids_before

    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    escalation_after = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    # Acceptance genuinely completed (a handling stage is now running)...
    assert escalation_after.handling_stage_due_at is not None
    # ...yet owner_ids is byte-for-byte the same as before acceptance —
    # the staleness resolve_current_owner's escalation_acceptance_
    # completed gate exists to work around.
    assert set(escalation_after.owner_ids) == owner_ids_before


async def test_resolution_sla_escalation_cycle_increments_on_each_handling_stage_restart(
    db_session,
):
    """
    Regression coverage for the root cause of "regular SLA notifications
    stop after the first escalation": restart_due_at_for_escalation must
    bump ResolutionSLA.escalation_cycle every time it resets this same
    clock row's due_at for a new handling stage — that number is what
    lets the SLABreachNotification ledger re-fire a threshold that
    already notified once in an earlier cycle (see
    test_sla_breach_notification_repository.py for the ledger side of
    this fix).
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    baseline = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert baseline.escalation_cycle == 0

    await service.acknowledge(ticket.ticket_id, team_lead)
    await service.confirm_assignment(ticket.ticket_id, team_lead)

    after_stage_1 = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert after_stage_1.escalation_cycle == 1

    # Simulate stage 1's window having elapsed with nobody resolving it
    # — same mechanics as test_confirm_assignment_advances_to_stage_2_
    # after_stage_1_elapses above.
    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    escalation.handling_stage_due_at = None
    await db_session.flush()

    await service.confirm_assignment(ticket.ticket_id, team_lead)

    after_stage_2 = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert after_stage_2.escalation_cycle == 2


async def test_advance_is_guarded_against_a_concurrent_racing_sweep(db_session):
    """
    Regression coverage for the "duplicate scheduler workers" risk this
    codebase's own CLAUDE.md documents (a local dev backend and the
    deployed Render backend can share the same database, each running
    its own scheduler). Simulates two overlapping evaluate_overdue()
    runs both having read the same escalation before either writes: the
    first advance() call wins; a second call against an in-memory
    object still showing the OLD (pre-first-advance) level — exactly
    what a second process's independent, slightly-stale read would look
    like — must lose the race and return None rather than double-
    advancing the ladder.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    stale_level = escalation.level
    now = datetime.now(timezone.utc)

    first = await service.ticket_escalation_repository.advance(
        escalation,
        new_level=EscalationLevel.MANAGER,
        owner_ids={uuid.uuid4()},
        ack_due_at=now + timedelta(minutes=30),
        now=now,
    )
    assert first is not None
    assert first.level == EscalationLevel.MANAGER

    # Simulate a second process's stale in-memory read: same escalation
    # row, but still showing the level it observed before the first
    # process's advance() committed.
    escalation.level = stale_level

    second = await service.ticket_escalation_repository.advance(
        escalation,
        new_level=EscalationLevel.SITE_LEAD,
        owner_ids={uuid.uuid4()},
        ack_due_at=now + timedelta(minutes=30),
        now=now,
    )
    assert second is None

    reloaded = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    # Still at MANAGER (the first, winning advance) — the second,
    # stale-level call must not have moved it to SITE_LEAD.
    assert reloaded.level == EscalationLevel.MANAGER


async def test_acknowledge_via_assignment_is_idempotent_while_stage_still_running(db_session):
    """
    A second acknowledge_via_assignment call (e.g. a later reassignment)
    while the current handling stage is still running (its window
    hasn't elapsed) must not advance the stage or reshift the clock
    again — guarded by handling_stage_due_at already being non-null,
    independent of has_advanced_past_starting_level entirely.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    first_reshifted_due_at = reloaded.due_at

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.handling_stage == 1
    first_stage_due_at = escalation.handling_stage_due_at

    # A second call, stage 1 still running — must not reshift the
    # clock again or advance the stage.
    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)
    reloaded_again = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded_again.due_at == first_reshifted_due_at

    escalation_again = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation_again.handling_stage == 1
    assert escalation_again.handling_stage_due_at == first_stage_due_at


async def test_acknowledge_via_assignment_still_completes_after_prior_explicit_acknowledge(
    db_session,
):
    """
    Guards acknowledge_via_assignment's own bail-out: it must not skip
    completing acceptance just because the escalation is already
    ACKNOWLEDGED (from a prior plain Acknowledge click) rather than
    still ACTIVE — by the time claim_ticket/transfer_agent calls this,
    status is already ACKNOWLEDGED from step 1, so bailing out there
    would silently leave acceptance (the handling-stage advance and
    Resolution SLA reshift) never completed at all for the single most
    common path through this feature.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)

    still_untouched = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert still_untouched.due_at == original_due_at

    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    assert reloaded.due_at != original_due_at

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.handling_stage == 1


async def _count_escalation_rows(session, ticket_id) -> int:
    result = await session.execute(
        select(TicketEscalation).where(TicketEscalation.ticket_id == ticket_id)
    )
    return len(result.scalars().all())


async def test_manual_escalate_advances_existing_escalation_one_level_not_a_second_chain(
    db_session,
):
    """
    Manual Escalation must be usable more than once during a ticket's
    lifetime: a second click while an escalation is already active
    moves that SAME escalation one level further along the chain
    (TEAM_LEAD -> MANAGER) rather than being rejected, and rather than
    creating a second, parallel TicketEscalation row.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    first = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert first.level == EscalationLevel.TEAM_LEAD
    first_escalation_id = first.escalation_id

    # Second click — must succeed (not 400), and must move the SAME
    # escalation forward one level.
    result = await service.manual_escalate(ticket.ticket_id, team_lead)
    assert result.ticket_id == ticket.ticket_id

    second = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert second is not None
    assert second.escalation_id == first_escalation_id
    assert second.level == EscalationLevel.MANAGER
    assert str(team_lead.manager_id) in second.owner_ids
    # The Team Lead who owned the first level is no longer an owner —
    # ownership moved one level up, exactly as an ack-window timeout
    # would move it.
    assert str(team_lead.user_id) not in second.owner_ids
    # A fresh acknowledgment window for the new level, not the
    # original — nobody at MANAGER has acknowledged anything yet.
    assert second.status == EscalationStatus.ACTIVE
    assert second.acknowledged_at is None

    # Exactly one escalation row for this ticket, never two.
    assert await _count_escalation_rows(db_session, ticket.ticket_id) == 1


async def test_manual_escalate_full_chain_then_terminal_level_is_rejected(db_session):
    """
    Repeated manual escalation must climb the whole TEAM_LEAD -> MANAGER
    -> SITE_LEAD chain one level per click (matching the spec's own
    three-step worked example), and once SITE_LEAD (the highest
    configured level) is reached, a further attempt must be rejected —
    the backend equivalent of the Manual Escalation button being
    disabled/hidden once there's nowhere left to escalate to.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)

    await service.manual_escalate(ticket.ticket_id, team_lead)  # -> TEAM_LEAD
    first = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    escalation_id = first.escalation_id
    assert first.level == EscalationLevel.TEAM_LEAD

    await service.manual_escalate(ticket.ticket_id, team_lead)  # -> MANAGER
    second = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert second.level == EscalationLevel.MANAGER
    assert second.escalation_id == escalation_id

    await service.manual_escalate(ticket.ticket_id, team_lead)  # -> SITE_LEAD
    third = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert third.level == EscalationLevel.SITE_LEAD
    assert third.escalation_id == escalation_id

    # SITE_LEAD is terminal — a fourth attempt must be rejected outright,
    # never silently re-notify or advance past it.
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.manual_escalate(ticket.ticket_id, team_lead)
    assert exc_info.value.status_code == 400

    unchanged = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert unchanged.level == EscalationLevel.SITE_LEAD
    assert unchanged.escalation_id == escalation_id
    assert await _count_escalation_rows(db_session, ticket.ticket_id) == 1


async def test_manual_escalate_advance_writes_escalation_advanced_audit_and_notifies(
    db_session,
):
    """
    A manual re-escalation of an already-active chain must reuse the
    exact same ESCALATION_ADVANCED audit event and owner-notification
    mechanics the ack-window-timeout auto-advance (evaluate_overdue)
    already uses — not a second ESCALATION_CREATED row, and not silence.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session, with_notifications=True)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.level == EscalationLevel.MANAGER
    new_owner_id = uuid.UUID(escalation.owner_ids[0])

    # Exactly one ESCALATION_CREATED (the first click) and one
    # ESCALATION_ADVANCED (the second) — never two CREATED rows.
    created_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == ticket.ticket_id,
            AuditLog.event_type == AuditEventType.ESCALATION_CREATED,
        )
    )
    assert len(created_result.scalars().all()) == 1

    advanced_result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == ticket.ticket_id,
            AuditLog.event_type == AuditEventType.ESCALATION_ADVANCED,
        )
    )
    advanced_rows = advanced_result.scalars().all()
    assert len(advanced_rows) == 1
    advanced_row = advanced_rows[0]
    assert advanced_row.old_values["level"] == EscalationLevel.TEAM_LEAD.value
    assert advanced_row.new_values["level"] == EscalationLevel.MANAGER.value
    assert advanced_row.new_values["triggered_by"] == TRIGGERED_BY_MANUAL
    assert advanced_row.actor_id == team_lead.user_id
    assert advanced_row.actor_name == team_lead.name

    notification_result = await db_session.execute(
        select(Notification).where(
            Notification.user_id == new_owner_id,
            Notification.related_entity_id == ticket.ticket_id,
        )
    )
    notification_rows = notification_result.scalars().all()
    assert len(notification_rows) >= 1
    assert any(
        ticket.title in n.message or ticket.title in n.title for n in notification_rows
    )

    # Still exactly one escalation row — the second manual_escalate
    # advanced the existing chain, it never spawned a second one.
    assert await _count_escalation_rows(db_session, ticket.ticket_id) == 1


async def test_manual_escalate_after_acceptance_advances_and_resets_handling_stage(
    db_session,
):
    """
    Example 2 from the spec: the current owner (Team Lead) accepts the
    ticket, THEN decides to manually escalate further. Must still
    reuse the same advance mechanics — including clearing out the
    now-stale escalation-handling-SLA window that acceptance started,
    so the sweep never later evaluates a "breach" against a handling
    window this advance has already superseded — while the Resolution
    SLA clock itself, and the handling_stage counter, stay untouched
    (only handling_stage_due_at is cleared; the next acceptance at the
    new level is what bumps handling_stage again).
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    # Team Lead accepts by claiming/being assigned the ticket —
    # acknowledge_via_assignment is the same path claim_ticket/
    # transfer_agent already call.
    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    accepted = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert accepted.handling_stage == 1
    assert accepted.handling_stage_due_at is not None
    reshifted_due_at = (
        await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    ).due_at

    # Team Lead now manually escalates further, per Example 2.
    await service.manual_escalate(ticket.ticket_id, team_lead)

    advanced = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert advanced.escalation_id == accepted.escalation_id
    assert advanced.level == EscalationLevel.MANAGER
    assert advanced.status == EscalationStatus.ACTIVE
    assert advanced.acknowledged_at is None
    # The now-superseded handling window is cleared...
    assert advanced.handling_stage_due_at is None
    # ...but the stage counter itself is left alone — the next real
    # acceptance (at MANAGER) is what advances it to 2.
    assert advanced.handling_stage == 1

    # The Resolution SLA clock (reshifted onto the CRITICAL/handling
    # target when Team Lead accepted) is untouched by this further
    # escalation — advancing the escalation ladder never reshifts it;
    # only a fresh acceptance at the new level does.
    still_reshifted = await _reload_resolution_sla(
        db_session, resolution_sla.resolution_sla_id
    )
    assert still_reshifted.due_at == reshifted_due_at


async def test_manual_escalate_advance_requires_ticket_escalate_permission(db_session):
    """
    The permission gate applies to a re-escalation of an already-active
    chain exactly as it does to the first escalation — a caller without
    ticket:escalate can't advance someone else's active escalation
    either.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    stranger = User(
        user_id=uuid.uuid4(),
        role=(await _get_team_lead(db_session)).role,
        name="No Permission User",
    )
    stranger.permissions = []  # no ticket:escalate

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.manual_escalate(ticket.ticket_id, stranger)
    assert exc_info.value.status_code == 403

    # No advance happened — still parked at the original level.
    unchanged = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert unchanged.level == EscalationLevel.TEAM_LEAD


async def test_evaluate_overdue_ack_timeout_advance_still_works_after_refactor(db_session):
    """
    Regression guard for the _advance_escalation_level extraction:
    evaluate_overdue's own ack-window-timeout auto-advance (unrelated
    to manual escalation, but now sharing the same underlying advance
    helper) must keep behaving exactly as before — advancing an
    overdue ACTIVE escalation one level and re-notifying, without any
    manual trigger involved at all.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    # Force it overdue.
    escalation.ack_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    # Deliberately not asserting evaluate_overdue's returned count here —
    # list_overdue_active scans the ENTIRE ticket_escalations table, not
    # just rows created in this test's own rolled-back transaction, so
    # against the shared dev database this count is unreliable (see
    # test_evaluate_overdue_advance_uses_original_priority_for_new_ack_window's
    # identical comment). This test only cares that THIS ticket's own
    # escalation was advanced correctly.
    await service.evaluate_overdue(now=datetime.now(timezone.utc))

    reloaded = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert reloaded.level == EscalationLevel.MANAGER
    assert reloaded.escalation_id == escalation.escalation_id

    advanced_audit = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == ticket.ticket_id,
            AuditLog.event_type == AuditEventType.ESCALATION_ADVANCED,
        )
    )
    audit_row = advanced_audit.scalars().first()
    assert audit_row is not None
    assert audit_row.actor_name == "SLA Sweep"
    # Distinguishable from a manual advance — no triggered_by:MANUAL tag.
    assert "triggered_by" not in audit_row.new_values


async def test_acknowledge_by_owner_stops_auto_advance(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
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

    # Acknowledging alone deliberately does NOT reshift the clock (see
    # test_acknowledge_alone_does_not_reshift_sla for that invariant in
    # isolation) — this test is only about the auto-advance side
    # effect, so it doesn't assert anything about due_at itself.


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
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    # Never acknowledged in this test, so the SLA-reshift exception
    # never fires (priority already bumped to CRITICAL from escalating
    # alone, but that's a separate concern from the clock's own due_at)
    # — due_at should be untouched throughout.
    original_due_at = (
        await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    ).due_at

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

    # Ladder movement alone must never touch handling progression — the
    # exact distinction this whole redesign exists to enforce.
    assert advanced.handling_stage == 0
    assert advanced.handling_stage_due_at is None


async def test_ack_timeout_ladder_advance_then_first_accept_starts_at_stage_1_not_2(db_session):
    """
    The core regression test for this session's fix. Team Lead never
    acknowledges; the ack window lapses and the ladder auto-advances to
    MANAGER (evaluate_overdue) — nobody has done any real handling work
    yet. The Manager's SUBSEQUENT first acceptance must still be
    handling_stage=1 (25% of the ORIGINAL priority's target), not stage
    2 and not CRITICAL's target — before this fix,
    has_advanced_past_starting_level (which evaluate_overdue always
    sets True on any ladder advance, regardless of cause) was
    incorrectly used as a proxy for "a real handling cycle already
    happened," which this scenario disproves: the ladder moved, but
    handling never started.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.level == EscalationLevel.TEAM_LEAD

    # Simulate the ack window lapsing with nobody having acknowledged —
    # same mechanism test_overdue_active_escalation_advances_without_
    # touching_sla already exercises in isolation.
    escalation.ack_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    advanced_count = await service.evaluate_overdue(now=datetime.now(timezone.utc))
    assert advanced_count == 1

    ladder_advanced = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert ladder_advanced.status == EscalationStatus.ACTIVE
    assert ladder_advanced.level != EscalationLevel.TEAM_LEAD
    assert ladder_advanced.has_advanced_past_starting_level is True
    # The would-be-buggy proxy is True, but handling progression itself
    # must be completely untouched by this ladder movement alone.
    assert ladder_advanced.handling_stage == 0
    assert ladder_advanced.handling_stage_due_at is None

    # Whoever the ladder now points at (MANAGER — the Team Lead's own
    # manager, resolved by _resolve_owners_for_level) accepts for the
    # very first time.
    new_owner_id = uuid.UUID(ladder_advanced.owner_ids[0])
    new_owner = (
        await db_session.execute(
            select(User)
            .options(joinedload(User.role), joinedload(User.category))
            .where(User.user_id == new_owner_id)
        )
    ).unique().scalar_one()

    await service.acknowledge(ticket.ticket_id, new_owner)
    await service.confirm_assignment(ticket.ticket_id, new_owner)

    policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)
    expected_target_minutes = round(
        # stage 1's percentage, NOT stage 2's — this is the exact bug
        # fix: the ladder having already advanced once must not skip
        # straight to stage 2's smaller percentage.
        policy.resolution_target_minutes * policy.handling_stage_percentages[0] / 100
    )

    final_escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert final_escalation.handling_stage == 1

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    assert reloaded.active_target_minutes == expected_target_minutes


async def test_advance_for_handling_sla_breach_clears_due_at_without_bumping_stage(db_session):
    """
    advance_for_handling_sla_breach only clears handling_stage_due_at
    (so list_handling_stage_overdue's idempotency guard doesn't fire
    again for the same breach) and moves the ownership ladder — it does
    NOT itself increment handling_stage. The stage counter only
    advances on the NEXT successful _complete_acceptance, mirroring
    handling_stage=1 -> 2's own mechanics tested above.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)
    await service.confirm_assignment(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.handling_stage == 1
    assert escalation.handling_stage_due_at is not None
    old_level_started_at = escalation.level_started_at

    advanced = await service.advance_for_handling_sla_breach(ticket.ticket_id)
    assert advanced is True

    reloaded = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert reloaded.status == EscalationStatus.ACTIVE
    # Ticket is still unclaimed (agent_id never set in this scenario),
    # so _resolve_starting_level correctly lands back on TEAM_LEAD
    # again rather than skipping a level — but it's still a genuine
    # fresh ownership cycle (level_started_at/ack_due_at reset), not a
    # no-op.
    assert reloaded.level == EscalationLevel.TEAM_LEAD
    assert reloaded.level_started_at != old_level_started_at
    assert reloaded.handling_stage_due_at is None
    # Stage itself is untouched by this call — only the next
    # _complete_acceptance bumps it to 2.
    assert reloaded.handling_stage == 1
    assert reloaded.has_advanced_past_starting_level is True


async def test_close_for_ticket_resolution_closes_escalation_only(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    # Never acknowledged in this test, so the SLA-reshift exception
    # never fires (priority already bumped to CRITICAL from escalating
    # alone, but that's a separate concern from the clock's own due_at)
    # — due_at should be untouched throughout.
    original_due_at = (
        await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    ).due_at

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


# =========================================================
# Regression coverage for two fixes:
#
# 1. The escalation ack window (ack_due_at) must be resolved from the
#    ticket's ORIGINAL priority, never Ticket.current_priority — by
#    the time _create_escalation/evaluate_overdue/
#    advance_for_handling_sla_breach compute it, current_priority is
#    already (and permanently) CRITICAL, so using it there silently
#    applied CRITICAL's own ack target (a fixed, unrelated tier)
#    instead of the ticket's real priority's. CRITICAL is not an
#    independently configurable SLA tier at all (see
#    sla_service.update_policy's matching guard) — nothing should ever
#    read its policy row for a real calculation.
# 2. get_acknowledge_candidates' role-scoped candidate groups: Site
#    Lead/Super Admin were missing a Staff group and resolved Account
#    Manager via the ticket's own client owner (a single person)
#    rather than the ticket's category's actual Reporting Manager(s)
#    (ReportingManagerTeam); Account Manager was missing a Staff group
#    entirely and incorrectly narrowed Team Leads to their own direct
#    reports instead of the ticket's whole category.
# =========================================================


async def test_create_escalation_ack_window_uses_original_priority_not_critical(db_session):
    """
    A MEDIUM-priority ticket's ack window must be MEDIUM's
    escalation_ack_target_minutes — never CRITICAL's — even though
    Ticket.current_priority is already CRITICAL by the time ack_due_at
    is computed (_set_ticket_priority_to_critical runs first in
    _create_escalation).
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    medium_policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)
    critical_policy = await SLAPolicyRepository(db_session).get_by_priority(
        TicketPriority.CRITICAL
    )
    # A real, meaningful regression test requires these two targets to
    # actually differ in the seeded data — if they were ever seeded
    # equal, this test would pass even with the bug still present.
    assert medium_policy.escalation_ack_target_minutes != critical_policy.escalation_ack_target_minutes

    service = _build_service(db_session)
    result = await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    reloaded_ticket = await service.ticket_repository.get_by_id(ticket.ticket_id)
    assert reloaded_ticket.current_priority == TicketPriority.CRITICAL

    assert escalation.original_priority == TicketPriority.MEDIUM
    actual_ack_minutes = round(
        (escalation.ack_due_at - result.created_at).total_seconds() / 60
    )
    assert actual_ack_minutes == medium_policy.escalation_ack_target_minutes
    assert actual_ack_minutes != critical_policy.escalation_ack_target_minutes


async def test_evaluate_overdue_advance_uses_original_priority_for_new_ack_window(db_session):
    """
    Same fix, exercised through the ack-window-lapse ladder advance
    (evaluate_overdue) rather than creation — the new ack_due_at it
    computes for the next level must also be resolved from
    escalation.original_priority, not ticket.current_priority.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    medium_policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    escalation.ack_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    # Deliberately not asserting evaluate_overdue's returned count here —
    # list_overdue_active scans the ENTIRE ticket_escalations table, not
    # just rows created in this test's own rolled-back transaction, so
    # against the shared dev database this count is unreliable (see
    # test_overdue_active_escalation_advances_without_touching_sla's own
    # docstring/comment for the same pre-existing, documented fragility).
    # This test only cares that THIS ticket's own escalation was
    # advanced with the correct ack window.
    await service.evaluate_overdue(now=now)

    advanced = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert advanced.level != EscalationLevel.TEAM_LEAD
    actual_ack_minutes = round((advanced.ack_due_at - now).total_seconds() / 60)
    assert actual_ack_minutes == medium_policy.escalation_ack_target_minutes


async def test_advance_for_handling_sla_breach_uses_original_priority_for_new_ack_window(
    db_session,
):
    """
    Same fix again, through the handling-SLA-breach advance path.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    medium_policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)
    await service.confirm_assignment(ticket.ticket_id, team_lead)

    before = await service.ticket_escalation_repository.get_active_by_ticket_id(ticket.ticket_id)
    assert before.handling_stage == 1

    result = await service.advance_for_handling_sla_breach(ticket.ticket_id)
    assert result is True

    after = await service.ticket_escalation_repository.get_active_by_ticket_id(ticket.ticket_id)
    actual_ack_minutes = round(
        (after.ack_due_at - after.level_started_at).total_seconds() / 60
    )
    assert actual_ack_minutes == medium_policy.escalation_ack_target_minutes


async def test_acknowledge_candidates_team_lead_sees_only_own_category_staff(db_session):
    """
    Unchanged behavior — Team Lead's candidate list is exactly their
    own category's Staff, nothing else.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    staff_in_category = await _get_staff_in_category(db_session, TEAM_LEAD_CATEGORY)
    if not staff_in_category:
        pytest.skip(f"No active seeded Staff found for category {TEAM_LEAD_CATEGORY!r}.")

    service = _build_service(db_session)
    response = await service.get_acknowledge_candidates(ticket.ticket_id, team_lead)

    assert response.me.user_id == team_lead.user_id
    assert [g.role for g in response.groups] == ["Staff"]
    returned_ids = {u.user_id for u in response.groups[0].users}
    assert returned_ids == {u.user_id for u in staff_in_category}


async def test_acknowledge_candidates_account_manager_sees_category_team_leads_and_staff(
    db_session,
):
    """
    Regression test for the fix: Account Manager's candidate list must
    be the ticket's whole category's Team Leads (not narrowed to their
    own direct reports via manager_id) plus that category's Staff
    (previously missing entirely).
    """

    account_manager = await _get_account_manager(db_session)
    _team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    staff_in_category = await _get_staff_in_category(db_session, TEAM_LEAD_CATEGORY)
    if not staff_in_category:
        pytest.skip(f"No active seeded Staff found for category {TEAM_LEAD_CATEGORY!r}.")

    service = _build_service(db_session)
    response = await service.get_acknowledge_candidates(ticket.ticket_id, account_manager)

    assert response.me.user_id == account_manager.user_id
    roles_returned = [g.role for g in response.groups]
    assert "Site Lead" not in roles_returned
    assert "Account Manager" not in roles_returned
    assert set(roles_returned) == {"Team Lead", "Staff"}

    team_lead_group = next(g for g in response.groups if g.role == "Team Lead")
    all_category_team_leads = await UserRepository(db_session).list_active_by_role_and_category(
        "Team Lead", TEAM_LEAD_CATEGORY
    )
    assert {u.user_id for u in team_lead_group.users} == {u.user_id for u in all_category_team_leads}

    staff_group = next(g for g in response.groups if g.role == "Staff")
    assert {u.user_id for u in staff_group.users} == {u.user_id for u in staff_in_category}


async def test_acknowledge_candidates_site_lead_sees_reporting_manager_am_team_leads_and_staff(
    db_session,
):
    """
    Regression test for the fix: Site Lead's candidate list must
    include every Account Manager who is the Reporting Manager for the
    ticket's category (ReportingManagerTeam), not just the ticket's
    client's own account_manager_id — plus that category's Team
    Lead(s) and Staff (Staff was previously missing entirely).
    """

    site_lead = await _get_site_lead(db_session)
    account_manager = await _get_account_manager(db_session)
    _team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    staff_in_category = await _get_staff_in_category(db_session, TEAM_LEAD_CATEGORY)
    if not staff_in_category:
        pytest.skip(f"No active seeded Staff found for category {TEAM_LEAD_CATEGORY!r}.")

    category_result = await db_session.execute(
        select(Category).where(Category.category_name == TEAM_LEAD_CATEGORY)
    )
    category = category_result.scalar_one()

    # Idempotent — the dev database may already have a real, seeded
    # Reporting Manager mapping for this exact (account_manager,
    # category) pair (this is genuine seed/admin data, not test
    # pollution — see ReportingManagerRepository's own docstring), so
    # this only inserts one if it isn't already there, same convention
    # as ReportingManagerService.assign's own pre-check.
    reporting_manager_repository = ReportingManagerRepository(db_session)
    if not await reporting_manager_repository.exists(
        account_manager.user_id, category.category_id
    ):
        db_session.add(
            ReportingManagerTeam(
                account_manager_id=account_manager.user_id,
                category_id=category.category_id,
            )
        )
        await db_session.flush()

    service = _build_service(db_session)
    response = await service.get_acknowledge_candidates(ticket.ticket_id, site_lead)

    assert response.me.user_id == site_lead.user_id
    roles_returned = {g.role for g in response.groups}
    assert roles_returned == {"Account Manager", "Team Lead", "Staff"}

    # Ground-truth comparison, not a hardcoded {account_manager} set —
    # the dev database may already map more than one Account Manager as
    # Reporting Manager for this category (the model deliberately
    # allows this, see its own docstring), and our ensured mapping only
    # guarantees account_manager is *among* them, not the only one.
    # Filtered to active users, matching _resolve_category_account_
    # managers' own filter — a mapped-but-deactivated AM must not
    # appear.
    am_group = next(g for g in response.groups if g.role == "Account Manager")
    mapped_am_ids = await reporting_manager_repository.list_account_manager_ids_by_category(
        category.category_id
    )
    mapped_ams = await UserRepository(db_session).list_by_ids(mapped_am_ids)
    expected_am_ids = {u.user_id for u in mapped_ams if u.is_active}
    assert account_manager.user_id in expected_am_ids
    assert {u.user_id for u in am_group.users} == expected_am_ids

    staff_group = next(g for g in response.groups if g.role == "Staff")
    assert {u.user_id for u in staff_group.users} == {u.user_id for u in staff_in_category}


async def test_acknowledge_candidates_site_lead_am_group_matches_reporting_manager_ground_truth(
    db_session,
):
    """
    The Account Manager group Site Lead sees must exactly match
    ReportingManagerTeam's own data for the ticket's category — whether
    that's empty (group absent entirely, not an error or a fallback to
    some unrelated AM) or already populated by real, pre-existing
    seed/admin data. This intentionally makes no assumption about
    whether the dev database already has a mapping for this category —
    see the sibling test above for the "ensure at least one mapping
    exists" case.
    """

    site_lead = await _get_site_lead(db_session)
    _team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)

    category_result = await db_session.execute(
        select(Category).where(Category.category_name == TEAM_LEAD_CATEGORY)
    )
    category = category_result.scalar_one()
    mapped_am_ids = await ReportingManagerRepository(db_session).list_account_manager_ids_by_category(
        category.category_id
    )
    mapped_ams = await UserRepository(db_session).list_by_ids(mapped_am_ids)
    expected_am_ids = {u.user_id for u in mapped_ams if u.is_active}

    service = _build_service(db_session)
    response = await service.get_acknowledge_candidates(ticket.ticket_id, site_lead)

    roles_returned = {g.role for g in response.groups}
    if expected_am_ids:
        assert "Account Manager" in roles_returned
        am_group = next(g for g in response.groups if g.role == "Account Manager")
        assert {u.user_id for u in am_group.users} == expected_am_ids
    else:
        assert "Account Manager" not in roles_returned


# =========================================================
# Manual Escalate button / workflow — new coverage.
#
# manual_escalate() itself already existed, fully wired (permission
# check, _create_escalation reuse, audit log, notifications) and
# already reachable via POST /tickets/{id}/escalate — these tests fill
# in gaps the rest of this file's manual_escalate-driven tests above
# don't already cover explicitly: escalating before any SLA breach,
# the actual audit-log row and notification row it writes, and its own
# permission gate rejecting an unauthorized caller. No new service
# code was needed for any of this — see the frontend's SlaCard.tsx for
# the only change this feature required (a confirmation dialog in
# front of the same, already-existing Escalate button/API call).
# =========================================================


async def _make_unbreached_scenario(session):
    """
    Same shape as _make_scenario, but the Resolution SLA clock is
    freshly started and far from its target — manual_escalate has no
    elapsed-fraction precondition at all (only "not already escalated"
    and "not closed"), so this proves escalating doesn't require a
    breach, at-risk state, or any SLA threshold to have been crossed.
    """

    team_lead = await _get_team_lead(session)

    client = Client(
        client_id=uuid.uuid4(),
        name="Escalation Test Client (unbreached)",
        inbox_email=f"escalation-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        is_active=True,
    )
    session.add(client)

    started_at = datetime.now(timezone.utc)
    due_at = started_at + timedelta(days=7)  # nowhere near elapsed

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=None,
        title="Escalation regression test ticket (unbreached)",
        ticket_type=TEAM_LEAD_CATEGORY,
        current_status="OPEN",
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
        due_at=due_at,
        active_target_minutes=medium_policy.resolution_target_minutes,
    )
    session.add(resolution_sla)
    await session.flush()

    return team_lead, client, ticket, resolution_sla


async def test_manual_escalate_works_before_sla_breach(db_session):
    """
    manual_escalate has no SLA-state precondition — a ticket nowhere
    near its Resolution SLA target can still be escalated on demand,
    exactly like an already-breached one.
    """

    team_lead, _client, ticket, resolution_sla = await _make_unbreached_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    assert resolution_sla.due_at > datetime.now(timezone.utc) + timedelta(days=1)

    service = _build_service(db_session)
    result = await service.manual_escalate(ticket.ticket_id, team_lead)
    assert result.ticket_id == ticket.ticket_id

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    assert escalation.status == EscalationStatus.ACTIVE
    assert escalation.triggered_by == TRIGGERED_BY_MANUAL

    # The clock itself is completely untouched by escalating, same as
    # every other manual_escalate test in this file — still true when
    # nowhere near its target.
    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.due_at == resolution_sla.due_at
    assert reloaded.status == SLAClockStatus.RUNNING


async def test_manual_escalate_writes_audit_log_and_notifies_new_owner(db_session):
    """
    manual_escalate must write a real ESCALATION_CREATED audit row
    (triggered_by=MANUAL, distinguishable from an automatic one) and
    send a real in-app notification to the resolved owner — the same
    two side effects auto_escalate_if_needed produces, via the exact
    same _create_escalation/_notify_owners calls.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session, with_notifications=True)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    new_owner_id = uuid.UUID(escalation.owner_ids[0])

    audit_result = await db_session.execute(
        select(AuditLog)
        .where(
            AuditLog.entity_id == ticket.ticket_id,
            AuditLog.event_type == AuditEventType.ESCALATION_CREATED,
        )
        .order_by(AuditLog.created_at.desc())
    )
    audit_row = audit_result.scalars().first()
    assert audit_row is not None
    assert audit_row.new_values["triggered_by"] == TRIGGERED_BY_MANUAL
    assert audit_row.new_values["level"] == escalation.level.value
    assert audit_row.actor_id == team_lead.user_id

    notification_result = await db_session.execute(
        select(Notification).where(
            Notification.user_id == new_owner_id,
            Notification.related_entity_id == ticket.ticket_id,
        )
    )
    notification_row = notification_result.scalars().first()
    assert notification_row is not None
    assert ticket.title in notification_row.message or ticket.title in notification_row.title


async def test_manual_escalate_requires_ticket_escalate_permission(db_session):
    """
    manual_escalate's own permission gate (ensure_has_permission(...,
    "ticket:escalate")) must reject a caller who doesn't hold it —
    the same RBAC permission the frontend's canEscalate check (and the
    Manual Escalate button's visibility) already reuses, no new
    permission introduced.
    """

    _team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)

    stranger = User(
        user_id=uuid.uuid4(),
        role=(await _get_team_lead(db_session)).role,
        name="No Permission User",
    )
    stranger.permissions = []  # no ticket:escalate

    service = _build_service(db_session)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.manual_escalate(ticket.ticket_id, stranger)
    assert exc_info.value.status_code == 403

    # Confirm no escalation was created despite the attempt.
    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is None


# ---------------------------------------------------------------------
# Manual escalation's own escalation-handling-SLA timer behavior — added
# to close the loop explicitly, even though it already follows from
# test_manual_escalate_bumps_priority_but_leaves_sla_untouched +
# test_acknowledge_alone_does_not_reshift_sla +
# test_confirm_assignment_reshifts_sla_to_stage_1_on_first_acceptance
# above. A reported "bug" claimed the handling-SLA timer keeps running
# after Manual Escalate, before the new owner acknowledges. Live testing
# against the running backend (manual_escalate -> inspect
# TicketEscalation.handling_stage/_started_at/_due_at -> confirm_assignment
# -> re-inspect) confirmed the premise is false: _create_escalation (the
# helper manual_escalate and auto_escalate_if_needed both call) never
# passes handling-stage fields to TicketEscalationRepository.create, so a
# freshly created escalation always starts at handling_stage=0 with both
# timestamps NULL — no timer running — regardless of trigger. The timer
# only ever starts inside _complete_acceptance, reached from
# acknowledge_via_assignment/confirm_assignment, i.e. only once a
# supervisor has actually accepted the ticket. These tests make that
# explicit for the manual-escalation path specifically, and confirm parity
# with the automatic path.
# ---------------------------------------------------------------------


async def test_manual_escalate_does_not_start_handling_sla_timer(db_session):
    """
    Immediately after manual_escalate, no handling-SLA timer is running
    and ticket ownership (agent_id) has not moved — only the escalation's
    own owner_ids (who is responsible for acknowledging) reflects the new
    level. The ticket sits "awaiting acknowledgement" until a supervisor
    actually accepts it.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    original_agent_id = ticket.agent_id
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    assert escalation.status == EscalationStatus.ACTIVE
    assert escalation.handling_stage == 0
    assert escalation.handling_stage_started_at is None
    assert escalation.handling_stage_due_at is None

    reloaded_ticket = await service.ticket_repository.get_by_id(ticket.ticket_id)
    assert reloaded_ticket.agent_id == original_agent_id


async def test_manual_escalate_then_accept_starts_handling_sla_at_full_duration(db_session):
    """
    Once the new owner acknowledges and the assignment is settled
    (confirm_assignment), the handling-SLA timer starts fresh — from the
    call's own timestamp, for the FULL configured stage-1 duration —
    never a partial or carried-over remainder from any prior state.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)

    still_pending = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert still_pending.handling_stage == 0
    assert still_pending.handling_stage_due_at is None

    before_accept = datetime.now(timezone.utc)
    await service.confirm_assignment(ticket.ticket_id, team_lead)
    after_accept = datetime.now(timezone.utc)

    policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)
    expected_target_minutes = round(
        policy.resolution_target_minutes * policy.handling_stage_percentages[0] / 100
    )

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.handling_stage == 1
    assert before_accept <= escalation.handling_stage_started_at <= after_accept
    actual_minutes = (
        escalation.handling_stage_due_at - escalation.handling_stage_started_at
    ).total_seconds() / 60
    assert round(actual_minutes) == expected_target_minutes


async def test_auto_escalate_also_does_not_start_handling_sla_timer_immediately(db_session):
    """
    Regression parity check: the automatic escalation trigger
    (auto_escalate_if_needed, called from the SLA sweep) shares the exact
    same _create_escalation helper as manual_escalate, so it must exhibit
    the identical "no handling timer until acceptance" behavior — this
    guards against the two triggers ever silently diverging.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)

    service = _build_service(db_session)
    created = await service.auto_escalate_if_needed(
        ticket=ticket, resolution_clock=resolution_sla
    )
    assert created is True

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    assert escalation.triggered_by != TRIGGERED_BY_MANUAL
    assert escalation.handling_stage == 0
    assert escalation.handling_stage_started_at is None
    assert escalation.handling_stage_due_at is None
