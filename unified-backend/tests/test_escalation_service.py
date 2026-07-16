# test_escalation_service.py
#
# Regression coverage for the internal escalation workflow
# (TicketEscalation / EscalationService). Three deliberate exceptions
# to "escalating must never restart/recalculate the Resolution SLA
# clock," split into three separate moments on purpose:
#
# 1. The ticket's priority permanently becomes CRITICAL the instant it
#    escalates — manual_escalate/auto_escalate_if_needed, via
#    EscalationService._set_ticket_priority_to_critical. Plain
#    Ticket.current_priority write; the Resolution SLA clock itself is
#    NOT touched here — test_manual_escalate_bumps_priority_but_leaves_
#    sla_untouched below is the test that guards this split.
# 2. Acknowledging alone (acknowledge()) only stops the ack-window
#    auto-advance — it does NOT reshift the Resolution SLA clock and
#    does NOT start the escalation-handling SLA. See
#    test_acknowledge_alone_does_not_reshift_sla below.
# 3. The Resolution SLA clock's own due_at/priority only reshift once a
#    supervisor has ALSO settled who the ticket is assigned to —
#    acknowledge_via_assignment() (claim_ticket/transfer_agent) or
#    confirm_assignment() (the "keep the current assignee" case) —
#    via EscalationService._complete_acceptance /
#    _reshift_sla_for_escalation_acceptance. This is the "the
#    Resolution SLA should NOT start immediately when escalated — only
#    after acknowledgment AND assignment" requirement. Further gated on
#    escalation.has_advanced_past_starting_level: acceptance of a
#    still-first-time escalation leaves the clock running against its
#    original_priority target rather than reshifting straight to
#    CRITICAL's — only once nobody acted in time and it genuinely
#    advanced to a further level does acceptance reshift onto CRITICAL.
#    See test_confirm_assignment_does_not_reshift_sla_on_first_acceptance
#    / test_confirm_assignment_reshifts_sla_after_escalation_has_advanced.
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


async def test_confirm_assignment_does_not_reshift_sla_on_first_acceptance(db_session):
    """
    The "keep the current assignee" branch: Acknowledge (step 1) is
    clicked first — leaving the clock untouched (see the test above) —
    and confirm_assignment (step 2's no-reassignment branch) completes
    acceptance. On a still-first-time escalation (never advanced past
    its starting level), this must NOT reshift the Resolution SLA onto
    CRITICAL's target — it keeps running against its original
    priority's target until the escalation has actually advanced (see
    test_confirm_assignment_reshifts_sla_after_escalation_has_advanced
    below). Reshifting immediately here used to jump straight to
    CRITICAL's 60-minute target even though the clock had already run
    for hours under MEDIUM's, landing due_at in the past.
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

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    assert reloaded.due_at == original_due_at


async def test_confirm_assignment_reshifts_sla_after_escalation_has_advanced(db_session):
    """
    Once the escalation has gone unhandled and advanced past its
    starting level — a genuine "second time" escalation — acceptance
    DOES reshift the Resolution SLA clock onto CRITICAL's target, same
    as it always did before this fix, just deferred until this later
    point instead of firing on the very first acceptance. Sets
    has_advanced_past_starting_level directly, same convention as
    test_overdue_active_escalation_advances_without_touching_sla's own
    direct manipulation of ack_due_at, rather than driving a full
    ack-window-lapse cycle through evaluate_overdue.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    escalation.has_advanced_past_starting_level = True
    await db_session.flush()

    await service.acknowledge(ticket.ticket_id, team_lead)
    result = await service.confirm_assignment(ticket.ticket_id, team_lead)
    assert result.ticket_id == ticket.ticket_id

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.CRITICAL
    assert reloaded.due_at != original_due_at


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


async def test_acknowledge_via_assignment_does_not_reshift_on_first_acceptance(db_session):
    """
    Simulates a supervisor assigning the ticket out (acceptance) before
    ever clicking a literal Acknowledge button. The ticket's priority
    label still becomes CRITICAL immediately (escalating alone always
    does that), but on a still-first-time escalation the Resolution SLA
    clock itself must NOT reshift yet — see
    test_acknowledge_via_assignment_reshifts_once_escalation_has_advanced
    below for when it does.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    reloaded_ticket = await service.ticket_repository.get_by_id(ticket.ticket_id)
    assert reloaded_ticket.current_priority == TicketPriority.CRITICAL

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.MEDIUM
    assert reloaded.due_at == original_due_at


async def test_acknowledge_via_assignment_reshifts_once_escalation_has_advanced(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    escalation.has_advanced_past_starting_level = True
    await db_session.flush()

    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.CRITICAL
    assert reloaded.due_at != original_due_at
    first_reshifted_due_at = reloaded.due_at

    # A second acknowledge_via_assignment call (e.g. a later
    # reassignment) must not reshift the clock again — idempotent once
    # the clock is already on CRITICAL.
    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)
    reloaded_again = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded_again.due_at == first_reshifted_due_at


async def test_acknowledge_via_assignment_still_completes_after_prior_explicit_acknowledge(
    db_session,
):
    """
    Guards the fix to acknowledge_via_assignment's own bail-out: it used
    to skip everything unless the escalation was still ACTIVE, which
    broke the ordinary two-step flow (Acknowledge, then Assign) — by
    the time claim_ticket/transfer_agent calls this, status is already
    ACKNOWLEDGED from step 1, so bailing out there would silently leave
    acceptance (the reshift once the escalation has advanced, and the
    escalation-handling SLA's start) never completed at all for the
    single most common path through this feature.

    has_advanced_past_starting_level is forced True first so the
    reshift itself has something to prove: on a still-first-time
    escalation this method now correctly no-ops the reshift regardless
    of whether it bails out early or not, which would make a bail-out
    regression invisible here otherwise.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(db_session)
    original_due_at = resolution_sla.due_at
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)
    await service.acknowledge(ticket.ticket_id, team_lead)

    still_untouched = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert still_untouched.due_at == original_due_at

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    escalation.has_advanced_past_starting_level = True
    await db_session.flush()

    await service.acknowledge_via_assignment(ticket.ticket_id, team_lead)

    reloaded = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reloaded.priority == TicketPriority.CRITICAL
    assert reloaded.due_at != original_due_at


async def test_escalating_twice_is_rejected_not_a_second_chain(db_session):
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    team_lead.permissions = ["ticket:escalate"]

    service = _build_service(db_session)
    await service.manual_escalate(ticket.ticket_id, team_lead)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await service.manual_escalate(ticket.ticket_id, team_lead)
    assert exc_info.value.status_code == 400


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
