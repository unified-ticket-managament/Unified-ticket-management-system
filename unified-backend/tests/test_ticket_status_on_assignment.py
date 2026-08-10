# test_ticket_status_on_assignment.py
#
# Regression coverage for "OPEN -> IN_PROGRESS on claim/assign/transfer"
# (UTMS ticketing/mail bug-fix pass). Two distinct code paths write
# Ticket.agent_id:
#
#   - InteractionService.claim_ticket -> TicketRepository.claim, whose
#     atomic, WHERE-gated UPDATE already moved OPEN -> IN_PROGRESS
#     before this pass (nothing to fix there — this file adds the
#     regression test that didn't previously exist for it).
#   - InteractionService.transfer_agent (used for both "Assign" of an
#     unclaimed ticket to a specific agent, and "Reassign"/"Transfer"
#     of an already-claimed ticket to someone else) — this one had NO
#     status side effect at all before this pass, a real gap fixed by
#     folding an OPEN -> IN_PROGRESS bump into the same TicketUpdate
#     call transfer_agent already makes, scoped to exactly OPEN so it
#     never fights WAITING_FOR_CLIENT/RESOLVED/CLOSED, and recorded on
#     the existing AGENT_TRANSFERRED audit event rather than a second
#     STATUS_CHANGED row.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_transfer_agent_ownership.py / test_resolution_sla_resolved_transition.py.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import (
    AuditEventType,
    InteractionDirection,
    InteractionStatus,
    SLAClockStatus,
    TicketPriority,
    TicketStatus,
)
from app.ticketing.models.audit_log import AuditLog
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket import TicketUpdate
from app.ticketing.schemas.ticket_action import TransferAgentRequest
from app.ticketing.schemas.ticket_from_interaction import TicketFromInteractionCreate
from app.ticketing.services.assignment_service import AssignmentService
from app.ticketing.services.inbox_ticket_service import InboxTicketService
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.sla_service import build_sla_service
from app.ticketing.services.ticket_service import TicketService

# Deliberately not hardcoded to one fixed category name (e.g.
# "Eligibility") — this suite runs against the real, shared dev Neon
# database (see root CLAUDE.md's "shared dev database" caveats), whose
# category/seed data has drifted since these role/category pairings
# were first seeded. test_transfer_agent_ownership.py's own
# TEAM_LEAD_CATEGORY = "Eligibility" constant no longer matches any
# currently-seeded Team Lead in this database (confirmed: every
# currently-active Team Lead's own category is now one of
# AR/Payment Posting/Referral/Coding/None), which silently skips every
# test in that file today. This suite instead discovers, at run time,
# any category with at least one active Team Lead and enough active
# Staff to run the scenario — robust to whatever the shared database's
# category data looks like on a given day.


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _find_team_lead_with_staff(session, staff_count: int) -> tuple[User, list[User]]:
    team_lead_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    team_leads = [
        user
        for user in team_lead_result.unique().scalars().all()
        if user.category is not None
    ]

    staff_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    staff_by_category: dict[str, list[User]] = {}
    for user in staff_result.unique().scalars().all():
        if user.category is None:
            continue
        staff_by_category.setdefault(user.category.category_name.value, []).append(user)

    for team_lead in team_leads:
        candidates = staff_by_category.get(team_lead.category.category_name.value, [])
        if len(candidates) >= staff_count:
            return team_lead, candidates[:staff_count]

    pytest.skip(
        f"No category currently has both an active Team Lead and {staff_count} "
        "active Staff in the connected database."
    )


async def _get_team_lead(session) -> User:
    team_lead, _staff = await _find_team_lead_with_staff(session, 1)
    return team_lead


async def _get_staff_members(session, count: int) -> list[User]:
    _team_lead, staff = await _find_team_lead_with_staff(session, count)
    return staff


