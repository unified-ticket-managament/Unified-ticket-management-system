# test_escalation_read_only_access.py
#
# Regression coverage for a real, confirmed bug: ensure_agent_can_act_
# on_ticket's escalation-freeze check used to run AFTER the
# SUPERVISOR_ROLE_NAMES bypass, not before it — and every possible
# escalation owner (TicketEscalation.owner_ids can only ever name a
# Team Lead/Account Manager/Site Lead/Super Admin, see
# EscalationService._resolve_owners_for_level) is itself a supervisor.
# That meant the freeze could never actually apply to the population
# it exists to restrict: a Team Lead a ticket just escalated to had
# full edit access (reply, internal note, status/priority change,
# close) the instant it escalated to them, before ever clicking
# Acknowledge — only the *previous* (non-supervisor) assignee was ever
# actually frozen.
#
# Fixed by moving the freeze check in access_control.py's
# ensure_agent_can_act_on_ticket to run before the supervisor bypass,
# extracting it into a standalone ensure_ticket_not_frozen_by_escalation
# helper (also used directly by change_priority, which deliberately
# skips the rest of that function's ownership check), and wiring the
# escalation/handling-SLA repositories into close_ticket/reopen_ticket/
# AttachmentService.upload_attachment, none of which previously passed
# them at all.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_escalation_service.py.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import EscalationStatus, SLAClockStatus, TicketPriority
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
from app.ticketing.schemas.note import InternalNoteCreate
from app.ticketing.schemas.ticket_action import (
    PriorityChangeRequest,
    ReplyCreate,
    StatusChangeRequest,
)
from app.ticketing.services.escalation_service import EscalationService, build_escalation_service
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


async def _make_scenario(session, *, agent_id):
    """A real Client + Ticket + running Resolution SLA, owned by the seeded Eligibility category."""

    team_lead = await _get_team_lead(session)

    client = Client(
        client_id=uuid.uuid4(),
        name="Read-Only-Access Test Client",
        inbox_email=f"read-only-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        is_active=True,
    )
    session.add(client)

    started_at = datetime.now(timezone.utc) - timedelta(hours=1)

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="Read-only-access regression test ticket",
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


def _build_escalation_service(session) -> EscalationService:
    return build_escalation_service(session)


async def _escalate_to_team_lead(session, ticket, resolution_clock, team_lead) -> None:
    """
    Manually escalates the ticket (Staff-assigned, so
    _resolve_starting_level starts at TEAM_LEAD) via the exact same
    EscalationService.manual_escalate real production code path a
    Manual Escalation click uses — leaves a real ACTIVE
    TicketEscalation row with owner_ids=[team_lead.user_id] and no
    EscalationHandlingSLA row yet (i.e. genuinely unaccepted).
    """

    team_lead.permissions = ["ticket:escalate"]
    escalation_service = _build_escalation_service(session)
    await escalation_service.manual_escalate(ticket.ticket_id, team_lead)


async def test_escalation_owner_is_frozen_before_acceptance(db_session):
    """
    The core regression: Team Lead — the escalation owner, a
    supervisor — must be blocked from every edit action while the
    escalation is still ACTIVE (awaiting acknowledgment and
    assignment), not just the previous (Staff) assignee.
    """

    staff = await _get_staff(db_session)
    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, agent_id=staff.user_id
    )
    await _escalate_to_team_lead(db_session, ticket, resolution_sla, team_lead)

    team_lead.permissions = [
        "ticket:update_status",
        "ticket:change_priority",
        "ticket:reply",
        "communication:reply_internal",
        "communication:reply_external",
        "ticket:close_ticket",
    ]
    service = _build_interaction_service(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await service.change_status(
            ticket.ticket_id, StatusChangeRequest(new_status="IN_PROGRESS"), team_lead
        )
    assert exc_info.value.status_code == 403
    assert "escalated" in exc_info.value.detail.lower()

    with pytest.raises(HTTPException) as exc_info:
        await service.change_priority(
            ticket.ticket_id, PriorityChangeRequest(new_priority="HIGH"), team_lead
        )
    assert exc_info.value.status_code == 403
    assert "escalated" in exc_info.value.detail.lower()

    with pytest.raises(HTTPException) as exc_info:
        await service.add_internal_note(
            ticket.ticket_id,
            InternalNoteCreate(subject="test", note="test note"),
            team_lead,
        )
    assert exc_info.value.status_code == 403
    assert "escalated" in exc_info.value.detail.lower()

    with pytest.raises(HTTPException) as exc_info:
        await service.add_reply(
            ticket.ticket_id, ReplyCreate(message="test reply"), team_lead
        )
    assert exc_info.value.status_code == 403
    assert "escalated" in exc_info.value.detail.lower()

    with pytest.raises(HTTPException) as exc_info:
        await service.close_ticket(ticket.ticket_id, team_lead)
    assert exc_info.value.status_code == 403
    assert "escalated" in exc_info.value.detail.lower()

    # The ticket itself must be genuinely untouched by every attempt above.
    reloaded = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reloaded.current_status == "OPEN"
    assert reloaded.current_priority == TicketPriority.CRITICAL  # from escalating itself
    assert reloaded.agent_id == staff.user_id


async def test_edit_access_restored_after_acknowledge_and_assign(db_session):
    """
    Once acceptance completes (acknowledge + confirm_assignment, or
    claim/transfer), the freeze lifts and normal RBAC-permission-based
    access resumes for whoever can act on the ticket — here, the Team
    Lead confirming the ticket stays with the current (Staff) assignee,
    which should unfreeze the ticket for everyone without changing who
    it's assigned to.
    """

    staff = await _get_staff(db_session)
    team_lead, _client, ticket, _resolution_sla = await _make_scenario(
        db_session, agent_id=staff.user_id
    )
    await _escalate_to_team_lead(db_session, ticket, _resolution_sla, team_lead)

    escalation_repo = TicketEscalationRepository(db_session)
    escalation = await escalation_repo.get_active_by_ticket_id(ticket.ticket_id)
    assert escalation is not None
    assert escalation.status == EscalationStatus.ACTIVE

    # Acknowledge, then confirm the ticket stays with Staff — the one
    # confirm_assignment branch that never reaches claim_ticket/
    # transfer_agent, so it's the real test that _complete_acceptance
    # (not some other side effect) is what lifts the freeze.
    escalation_service = _build_escalation_service(db_session)
    await escalation_service.acknowledge(ticket.ticket_id, team_lead)
    await escalation_service.confirm_assignment(ticket.ticket_id, team_lead)

    reloaded_escalation = await escalation_repo.get_active_by_ticket_id(ticket.ticket_id)
    assert reloaded_escalation.handling_stage_due_at is not None  # acceptance completed

    staff.permissions = ["ticket:update_status", "ticket:editown_ticket"]
    service = _build_interaction_service(db_session)

    # Staff — the still-assigned agent — can now act again via
    # ticket:editown_ticket, exactly as before the escalation ever
    # existed. This is the "edit access follows the assigned owner"
    # requirement: the ticket was never reassigned, so it's still
    # Staff who can work it, not Team Lead.
    result = await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="IN_PROGRESS"), staff
    )
    assert result.ticket_id == ticket.ticket_id

    reloaded = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reloaded.current_status == "IN_PROGRESS"
