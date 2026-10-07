# test_escalation_notification_regression.py
#
# Regression guard: the Team Lead ASSIGNMENT-scope rule
# (AssignmentService.ensure_team_lead_can_assign / team_lead_staff_ids)
# must never influence WHO IS NOTIFIED about an escalation. Recipients
# come only from the assignment chain + reporting manager
# (escalation_rules.build_chain_owner_ids / EscalationService._notify_owners
# / resolve_global_inbox_user_ids). A Team Lead who is the assigning
# manager keeps receiving the notification, alongside the reporting
# manager, exactly once.
#
# Uses the same real seeded employees as test_assignment_chain_escalation.py
# (skips if absent) inside a rolled-back transaction; Pavana's
# reporting_manager_id is overridden in-session only.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import User

from app.database.session import AsyncSessionLocal, engine
from app.notifications.models import Notification
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.enums import (
    OWNER_ROLE_ASSIGNEE_CHAIN,
    OWNER_ROLE_REPORTING_MANAGER,
    SLAClockStatus,
    TicketPriority,
)
from app.ticketing.models.client import Client
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.audit_log_repository import AuditLogRepository
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_escalation_repository import TicketEscalationRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.assignment_service import AssignmentService
from app.ticketing.services.escalation_rules import build_chain_owner_ids
from app.ticketing.services.escalation_service import EscalationService

CATEGORY = "Payment Posting"


@pytest.fixture(autouse=True)
def _no_real_emails(monkeypatch):
    monkeypatch.setattr(
        "app.notifications.email_notifier.queue_notification_emails", lambda created: None
    )


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _user(session, name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category), joinedload(User.categories))
        .where(User.name == name)
    )
    user = result.unique().scalar_one_or_none()
    if user is None:
        pytest.skip(f"Seeded user {name!r} not found in this database.")
    return user


async def _ticket(session, *, agent_id, assigned_by, created_by):
    client = Client(
        client_id=uuid.uuid4(),
        name="Escalation Notification Regression Client",
        inbox_email=f"esc-notif-regress-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=created_by,
        is_active=True,
    )
    session.add(client)
    started_at = datetime.now(timezone.utc) - timedelta(hours=4)
    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        assigned_by=assigned_by,
        created_by=created_by,
        title="Escalation notification regression ticket",
        ticket_type=CATEGORY,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=started_at,
    )
    session.add(ticket)
    await session.flush()
    policy = await SLAPolicyRepository(session).get_by_priority(TicketPriority.MEDIUM)
    sla = ResolutionSLA(
        resolution_sla_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        client_id=client.client_id,
        priority=TicketPriority.MEDIUM,
        status=SLAClockStatus.RUNNING,
        started_at=started_at,
        due_at=started_at + timedelta(hours=4),
        active_target_minutes=policy.resolution_target_minutes,
    )
    session.add(sla)
    await session.flush()
    return ticket, sla


def _escalation_service(session) -> EscalationService:
    return EscalationService(
        ticket_escalation_repository=TicketEscalationRepository(session),
        ticket_repository=TicketRepository(session),
        resolution_sla_repository=ResolutionSLARepository(session),
        sla_policy_repository=SLAPolicyRepository(session),
        user_repository=UserRepository(session),
        audit_log_repository=AuditLogRepository(session),
        notification_service=NotificationService(NotificationRepository(session)),
    )


async def _notifications(session, ticket_id):
    result = await session.execute(
        select(Notification).where(Notification.related_entity_id == ticket_id)
    )
    return list(result.scalars().all())


async def _escalate(session, *, assigner_name: str):
    assigner = await _user(session, assigner_name)
    pavana = await _user(session, "Pavana M")
    reporting_manager = await _user(session, "Satish H R")
    creator = await _user(session, "Kamaleshwaran K")
    pavana.reporting_manager_id = reporting_manager.user_id
    await session.flush()

    ticket, sla = await _ticket(
        session, agent_id=pavana.user_id, assigned_by=assigner.user_id, created_by=creator.user_id
    )
    service = _escalation_service(session)
    await service.auto_escalate_if_needed(ticket=ticket, resolution_clock=sla)
    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(ticket.ticket_id)
    assert escalation is not None
    return ticket, escalation, assigner, reporting_manager, service


async def _assert_recipients(session, ticket, escalation, assigner, reporting_manager):
    assert set(escalation.owner_ids) == {str(reporting_manager.user_id), str(assigner.user_id)}
    assert escalation.owner_roles[str(reporting_manager.user_id)] == OWNER_ROLE_REPORTING_MANAGER
    assert escalation.owner_roles[str(assigner.user_id)] == OWNER_ROLE_ASSIGNEE_CHAIN

    rows = await _notifications(session, ticket.ticket_id)
    by_user: dict = {}
    for row in rows:
        by_user.setdefault(row.user_id, []).append(row)
    for owner in (reporting_manager, assigner):
        mine = by_user.get(owner.user_id, [])
        assert len(mine) == 1, f"{owner.name} must be notified exactly once, got {len(mine)}"
        assert mine[0].notification_type == "ESCALATION_CREATED"
    # No user is notified twice for the same event.
    assert all(len(v) == 1 for v in by_user.values())


async def test_team_lead_assigned_manager_and_reporting_manager_are_both_notified(db_session):
    ticket, escalation, tl, reporting_manager, _ = await _escalate(db_session, assigner_name="Yashodha S")
    assert tl.role.name == "Team Lead"
    await _assert_recipients(db_session, ticket, escalation, tl, reporting_manager)


async def test_non_team_lead_assigned_manager_recipients_unchanged(db_session):
    ticket, escalation, am, reporting_manager, _ = await _escalate(
        db_session, assigner_name="Kamaleshwaran K"
    )
    assert am.role.name == "Account Manager"
    await _assert_recipients(db_session, ticket, escalation, am, reporting_manager)


async def test_assignment_scope_rule_does_not_change_escalation_recipients(db_session):
    ticket, escalation, tl, reporting_manager, _ = await _escalate(db_session, assigner_name="Yashodha S")
    audit_repo = AuditLogRepository(db_session)
    chain_before = await build_chain_owner_ids(ticket, audit_repo)
    owners_before = list(escalation.owner_ids)

    # Exercise the new assignment rule as the Team Lead on every Staff
    # member in this category - allowed or rejected, it must not touch
    # escalation recipient state.
    assignment_service = AssignmentService(UserRepository(db_session))
    await assignment_service.get_assignable_groups(tl, CATEGORY)
    await assignment_service.team_lead_staff_ids(tl, [CATEGORY])
    for staff in await UserRepository(db_session).list_active_staff_by_category(CATEGORY):
        try:
            await assignment_service.ensure_team_lead_can_assign(tl, staff, [CATEGORY])
        except Exception:
            pass

    assert await build_chain_owner_ids(ticket, audit_repo) == chain_before
    refreshed = await TicketEscalationRepository(db_session).get_active_by_ticket_id(ticket.ticket_id)
    assert list(refreshed.owner_ids) == owners_before
    # Team Lead is still an owner even if they would not be an eligible
    # assignment TARGET for anyone.
    assert str(tl.user_id) in refreshed.owner_ids