async def _make_ticket(
    session, *, account_manager_id, ticket_type, agent_id=None, current_status="OPEN"
):
    client = Client(
        client_id=uuid.uuid4(),
        name="Status-on-assignment Test Client",
        inbox_email=f"status-assign-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="Status-on-assignment regression test ticket",
        ticket_type=ticket_type,
        current_status=current_status,
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return client, ticket


def _build_service(session, *, with_sla=False) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
        sla_service=build_sla_service(session) if with_sla else None,
    )


async def _reload_ticket(session, ticket_id) -> Ticket:
    return await TicketRepository(session).get_by_id(ticket_id)


async def _audit_events(session, ticket_id, event_type):
    result = await session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == ticket_id,
            AuditLog.event_type == event_type,
        )
    )
    return result.scalars().all()


# ---------------------------------------------------------------
# 1. Claim OPEN ticket -> IN_PROGRESS
# ---------------------------------------------------------------


async def test_claim_open_ticket_moves_to_in_progress(db_session):
    [staff] = await _get_staff_members(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=staff.manager_id or staff.user_id,
        ticket_type=staff.category.category_name.value,
        current_status="OPEN",
    )

    service = _build_service(db_session)
    await service.claim_ticket(ticket.ticket_id, staff)

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.IN_PROGRESS
    assert reloaded.agent_id == staff.user_id


# ---------------------------------------------------------------
# 2. Assign (transfer_agent, unclaimed) OPEN ticket -> IN_PROGRESS
# ---------------------------------------------------------------


async def test_assign_unclaimed_open_ticket_moves_to_in_progress(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=None,
        current_status="OPEN",
    )

    service = _build_service(db_session)
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=staff.user_id, reason="Assigning to staff"),
        team_lead,
    )

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.IN_PROGRESS
    assert reloaded.agent_id == staff.user_id


# ---------------------------------------------------------------
# 3. Reassign/transfer OPEN ticket -> IN_PROGRESS where applicable
# ---------------------------------------------------------------


async def test_reassign_open_ticket_to_new_agent_moves_to_in_progress(db_session):
    team_lead, [staff_a, staff_b] = await _find_team_lead_with_staff(db_session, 2)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff_a.user_id,
        current_status="OPEN",
    )

    service = _build_service(db_session)
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=staff_b.user_id, reason="Reassigning"),
        team_lead,
    )

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.IN_PROGRESS
    assert reloaded.agent_id == staff_b.user_id


# ---------------------------------------------------------------
# 4. Transfer of an already IN_PROGRESS ticket -> remains IN_PROGRESS,
#    and no spurious status-change audit data is added.
# ---------------------------------------------------------------


async def test_transfer_already_in_progress_ticket_stays_in_progress(db_session):
    team_lead, [staff_a, staff_b] = await _find_team_lead_with_staff(db_session, 2)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff_a.user_id,
        current_status="IN_PROGRESS",
    )

    service = _build_service(db_session)
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=staff_b.user_id, reason="Reassigning again"),
        team_lead,
    )

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.IN_PROGRESS
    assert reloaded.agent_id == staff_b.user_id

    events = await _audit_events(db_session, ticket.ticket_id, AuditEventType.AGENT_TRANSFERRED)
    assert len(events) == 1
    assert "current_status" not in events[0].new_values
    assert "current_status" not in events[0].old_values


# ---------------------------------------------------------------
# 5. CLOSED/RESOLVED tickets are never reopened by claim/transfer.
# ---------------------------------------------------------------


async def test_transfer_closed_ticket_is_still_rejected(db_session):
    team_lead, [staff_a, staff_b] = await _find_team_lead_with_staff(db_session, 2)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff_a.user_id,
        current_status="CLOSED",
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.transfer_agent(
            ticket.ticket_id,
            TransferAgentRequest(new_agent_id=staff_b.user_id, reason="Should be rejected"),
            team_lead,
        )
    assert exc_info.value.status_code == 400

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.CLOSED
    assert reloaded.agent_id == staff_a.user_id


