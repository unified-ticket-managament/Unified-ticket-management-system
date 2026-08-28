# test_resolution_sla_reopen.py
#
# Regression coverage for Issues 9 and 10:
#
#   9. IN_PROGRESS -> RESOLVED -> IN_PROGRESS: the Resolution SLA
#      clock correctly COMPLETEs on the first transition (see
#      test_resolution_sla_resolved_transition.py) but used to stay
#      permanently COMPLETED on the reopen — every other clock-mutator
#      treats COMPLETED as terminal by design, and change_status had
#      no branch at all for leaving RESOLVED. Fixed by adding an elif
#      to change_status's existing RESOLVED-branch if-statement, calling
#      SLAService.reopen_resolution_clock (the one method built to
#      revive a COMPLETED clock) on old_status == RESOLVED and
#      new_status != RESOLVED.
#
#  10. The dedicated Reopen Ticket action (InteractionService.
#      reopen_ticket, CLOSED -> OPEN) used to not touch the Resolution
#      SLA clock at all — its own comment cited create_or_resume_
#      resolution_clock's "never resurrect a COMPLETED clock" rule,
#      which is the wrong method to cite (that rule is about the
#      ordinary pause/resume case); reopen_resolution_clock exists
#      precisely for this moment and was simply never called. Fixed by
#      calling it directly inside reopen_ticket. This also let
#      InboxTicketService.attach_to_existing_ticket drop its own
#      separate, now-redundant reopen_resolution_clock call (which
#      would otherwise double-bump escalation_cycle for one logical
#      reopen-with-priority-change) — see that method's own updated
#      comment.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention/helpers as
# test_resolution_sla_resolved_transition.py and
# test_ticket_status_on_assignment.py (dynamic category discovery,
# not a hardcoded category name, since that's known to drift in this
# shared dev database).

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
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket_action import PriorityChangeRequest, StatusChangeRequest
from app.ticketing.services.escalation_service import build_escalation_service
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.sla_service import build_sla_service


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
        .options(joinedload(User.role), joinedload(User.category), joinedload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if user.category is not None:
            return user
    pytest.skip("No active Team Lead with a category in the connected database.")


async def _make_scenario(session, *, initial_status):
    team_lead = await _get_team_lead(session)

    client = Client(
        client_id=uuid.uuid4(),
        name="Resolution-SLA-reopen Test Client",
        inbox_email=f"sla-reopen-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        is_active=True,
    )
    session.add(client)

    started_at = datetime.now(timezone.utc) - timedelta(hours=1)

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=None,
        title="Resolution-SLA-reopen regression test ticket",
        ticket_type=team_lead.category.category_name,
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
        escalation_cycle=0,
    )
    session.add(resolution_sla)
    await session.flush()

    return team_lead, client, ticket, resolution_sla


def _build_service(session) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
        sla_service=build_sla_service(session),
        escalation_service=build_escalation_service(session),
    )


async def _reload_resolution_sla(session, resolution_sla_id) -> ResolutionSLA:
    result = await session.execute(
        select(ResolutionSLA).where(ResolutionSLA.resolution_sla_id == resolution_sla_id)
    )
    return result.scalar_one()


async def _count_resolution_slas_for_ticket(session, ticket_id) -> int:
    result = await session.execute(
        select(ResolutionSLA).where(ResolutionSLA.ticket_id == ticket_id)
    )
    return len(result.scalars().all())


# ---------------------------------------------------------------
# Issue 9 — change_status RESOLVED -> active resumes the clock
# ---------------------------------------------------------------


async def test_reopening_from_resolved_via_change_status_revives_the_clock(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, initial_status="IN_PROGRESS"
    )
    team_lead.permissions = ["ticket:update_status"]
    service = _build_service(db_session)

    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="RESOLVED"), team_lead
    )
    completed = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert completed.status == SLAClockStatus.COMPLETED
    assert completed.completed_at is not None
    # Snapshot the plain value, not a reference to the ORM object —
    # SQLAlchemy's identity map returns the SAME Python instance on a
    # later re-select of the same PK, so comparing `.due_at` against
    # `completed` again after further mutation would silently compare
    # the object against its own later, already-mutated self.
    completed_due_at = completed.due_at

    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="IN_PROGRESS"), team_lead
    )

    reopened = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reopened.status == SLAClockStatus.RUNNING
    assert reopened.completed_at is None
    assert reopened.due_at > completed_due_at
    assert reopened.escalation_cycle == 1

    # Same row, reused — never a second ResolutionSLA for this ticket.
    assert await _count_resolution_slas_for_ticket(db_session, ticket.ticket_id) == 1


