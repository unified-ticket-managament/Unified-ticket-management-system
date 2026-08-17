# test_view_escalated_permission.py
#
# Regression coverage for `ticket:view_escalated`'s intended contract:
# complete READ-ONLY visibility into an authorized escalated ticket
# (ticket details, timeline, attachments, audit trail, SLA/escalation
# state), and NOTHING else — it must never widen any mutating action,
# most importantly Manual Escalation (EscalationService.manual_escalate),
# which is (and must remain) authorized purely by ticket ownership
# (Ticket.agent_id / TicketEscalation.owner_ids), never by any RBAC
# permission at all. See root CLAUDE.md's "RBAC permission compliance
# audit" section and access_control.ensure_agent_can_view_ticket_
# including_escalated's own docstring for the read-only widening this
# file verifies; EscalationService.manual_escalate/acknowledge/
# confirm_assignment's own docstrings for why they are deliberately
# ownership-only with no permission fallback.
#
# The "viewer" in every test below is a Staff member in a DIFFERENT
# category than the ticket's own ticket_type, holding ONLY
# ["ticket:view_escalated"] — i.e. exactly the population this
# permission is meant to grant something to, and exactly the
# population that would otherwise fail ensure_agent_can_view_ticket's
# category scoping. This is deliberately not the escalation's own
# owner (a Team Lead the ticket escalated to) — that population is
# already covered by test_escalation_read_only_access.py and
# test_escalation_service.py.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_escalation_service.py / test_escalation_read_only_access.py.
# Known pre-existing issue (see root CLAUDE.md): DB-touching test files
# hang if run in the same pytest process as another DB-touching file —
# run this file in isolation.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import (
    EscalationStatus,
    InteractionDirection,
    InteractionStatus,
    SLAClockStatus,
    TicketPriority,
)
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.schemas.interaction import HideInteractionRequest
from app.ticketing.repositories.audit_log_repository import AuditLogRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_escalation_repository import (
    TicketEscalationRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.note import InternalNoteCreate
from app.ticketing.schemas.ticket_action import (
    PriorityChangeRequest,
    StatusChangeRequest,
)
from app.ticketing.services.access_control import (
    ensure_agent_can_view_ticket_including_escalated,
)
from app.ticketing.services.escalation_service import EscalationService, build_escalation_service
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.sla_service import build_sla_service
from app.ticketing.services.ticket_service import TicketService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_team_lead_with_category(session) -> User:
    # ensure_agent_can_view_ticket reads the many-to-many `categories`
    # collection (not the legacy singular `category`/`category_id`) —
    # see access_control.py — so that's what must be eager-loaded here
    # to avoid a lazy-load (MissingGreenlet) outside the async context.
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), selectinload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if user.categories:
            return user
    pytest.skip("No active seeded Team Lead with a category found.")


async def _get_staff_for_category(session, category_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), selectinload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if any(c.category_name.value == category_name for c in user.categories):
            return user
    pytest.skip(f"No active seeded Staff found for category {category_name!r}.")


