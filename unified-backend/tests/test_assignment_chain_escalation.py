# test_assignment_chain_escalation.py
#
# End-to-end coverage for the assignment-chain escalation redesign
# (root CLAUDE.md's "SLA & Escalation" section) against the exact real,
# seeded employees the business spec's own worked examples named —
# Kamaleshwaran K (Account Manager), Yashodha S (Team Lead), Pavana M
# (Staff), Satish H R (Account Manager) — rather than synthetic users,
# since the spec's flows A-E are literally about this specific chain.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_escalation_service.py (no separate test database configured for
# this project). The one deliberate, documented exception: Pavana's own
# `reporting_manager_id` is mutated in-session for Flow A (see that
# test's own comment for why) — rolled back like everything else here,
# never committed.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import User

from app.database.session import AsyncSessionLocal, engine
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.enums import (
    OWNER_ROLE_ASSIGNEE_CHAIN,
    OWNER_ROLE_REPORTING_MANAGER,
    ActorRole,
    AuditEntityType,
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
from app.ticketing.services.escalation_service import EscalationService
from app.ticketing.services.interaction_service import InteractionService

CATEGORY = "Payment Posting"  # Yashodha's real seeded category — he's a Team Lead
# (category-scoped by ensure_agent_can_view_ticket), so the test
# ticket's own ticket_type has to match his, not Pavana's ("AR") —
# Kamaleshwaran/Satish (Account Manager, unrestricted) have no such
# constraint either way.


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


async def _get_user_by_name(session, name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .where(User.name == name)
    )
    user = result.unique().scalar_one_or_none()
    if user is None:
        pytest.skip(f"Seeded user {name!r} not found in this database.")
    return user


async def _make_ticket(session, *, agent_id, assigned_by, created_by) -> tuple[Client, Ticket, ResolutionSLA]:
    client = Client(
        client_id=uuid.uuid4(),
        name="Assignment Chain Test Client",
        inbox_email=f"assignment-chain-test-{uuid.uuid4().hex[:8]}@example.com",
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
        title="Assignment chain regression test ticket",
        ticket_type=CATEGORY,
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
        due_at=started_at + timedelta(hours=4),
        active_target_minutes=medium_policy.resolution_target_minutes,
    )
    session.add(resolution_sla)
    await session.flush()
    return client, ticket, resolution_sla


async def _seed_prior_assignment(session, ticket_id, *, new_agent_id, assigned_by) -> None:
    """Real AGENT_TRANSFERRED audit row — see build_chain_owner_ids' own docstring."""

    audit_log = AuditLog(
        entity_type=AuditEntityType.TICKET,
        entity_id=ticket_id,
        event_type=AuditEventType.AGENT_TRANSFERRED,
        actor_id=assigned_by,
        actor_name="Test Fixture",
        actor_role=ActorRole.AGENT,
        old_values={"agent_id": None},
        new_values={"agent_id": str(new_agent_id)},
        ticket_id=ticket_id,
    )
    session.add(audit_log)
    await session.flush()


def _build_escalation_service(session, *, with_notifications: bool = False) -> EscalationService:
    return EscalationService(
        ticket_escalation_repository=TicketEscalationRepository(session),
        ticket_repository=TicketRepository(session),
        resolution_sla_repository=ResolutionSLARepository(session),
        sla_policy_repository=SLAPolicyRepository(session),
        user_repository=UserRepository(session),
        audit_log_repository=AuditLogRepository(session),
        notification_service=(
            NotificationService(NotificationRepository(session)) if with_notifications else None
        ),
    )


def _build_interaction_service(session, escalation_service: EscalationService) -> InteractionService:
    return InteractionService(
        InteractionRepository(session),
        TicketRepository(session),
        UserRepository(session),
        client_repository=ClientRepository(session),
        notification_service=NotificationService(NotificationRepository(session)),
        escalation_service=escalation_service,
    )


async def test_flow_a_direct_assignment_notifies_reporting_manager_and_assigner(db_session):
    """
    Flow A: Kamaleshwaran assigns directly to Pavana. Pavana's real
    reporting_manager_id is Yashodha in this database (Flow B's own
    chain) — overridden to Satish here, in-session only, so this test
    exercises the spec's literal "reporting manager != assigner"
    scenario rather than the coincidental dedup Flow B is about.
    """

    kamaleshwaran = await _get_user_by_name(db_session, "Kamaleshwaran K")
    pavana = await _get_user_by_name(db_session, "Pavana M")
    satish = await _get_user_by_name(db_session, "Satish H R")

    pavana.reporting_manager_id = satish.user_id
    await db_session.flush()

    _client, ticket, resolution_sla = await _make_ticket(
        db_session,
        agent_id=pavana.user_id,
        assigned_by=kamaleshwaran.user_id,
        created_by=kamaleshwaran.user_id,
    )

    # Auto-triggered, exactly as a real Resolution SLA breach would
    # (SLASweepService.run_sweep) — manual_escalate's own "caller must
    # be the ticket's current owner" rule is orthogonal to this feature
    # and deliberately untouched, so it isn't the right trigger for a
    # scenario about who's notified, not who clicked the button.
    service = _build_escalation_service(db_session)
    await service.auto_escalate_if_needed(ticket=ticket, resolution_clock=resolution_sla)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    assert escalation.level == EscalationLevel.ASSIGNMENT_CHAIN
    assert set(escalation.owner_ids) == {str(satish.user_id), str(kamaleshwaran.user_id)}
    assert escalation.owner_roles[str(satish.user_id)] == OWNER_ROLE_REPORTING_MANAGER
    assert escalation.owner_roles[str(kamaleshwaran.user_id)] == OWNER_ROLE_ASSIGNEE_CHAIN

    # Both get Acknowledge + Assign (owner_ids membership is the sole
    # ack authorization criterion — unchanged by this redesign).
    await service.acknowledge(ticket.ticket_id, satish)
    reloaded = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert reloaded.status == EscalationStatus.ACKNOWLEDGED
    assert reloaded.acknowledged_by == satish.user_id


async def test_flow_e_reporting_manager_cannot_assign_to_self(db_session):
    """
    Flow E: Satish (Reporting Manager, not the ticket assignee) must
    not be able to use "Assign to Myself" — enforced both in the
    candidate picker (me=None) and directly on the backend action.
    """

    kamaleshwaran = await _get_user_by_name(db_session, "Kamaleshwaran K")
    pavana = await _get_user_by_name(db_session, "Pavana M")
    satish = await _get_user_by_name(db_session, "Satish H R")

    pavana.reporting_manager_id = satish.user_id
    await db_session.flush()

    _client, ticket, resolution_sla = await _make_ticket(
        db_session,
        agent_id=pavana.user_id,
        assigned_by=kamaleshwaran.user_id,
        created_by=kamaleshwaran.user_id,
    )

    escalation_service = _build_escalation_service(db_session)
    await escalation_service.auto_escalate_if_needed(ticket=ticket, resolution_clock=resolution_sla)

    satish.permissions = ["ticket:transfer"]
    candidates = await escalation_service.get_acknowledge_candidates(ticket.ticket_id, satish)
    assert candidates.me is None

    interaction_service = _build_interaction_service(db_session, escalation_service)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await interaction_service.acknowledge_and_assign_escalation(
            ticket.ticket_id, satish.user_id, satish
        )
    assert exc_info.value.status_code == 403

    # Kamaleshwaran (Assigned By, not a Reporting Manager) has no such
    # restriction — self-assign stays available to him.
    kamaleshwaran.permissions = ["ticket:transfer"]
    kamaleshwaran_candidates = await escalation_service.get_acknowledge_candidates(
        ticket.ticket_id, kamaleshwaran
    )
    assert kamaleshwaran_candidates.me is not None
    assert kamaleshwaran_candidates.me.user_id == kamaleshwaran.user_id


async def test_flow_b_first_target_is_yashodha_then_kamaleshwaran_on_timeout(db_session):
    """
    Flow B: Kamaleshwaran -> Yashodha (Team Lead) -> Pavana (Staff).
    First escalation target is Yashodha alone (he's both the assigner
    AND Pavana's real reporting_manager_id in this database, so the
    two dedupe to one owner). If he doesn't acknowledge before the ack
    window lapses, it advances to Kamaleshwaran, who assigned him the
    ticket (Flow D: advances to the next person in the chain).
    """

    kamaleshwaran = await _get_user_by_name(db_session, "Kamaleshwaran K")
    yashodha = await _get_user_by_name(db_session, "Yashodha S")
    pavana = await _get_user_by_name(db_session, "Pavana M")
    assert pavana.reporting_manager_id == yashodha.user_id  # the real, seeded relationship

    _client, ticket, resolution_sla = await _make_ticket(
        db_session,
        agent_id=pavana.user_id,
        assigned_by=yashodha.user_id,
        created_by=kamaleshwaran.user_id,
    )
    await _seed_prior_assignment(
        db_session, ticket.ticket_id, new_agent_id=yashodha.user_id, assigned_by=kamaleshwaran.user_id
    )

    service = _build_escalation_service(db_session)
    await service.auto_escalate_if_needed(ticket=ticket, resolution_clock=resolution_sla)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    # First target = Yashodha alone (dedup with his own reporting-manager slot).
    assert escalation.owner_ids == [str(yashodha.user_id)]
    assert escalation.owner_roles[str(yashodha.user_id)] == OWNER_ROLE_ASSIGNEE_CHAIN

    # Flow D: no acknowledgment before the ack window lapses -> advances
    # to the next person in the assignment chain (Kamaleshwaran).
    escalation.ack_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()
    await service.evaluate_overdue(now=datetime.now(timezone.utc))

    advanced = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert advanced.escalation_id == escalation.escalation_id
    assert advanced.chain_position == 1
    assert advanced.owner_ids == [str(kamaleshwaran.user_id)]
    assert advanced.owner_roles[str(kamaleshwaran.user_id)] == OWNER_ROLE_ASSIGNEE_CHAIN
    assert advanced.status == EscalationStatus.ACTIVE
    assert advanced.acknowledged_at is None


async def test_flow_c_acknowledgement_before_expiry_stops_escalation(db_session):
    """Flow C: acknowledging before the ack window expires stops the ladder."""

    kamaleshwaran = await _get_user_by_name(db_session, "Kamaleshwaran K")
    yashodha = await _get_user_by_name(db_session, "Yashodha S")
    pavana = await _get_user_by_name(db_session, "Pavana M")

    _client, ticket, resolution_sla = await _make_ticket(
        db_session,
        agent_id=pavana.user_id,
        assigned_by=yashodha.user_id,
        created_by=kamaleshwaran.user_id,
    )
    await _seed_prior_assignment(
        db_session, ticket.ticket_id, new_agent_id=yashodha.user_id, assigned_by=kamaleshwaran.user_id
    )

    service = _build_escalation_service(db_session)
    await service.auto_escalate_if_needed(ticket=ticket, resolution_clock=resolution_sla)

    await service.acknowledge(ticket.ticket_id, yashodha)

    escalation = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation.status == EscalationStatus.ACKNOWLEDGED

    # Even with the ack window artificially expired, evaluate_overdue
    # only ever considers still-ACTIVE escalations — an already-
    # acknowledged one is never advanced.
    escalation.ack_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()
    await service.evaluate_overdue(now=datetime.now(timezone.utc))

    unchanged = await service.ticket_escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert unchanged.chain_position == 0
    assert unchanged.owner_ids == [str(yashodha.user_id)]
    assert unchanged.status == EscalationStatus.ACKNOWLEDGED