async def test_transfer_resolved_ticket_does_not_reopen_it(db_session):
    team_lead, [staff_a, staff_b] = await _find_team_lead_with_staff(db_session, 2)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff_a.user_id,
        current_status="RESOLVED",
    )

    service = _build_service(db_session)
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=staff_b.user_id, reason="Reassign after resolve"),
        team_lead,
    )

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    # Transfer must not resurrect a RESOLVED ticket back to IN_PROGRESS —
    # only the OPEN case is ever bumped.
    assert reloaded.current_status == TicketStatus.RESOLVED
    assert reloaded.agent_id == staff_b.user_id


# ---------------------------------------------------------------
# 6. No duplicate audit/status events for the OPEN -> IN_PROGRESS bump.
# ---------------------------------------------------------------


async def test_assign_open_ticket_writes_exactly_one_audit_event(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=None,
        current_status="OPEN",
    )

    service = _build_service(db_session)
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=staff.user_id, reason="Assigning"),
        team_lead,
    )

    transfer_events = await _audit_events(db_session, ticket.ticket_id, AuditEventType.AGENT_TRANSFERRED)
    assert len(transfer_events) == 1
    assert transfer_events[0].old_values["current_status"] == TicketStatus.OPEN
    assert transfer_events[0].new_values["current_status"] == TicketStatus.IN_PROGRESS

    # The status bump must not also produce a second, separate
    # STATUS_CHANGED row — it's folded into the one AGENT_TRANSFERRED
    # event above instead.
    status_changed_events = await _audit_events(
        db_session, ticket.ticket_id, AuditEventType.STATUS_CHANGED
    )
    assert len(status_changed_events) == 0


# ---------------------------------------------------------------
# 7. SLA behavior is unaffected by the OPEN -> IN_PROGRESS bump —
#    transfer_agent never pauses/resumes/completes the Resolution SLA
#    clock (only WAITING_FOR_CLIENT/RESOLVED transitions via
#    change_status do that), and this fix must not change that.
# ---------------------------------------------------------------


async def test_assign_open_ticket_does_not_touch_resolution_sla_clock(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=None,
        current_status="OPEN",
    )

    medium_policy = await SLAPolicyRepository(db_session).get_by_priority(TicketPriority.MEDIUM)
    started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    due_at = started_at + timedelta(hours=3)
    resolution_sla = ResolutionSLA(
        resolution_sla_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        client_id=_client.client_id,
        priority=TicketPriority.MEDIUM,
        status=SLAClockStatus.RUNNING,
        started_at=started_at,
        due_at=due_at,
        active_target_minutes=medium_policy.resolution_target_minutes,
    )
    db_session.add(resolution_sla)
    await db_session.flush()

    service = _build_service(db_session, with_sla=True)
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=staff.user_id, reason="Assigning"),
        team_lead,
    )

    reloaded_ticket = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded_ticket.current_status == TicketStatus.IN_PROGRESS

    result = await db_session.execute(
        select(ResolutionSLA).where(
            ResolutionSLA.resolution_sla_id == resolution_sla.resolution_sla_id
        )
    )
    reloaded_sla = result.scalar_one()
    assert reloaded_sla.status == SLAClockStatus.RUNNING
    assert reloaded_sla.due_at == due_at
    assert reloaded_sla.paused_at is None


# ---------------------------------------------------------------
# 8. Supervisor-tier self-assignment (Team Lead assigns an unclaimed
#    OPEN ticket to *themselves* via transfer_agent, not Claim) also
#    bumps OPEN -> IN_PROGRESS — the rule is keyed on the ticket's own
#    prior status, never on which role the new assignee holds.
# ---------------------------------------------------------------


async def test_team_lead_self_assign_open_ticket_moves_to_in_progress(db_session):
    team_lead = await _get_team_lead(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=None,
        current_status="OPEN",
    )

    service = _build_service(db_session)
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=team_lead.user_id, reason="Taking this myself"),
        team_lead,
    )

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.IN_PROGRESS
    assert reloaded.agent_id == team_lead.user_id