async def test_repeated_resolve_reopen_cycles_stay_on_one_clock_row(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, initial_status="IN_PROGRESS"
    )
    team_lead.permissions = ["ticket:update_status"]
    service = _build_service(db_session)

    # IN_PROGRESS -> RESOLVED -> IN_PROGRESS -> RESOLVED -> IN_PROGRESS
    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="RESOLVED"), team_lead
    )
    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="IN_PROGRESS"), team_lead
    )
    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="RESOLVED"), team_lead
    )
    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="IN_PROGRESS"), team_lead
    )

    final = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert final.status == SLAClockStatus.RUNNING
    assert final.completed_at is None
    assert final.escalation_cycle == 2  # one bump per reopen
    assert await _count_resolution_slas_for_ticket(db_session, ticket.ticket_id) == 1

    resumed_events = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == ticket.ticket_id,
            AuditLog.event_type == AuditEventType.SLA_RESUMED,
        )
    )
    # Two reopen-from-RESOLVED events, each its own audit row — not
    # deduped away, not doubled either.
    assert len(resumed_events.scalars().all()) == 2


# ---------------------------------------------------------------
# Issue 10 — the dedicated Reopen Ticket action starts the clock
# ---------------------------------------------------------------


async def test_reopen_ticket_starts_the_resolution_sla_immediately(db_session):
    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, initial_status="IN_PROGRESS"
    )
    team_lead.permissions = [
        "ticket:update_status",
        "ticket:close_ticket",
        "ticket:archive_attachment",
    ]
    service = _build_service(db_session)

    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="RESOLVED"), team_lead
    )
    await service.close_ticket(ticket.ticket_id, team_lead)
    closed_clock = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert closed_clock.status == SLAClockStatus.COMPLETED
    # Snapshot the plain value — see the identical comment in the
    # change_status test above for why this can't be a reference to
    # the ORM object itself.
    closed_due_at = closed_clock.due_at

    # A separate role bypass is needed for the dedicated Reopen
    # action's own ensure_can_reopen_ticket check (CLOSE_REOPEN_
    # BYPASS_ROLE_NAMES is narrower than SUPERVISOR_ROLE_NAMES —
    # Site Lead/Super Admin only) — a plain permission grant on Team
    # Lead covers it without needing a different seeded role.
    team_lead.permissions.append("ticket:reopen")
    team_lead.permissions.append("ticket:editother_ticket")

    await service.reopen_ticket(ticket.ticket_id, team_lead)

    reopened = await TicketRepository(db_session).get_by_id(ticket.ticket_id)
    assert reopened.current_status == "OPEN"

    reopened_clock = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert reopened_clock.status == SLAClockStatus.RUNNING
    assert reopened_clock.completed_at is None
    assert reopened_clock.due_at > closed_due_at
    # No subsequent status change required — the dedicated action
    # alone must start it, immediately.
    assert await _count_resolution_slas_for_ticket(db_session, ticket.ticket_id) == 1


async def test_reopen_then_priority_change_bumps_escalation_cycle_only_once(db_session):
    """
    Regression guard for the double-bump this fix could have
    introduced: InboxTicketService.attach_to_existing_ticket's own
    reopen-then-optionally-change-priority sequence must land on the
    FINAL priority's target via change_priority's own existing SLA
    reshift call (no longer a no-op now that reopen_ticket already
    revived the clock), not via two competing reopen_resolution_clock
    calls.
    """

    team_lead, _client, ticket, resolution_sla = await _make_scenario(
        db_session, initial_status="IN_PROGRESS"
    )
    team_lead.permissions = [
        "ticket:update_status",
        "ticket:close_ticket",
        "ticket:archive_attachment",
        "ticket:reopen",
        "ticket:editother_ticket",
        "ticket:change_priority",
    ]
    service = _build_service(db_session)

    await service.change_status(
        ticket.ticket_id, StatusChangeRequest(new_status="RESOLVED"), team_lead
    )
    await service.close_ticket(ticket.ticket_id, team_lead)

    await service.reopen_ticket(ticket.ticket_id, team_lead)
    after_reopen = await _reload_resolution_sla(db_session, resolution_sla.resolution_sla_id)
    assert after_reopen.escalation_cycle == 1

    await service.change_priority(
        ticket.ticket_id, PriorityChangeRequest(new_priority="HIGH"), team_lead
    )

    after_priority_change = await _reload_resolution_sla(
        db_session, resolution_sla.resolution_sla_id
    )
    # Still just the one bump from reopen_ticket itself — change_priority's
    # reshift adjusts due_at/priority in place, it doesn't bump the cycle.
    assert after_priority_change.escalation_cycle == 1
    assert after_priority_change.priority == "HIGH"
    assert after_priority_change.status == SLAClockStatus.RUNNING