async def _get_staff_outside_category(session, excluded_category_name: str) -> User:
    """A Staff member with NO membership in the ticket's own category —
    fails ensure_agent_can_view_ticket's category scoping for a ticket
    filed under excluded_category_name, exactly the population
    ticket:view_escalated's override is meant to widen."""

    result = await session.execute(
        select(User)
        .options(joinedload(User.role), selectinload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if user.categories and all(
            c.category_name.value != excluded_category_name for c in user.categories
        ):
            return user
    pytest.skip("No active seeded Staff outside the ticket's own category found.")


async def _make_scenario(session, *, agent_id, ticket_type: str, account_manager_id):
    """A real Client + Ticket + running Resolution SLA under ticket_type."""

    client = Client(
        client_id=uuid.uuid4(),
        name="View-Escalated-Permission Test Client",
        inbox_email=f"view-escalated-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)

    started_at = datetime.now(timezone.utc) - timedelta(hours=1)

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="View-escalated-permission regression test ticket",
        ticket_type=ticket_type,
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

    return client, ticket, resolution_sla


def _build_interaction_service(session, *, with_escalation_widening: bool) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        attachment_repository=None,
        storage_service=None,
        audit_log_repository=AuditLogRepository(session),
        client_repository=ClientRepository(session),
        sla_service=build_sla_service(session),
        escalation_service=build_escalation_service(session),
        ticket_escalation_repository=(
            TicketEscalationRepository(session) if with_escalation_widening else None
        ),
    )


def _build_ticket_service(session) -> TicketService:
    return TicketService(
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
        ticket_escalation_repository=TicketEscalationRepository(session),
    )


def _build_escalation_service(session) -> EscalationService:
    return build_escalation_service(session)


async def _setup_escalated_ticket(session):
    team_lead = await _get_team_lead_with_category(session)
    category_name = team_lead.categories[0].category_name.value
    staff_owner = await _get_staff_for_category(session, category_name)
    outsider = await _get_staff_outside_category(session, category_name)

    _client, ticket, resolution_sla = await _make_scenario(
        session,
        agent_id=staff_owner.user_id,
        ticket_type=category_name,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
    )

    # manual_escalate's sole authorization criterion is ownership
    # (Ticket.agent_id), not any permission — with no active escalation
    # yet, that's the current assignee (staff_owner), never the future
    # escalation owner (team_lead). See EscalationService.manual_escalate's
    # own docstring/ownership check.
    escalation_service = _build_escalation_service(session)
    await escalation_service.manual_escalate(ticket.ticket_id, staff_owner)

    outsider.permissions = ["ticket:view_escalated"]

    return staff_owner, team_lead, outsider, ticket, resolution_sla


# ---------------------------------------------------------
# Read access IS granted
# ---------------------------------------------------------


async def test_viewer_can_see_ticket_details(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    service = _build_ticket_service(db_session)
    response = await service.get_by_id(ticket.ticket_id, outsider)

    assert response.ticket_id == ticket.ticket_id
    assert response.is_escalated is True


async def test_viewer_can_see_timeline(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    service = _build_interaction_service(db_session, with_escalation_widening=True)
    rows = await service.get_ticket_interactions(ticket.ticket_id, outsider)

    assert isinstance(rows, list)


async def test_viewer_can_see_attachments(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    service = _build_interaction_service(db_session, with_escalation_widening=True)
    rows = await service.get_ticket_attachments(ticket.ticket_id, outsider)

    assert rows == []


async def test_viewer_can_see_audit_logs_without_view_audit_trail_permission(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )
    assert "ticket:view_audit_trail" not in outsider.permissions

    service = _build_interaction_service(db_session, with_escalation_widening=True)
    rows = await service.get_ticket_audit_logs(ticket.ticket_id, outsider)

    assert isinstance(rows, list)
    assert len(rows) > 0  # at least the ESCALATION_CREATED entry


async def test_viewer_can_see_sla_and_escalation_state(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    granted_via_escalation = await ensure_agent_can_view_ticket_including_escalated(
        ticket, outsider, ClientRepository(db_session), TicketEscalationRepository(db_session)
    )
    assert granted_via_escalation is True

    sla_service = build_sla_service(db_session)
    sla_state = await sla_service.get_ticket_sla_state(ticket_id=ticket.ticket_id)
    assert sla_state.resolution is not None


async def test_viewer_loses_access_once_escalation_closes(db_session):
    """The widening is escalation-scoped, not a permanent grant — once
    the ticket's escalation is no longer active, the outsider goes back
    to being blocked by ordinary category scoping."""

    _staff_owner, team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    escalation_repo = TicketEscalationRepository(db_session)
    escalation = await escalation_repo.get_active_by_ticket_id(ticket.ticket_id)
    await escalation_repo.close(
        escalation, reason="test cleanup", at=datetime.now(timezone.utc)
    )
    await db_session.flush()

    service = _build_ticket_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_by_id(ticket.ticket_id, outsider)
    assert exc_info.value.status_code == 403


async def test_viewer_without_active_escalation_has_no_widened_access(db_session):
    """No escalation at all yet -> the outsider (still only holding
    ticket:view_escalated) is blocked exactly like before this feature
    existed."""

    team_lead = await _get_team_lead_with_category(db_session)
    category_name = team_lead.categories[0].category_name.value
    staff_owner = await _get_staff_for_category(db_session, category_name)
    outsider = await _get_staff_outside_category(db_session, category_name)
    outsider.permissions = ["ticket:view_escalated"]

    _client, ticket, _resolution_sla = await _make_scenario(
        db_session,
        agent_id=staff_owner.user_id,
        ticket_type=category_name,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
    )

    service = _build_ticket_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_by_id(ticket.ticket_id, outsider)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Manual Escalation, and every other mutation, is NOT granted
# ---------------------------------------------------------


async def test_viewer_cannot_manually_escalate(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    escalation_service = _build_escalation_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await escalation_service.manual_escalate(ticket.ticket_id, outsider)
    assert exc_info.value.status_code == 403


async def test_viewer_cannot_manually_escalate_unescalated_ticket(db_session):
    """Same rejection for a ticket that isn't escalated yet at all —
    manual_escalate never even consults ticket:view_escalated, so this
    holds regardless of escalation state."""

    team_lead = await _get_team_lead_with_category(db_session)
    category_name = team_lead.categories[0].category_name.value
    staff_owner = await _get_staff_for_category(db_session, category_name)
    outsider = await _get_staff_outside_category(db_session, category_name)
    outsider.permissions = ["ticket:view_escalated"]

    _client, ticket, _resolution_sla = await _make_scenario(
        db_session,
        agent_id=staff_owner.user_id,
        ticket_type=category_name,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
    )

    escalation_service = _build_escalation_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await escalation_service.manual_escalate(ticket.ticket_id, outsider)
    assert exc_info.value.status_code == 403


async def test_viewer_cannot_acknowledge_or_confirm_assignment(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    escalation_service = _build_escalation_service(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await escalation_service.acknowledge(ticket.ticket_id, outsider)
    assert exc_info.value.status_code in (400, 403)

    with pytest.raises(HTTPException) as exc_info:
        await escalation_service.confirm_assignment(ticket.ticket_id, outsider)
    assert exc_info.value.status_code in (400, 403)


async def test_viewer_cannot_change_status_or_priority(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    service = _build_interaction_service(db_session, with_escalation_widening=False)
    outsider.permissions = [
        "ticket:view_escalated",
        "ticket:update_status",
        "ticket:change_priority",
    ]

    with pytest.raises(HTTPException) as exc_info:
        await service.change_status(
            ticket.ticket_id, StatusChangeRequest(new_status="IN_PROGRESS"), outsider
        )
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        await service.change_priority(
            ticket.ticket_id, PriorityChangeRequest(new_priority="HIGH"), outsider
        )
    assert exc_info.value.status_code == 403


async def test_viewer_cannot_add_internal_note_or_reply(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    service = _build_interaction_service(db_session, with_escalation_widening=False)
    outsider.permissions = [
        "ticket:view_escalated",
        "ticket:reply",
        "communication:reply_internal",
        "communication:reply_external",
    ]

    with pytest.raises(HTTPException) as exc_info:
        await service.add_internal_note(
            ticket.ticket_id,
            InternalNoteCreate(subject="test", note="test note"),
            outsider,
        )
    assert exc_info.value.status_code == 403


async def test_viewer_cannot_close_ticket(db_session):
    _staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    service = _build_interaction_service(db_session, with_escalation_widening=False)
    outsider.permissions = ["ticket:view_escalated", "ticket:close_ticket"]

    with pytest.raises(HTTPException) as exc_info:
        await service.close_ticket(ticket.ticket_id, outsider)
    assert exc_info.value.status_code == 403


async def test_viewer_cannot_hide_interaction(db_session):
    staff_owner, _team_lead, outsider, ticket, _resolution_sla = await _setup_escalated_ticket(
        db_session
    )

    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        interaction_type="INTERNAL_NOTE",
        status=InteractionStatus.ASSIGNED,
        direction=InteractionDirection.INTERNAL,
        performed_by=staff_owner.user_id,
        payload={"note": "test note"},
        is_visible=True,
    )
    db_session.add(interaction)
    await db_session.flush()

    service = _build_interaction_service(db_session, with_escalation_widening=False)
    outsider.permissions = ["ticket:view_escalated", "ticket:hide_interaction"]

    with pytest.raises(HTTPException) as exc_info:
        await service.hide_interaction(
            ticket.ticket_id,
            interaction.interaction_id,
            HideInteractionRequest(),
            outsider,
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Regression: a genuinely-authorized user is unaffected
# ---------------------------------------------------------


async def test_actual_owner_can_still_manually_escalate(db_session):
    """The ticket's real current owner (Ticket.agent_id) must still be
    able to escalate it — confirms this fix didn't collaterally
    tighten the real, ownership-based authorization path. No
    permission at all is involved (staff_owner is given none)."""

    team_lead = await _get_team_lead_with_category(db_session)
    category_name = team_lead.categories[0].category_name.value
    staff_owner = await _get_staff_for_category(db_session, category_name)
    staff_owner.permissions = []

    _client, ticket, _resolution_sla = await _make_scenario(
        db_session,
        agent_id=staff_owner.user_id,
        ticket_type=category_name,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
    )

    escalation_service = _build_escalation_service(db_session)
    result = await escalation_service.manual_escalate(ticket.ticket_id, staff_owner)

    assert result.ticket_id == ticket.ticket_id
    reloaded = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reloaded.current_priority == TicketPriority.CRITICAL