# ---------------------------------------------------------------
# 9. InboxTicketService.create_ticket_from_interaction — the "other
#    assignment path" a ticket-detail-only investigation would miss.
#    A ticket born already assigned (the Create Ticket dialog's
#    "Assigned To" picker) must not sit at OPEN with a real agent_id —
#    exactly the "already assigned and OPEN" inconsistent state this
#    bug report describes. Uses self-assignment (agent_id ==
#    current_user.user_id) so AssignmentService.resolve_target's
#    hierarchy check is trivially satisfied, keeping this test focused
#    on the status-transition fix rather than assignment-candidate
#    resolution (already covered by test_transfer_candidates.py).
# ---------------------------------------------------------------


async def _make_inbox_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="Status-on-creation Test Client",
        inbox_email=f"status-on-creation-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


async def _make_pending_interaction(session, *, client_id) -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        status=InteractionStatus.PENDING,
        payload={"message": "test"},
        parent_interaction_id=None,
        ticket_id=None,
        client_id=client_id,
        is_visible=True,
        subject="Status-on-creation test subject",
        received_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()
    return interaction


def _build_inbox_ticket_service(session) -> InboxTicketService:
    return InboxTicketService(
        ticket_repository=TicketRepository(session),
        interaction_repository=InteractionRepository(session),
        assignment_service=AssignmentService(UserRepository(session)),
        client_repository=ClientRepository(session),
    )


async def test_create_ticket_with_preassigned_agent_starts_in_progress(db_session):
    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["communication:convert_to_ticket"]
    client = await _make_inbox_client(
        db_session, account_manager_id=team_lead.manager_id or team_lead.user_id
    )
    interaction = await _make_pending_interaction(db_session, client_id=client.client_id)

    service = _build_inbox_ticket_service(db_session)
    response = await service.create_ticket_from_interaction(
        TicketFromInteractionCreate(
            interaction_id=interaction.interaction_id,
            title="Pre-assigned-at-creation regression test ticket",
            ticket_type=team_lead.category.category_name.value,
            current_priority=TicketPriority.MEDIUM,
            agent_id=team_lead.user_id,
        ),
        current_user=team_lead,
    )

    ticket = await _reload_ticket(db_session, response.ticket_id)
    assert ticket.agent_id == team_lead.user_id
    # The exact reported inconsistent state (Case 8): a ticket created
    # with a real agent_id must never be left at OPEN, the model's own
    # default — before this fix, TicketCreate's deliberate omission of
    # current_status meant it always was.
    assert ticket.current_status == TicketStatus.IN_PROGRESS

    events = await _audit_events(db_session, ticket.ticket_id, AuditEventType.TICKET_CREATED)
    assert len(events) == 1
    # JSONB round-trips a UUID as its string form, unlike the str-enum
    # current_status field below (whose TicketStatus/str equality
    # holds either way).
    assert events[0].new_values["agent_id"] == str(team_lead.user_id)
    assert events[0].new_values["current_status"] == TicketStatus.IN_PROGRESS

    # Folded into the one TICKET_CREATED event, not a second
    # STATUS_CHANGED row — same "one user action, one audit entry"
    # convention transfer_agent's own status bump already follows.
    status_changed_events = await _audit_events(
        db_session, ticket.ticket_id, AuditEventType.STATUS_CHANGED
    )
    assert len(status_changed_events) == 0


async def test_create_ticket_without_agent_stays_open(db_session):
    team_lead = await _get_team_lead(db_session)
    team_lead.permissions = ["communication:convert_to_ticket"]
    client = await _make_inbox_client(
        db_session, account_manager_id=team_lead.manager_id or team_lead.user_id
    )
    interaction = await _make_pending_interaction(db_session, client_id=client.client_id)

    service = _build_inbox_ticket_service(db_session)
    response = await service.create_ticket_from_interaction(
        TicketFromInteractionCreate(
            interaction_id=interaction.interaction_id,
            title="Unassigned-at-creation regression test ticket",
            ticket_type=team_lead.category.category_name.value,
            current_priority=TicketPriority.MEDIUM,
            agent_id=None,
        ),
        current_user=team_lead,
    )

    ticket = await _reload_ticket(db_session, response.ticket_id)
    # A ticket created genuinely unassigned (the shared-pool default)
    # must still land OPEN — this fix only applies when there's a real
    # assignee, never as a side effect of ticket creation itself.
    assert ticket.agent_id is None
    assert ticket.current_status == TicketStatus.OPEN


# ---------------------------------------------------------------
# 10. The generic PATCH /tickets/{id} route (TicketService.update)
#     must not be usable to silently reassign a ticket's agent_id —
#     it has none of transfer_agent's role/category/hierarchy checks
#     or its status-transition logic, so a caller reaching it with
#     agent_id set would bypass all of that. Not currently exercised
#     by the frontend (TicketHeader.tsx only ever PATCHes the title),
#     but closed defensively rather than left as a latent gap (the
#     task's own "already assigned and OPEN" investigation explicitly
#     calls out checking every write path, not just the ones already
#     known to be used).
# ---------------------------------------------------------------


def _build_ticket_service(session) -> TicketService:
    return TicketService(
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
    )


async def test_generic_update_endpoint_rejects_agent_id_reassignment(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    team_lead.permissions = ["ticket:change_category"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=None,
        current_status="OPEN",
    )

    service = _build_ticket_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.update(
            ticket_id=ticket.ticket_id,
            request=TicketUpdate(agent_id=staff.user_id),
            current_user=team_lead,
        )
    assert exc_info.value.status_code == 400

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.agent_id is None
    assert reloaded.current_status == TicketStatus.OPEN


async def test_generic_update_endpoint_still_allows_non_agent_fields(db_session):
    """
    The new agent_id guard must be narrowly scoped — every other field
    this route legitimately updates (e.g. title) must keep working.
    """

    team_lead, [_staff] = await _find_team_lead_with_staff(db_session, 1)
    team_lead.permissions = ["ticket:change_category"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=None,
        current_status="OPEN",
    )

    service = _build_ticket_service(db_session)
    response = await service.update(
        ticket_id=ticket.ticket_id,
        request=TicketUpdate(title="Renamed via generic PATCH"),
        current_user=team_lead,
    )
    assert response.title == "Renamed via generic PATCH"


# ---------------------------------------------------------------
# 11. TicketRepository.claim's atomic WHERE-gated guard must reject a
#     second claim attempt even when handed the same (now-stale)
#     in-memory Ticket object a race between two concurrent requests
#     would produce — proxying a genuine two-connection race without
#     needing two real concurrent sessions in this rolled-back-
#     transaction test convention.
# ---------------------------------------------------------------


async def test_claim_repository_guard_rejects_second_claim_on_stale_object(db_session):
    [staff_a, staff_b] = await _get_staff_members(db_session, 2)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=staff_a.manager_id or staff_a.user_id,
        ticket_type=staff_a.category.category_name.value,
        agent_id=None,
        current_status="OPEN",
    )

    repo = TicketRepository(db_session)
    first = await repo.claim(ticket, staff_a.user_id)
    assert first is not None
    assert first.current_status == TicketStatus.IN_PROGRESS
    assert first.agent_id == staff_a.user_id

    # Same stale `ticket` object, as if a second request had read it
    # before the first claim's write landed — the WHERE-gated UPDATE
    # (agent_id IS NULL AND current_status = OPEN) must still reject
    # this rather than overwriting the winner.
    second = await repo.claim(ticket, staff_b.user_id)
    assert second is None

    reloaded = await _reload_ticket(db_session, ticket.ticket_id)
    assert reloaded.agent_id == staff_a.user_id
    assert reloaded.current_status == TicketStatus.IN_PROGRESS
