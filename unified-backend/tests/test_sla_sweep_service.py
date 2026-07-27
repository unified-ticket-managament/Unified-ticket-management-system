# test_sla_sweep_service.py
#
# End-to-end regression coverage for SLASweepService.run_sweep's
# Resolution-clock notification routing/timing — the "current owner
# must always get the right milestone at the right time, based on
# live ownership, never a stale or duplicate one" guarantee described
# in root CLAUDE.md's "SLA & Escalation" section and enforced by
# sla_escalation_rules.resolve_current_owner / the
# SLABreachNotification idempotency ledger.
#
# Two real bugs were found and fixed alongside this test file:
#
# 1. auto_escalate_if_needed used to be triggered off "BREACHED (100%)
#    OR ESCALATED (150%)" — meaning the very first tick a clock crossed
#    BREACHED, an escalation was created in the same tick, which
#    immediately flips resolve_current_owner's escalation-owner-takes-
#    priority branch on and silently redirects that same tick's
#    Breached notification away from the ticket's actual current owner
#    to the escalation's owner instead. Fixed by gating escalation
#    creation on ESCALATED (150%) only — see
#    test_half_at_risk_breached_all_go_to_current_owner_then_escalation_
#    only_at_150_percent below, which is the regression test for
#    exactly this.
# 2. That same auto-escalation-creation step read the ticket from a
#    batch snapshot taken at the very top of the sweep tick, rather
#    than re-fetching it — a claim/transfer landing on the ticket
#    between that snapshot and the (potentially much later, per-ticket-
#    round-trip-bound) escalation-creation step could feed a stale
#    agent_id into _resolve_starting_level, picking the wrong starting
#    escalation level. Fixed by re-fetching the ticket immediately
#    before creating the escalation — see
#    test_escalation_starting_level_reflects_ownership_as_of_escalation_
#    time_not_the_sweeps_initial_snapshot below.
# 3. Fix 1 above (BREACHED-vs-ESCALATED gating) assumed a clock only
#    ever crosses one threshold per sweep tick. A clock discovered
#    already past 150% (a delayed sweep, or a short SLA target relative
#    to the sweep interval) has HALF_ELAPSED/AT_RISK/BREACHED/ESCALATED
#    all newly-crossed together in one tick — auto-escalation used to
#    execute inline, in the same per-clock classification loop, so the
#    newly-created escalation could still pre-empt that SAME tick's own
#    HALF_ELAPSED/AT_RISK/BREACHED notifications via the (not
#    threshold-scoped) escalations_by_ticket_id refresh that runs before
#    the notify loop — a narrower recurrence of the exact defect fix 1
#    already closed for the one-threshold-per-tick case. Fixed by
#    deferring auto-escalation *execution* to a dedicated pass strictly
#    after the notify loop (still *recorded*, via
#    pending_auto_escalations, during classification) — see
#    test_all_thresholds_crossed_in_one_tick_still_route_to_pre_escalation_owner,
#    test_escalation_failure_does_not_block_notifications_and_retries_cleanly,
#    and test_full_stage_lifecycle_staff_then_accepted_team_lead_never_cross_contaminate
#    below.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_escalation_service.py. list_active_for_sweep() has no filter of
# its own beyond clock status, so a full run_sweep() call here also
# processes every other real active clock already in the shared dev
# database (same accepted trade-off test_escalation_service.py's own
# evaluate_overdue tests already document) — every assertion below is
# scoped to this test's own ticket/notifications, never to aggregate
# sweep counts, so that pre-existing data can't affect pass/fail.

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.notifications.models import Notification
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService, NotificationType
from app.ticketing.enums import EscalationLevel, TicketPriority, SLAClockStatus
from app.ticketing.models.client import Client
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.first_response_sla_repository import (
    FirstResponseSLARepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_breach_notification_repository import (
    SLABreachNotificationRepository,
)
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_escalation_repository import (
    TicketEscalationRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket import TicketUpdate
from app.ticketing.services.sla_sweep_service import SLASweepService

# "Eligibility" (used by test_escalation_service.py/test_transfer_agent_
# ownership.py) only has 1 seeded active Staff member in this dev
# database — not enough for this file's two-distinct-owner reassignment
# scenarios (Examples 3/4). "Claims" has 2 Staff + 1 Team Lead seeded.
TEAM_LEAD_CATEGORY = "Claims"


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
    for user in result.unique().scalars().all():
        if user.category is not None and user.category.category_name.value == TEAM_LEAD_CATEGORY:
            return user
    pytest.skip(f"No active seeded Team Lead found for category {TEAM_LEAD_CATEGORY!r}.")


async def _get_staff_members(session, *, count: int) -> list[User]:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    matches = [
        u
        for u in result.unique().scalars().all()
        if u.category is not None and u.category.category_name.value == TEAM_LEAD_CATEGORY
    ]
    if len(matches) < count:
        pytest.skip(
            f"Need {count} active seeded Staff in category {TEAM_LEAD_CATEGORY!r}, "
            f"found {len(matches)}."
        )
    return matches[:count]


async def _make_ticket_with_resolution_clock(
    session,
    *,
    agent_id,
    fraction: float,
    priority: TicketPriority = TicketPriority.MEDIUM,
) -> tuple[Client, Ticket, ResolutionSLA]:
    """
    A real Client + Ticket + running Resolution SLA clock whose due_at
    is computed to sit at exactly `fraction` of its target elapsed, as
    of "now" — mirrors compute_elapsed_fraction's own formula in
    reverse. `fraction` > 1.0 is valid (simulates a clock already past
    BREACHED/ESCALATED, e.g. to model a delayed first sweep tick).
    """

    team_lead = await _get_team_lead(session)

    client = Client(
        client_id=uuid.uuid4(),
        name="SLA Sweep Test Client",
        inbox_email=f"sla-sweep-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        is_active=True,
    )
    session.add(client)

    now = datetime.now(timezone.utc)
    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="SLA sweep regression test ticket",
        ticket_type=TEAM_LEAD_CATEGORY,
        current_status="OPEN",
        current_priority=priority,
        created_at=now - timedelta(hours=1),
    )
    session.add(ticket)
    await session.flush()

    policy = await SLAPolicyRepository(session).get_by_priority(priority)
    target_seconds = policy.resolution_target_minutes * 60
    remaining_seconds = (1.0 - fraction) * target_seconds
    due_at = now + timedelta(seconds=remaining_seconds)

    resolution_sla = ResolutionSLA(
        resolution_sla_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        client_id=client.client_id,
        priority=priority,
        status=SLAClockStatus.RUNNING,
        started_at=now - timedelta(hours=1),
        due_at=due_at,
        active_target_minutes=policy.resolution_target_minutes,
    )
    session.add(resolution_sla)
    await session.flush()

    return client, ticket, resolution_sla


def _build_sweep_service(session) -> SLASweepService:
    return SLASweepService(
        sla_policy_repository=SLAPolicyRepository(session),
        first_response_sla_repository=FirstResponseSLARepository(session),
        resolution_sla_repository=ResolutionSLARepository(session),
        sla_breach_notification_repository=SLABreachNotificationRepository(session),
        ticket_repository=TicketRepository(session),
        client_repository=ClientRepository(session),
        user_repository=UserRepository(session),
        notification_service=NotificationService(NotificationRepository(session)),
        interaction_repository=InteractionRepository(session),
    )


async def _set_fraction(session, resolution_sla, *, fraction: float) -> None:
    """Moves an existing clock's due_at to sit at `fraction` elapsed, as of now."""

    now = datetime.now(timezone.utc)
    remaining_seconds = (1.0 - fraction) * resolution_sla.active_target_minutes * 60
    resolution_sla.due_at = now + timedelta(seconds=remaining_seconds)
    await session.flush()


async def _notifications_for(session, *, user_id, ticket_id) -> list[Notification]:
    result = await session.execute(
        select(Notification)
        .where(Notification.user_id == user_id, Notification.related_entity_id == ticket_id)
        .order_by(Notification.created_at.asc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------
# Before escalation: current owner gets each milestone once, on time
# ---------------------------------------------------------------------


async def test_half_at_risk_breached_all_go_to_current_owner_then_escalation_only_at_150_percent(
    db_session,
):
    """
    Regression test for fix 1 (see module docstring): Half-Elapsed,
    At-Risk, and Breached must all route to the assigned Staff member
    — including Breached at exactly 100%, which used to be silently
    redirected to the Team Lead in the same tick an escalation was
    (incorrectly) created. The Team Lead must receive nothing at all
    until the clock actually reaches ESCALATED (150%), at which point
    they get exactly one Auto-Escalated notification and the escalation
    only then exists.
    """

    team_lead = await _get_team_lead(db_session)
    (staff,) = await _get_staff_members(db_session, count=1)
    _client, ticket, resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=staff.user_id, fraction=0.55
    )
    service = _build_sweep_service(db_session)

    await service.run_sweep()
    staff_notifications = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    team_lead_notifications = await _notifications_for(
        db_session, user_id=team_lead.user_id, ticket_id=ticket.ticket_id
    )
    assert [n.notification_type for n in staff_notifications] == [NotificationType.SLA_HALF_ELAPSED]
    assert team_lead_notifications == []

    await _set_fraction(db_session, resolution_sla, fraction=0.85)
    await service.run_sweep()
    staff_notifications = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    assert [n.notification_type for n in staff_notifications] == [
        NotificationType.SLA_HALF_ELAPSED,
        NotificationType.SLA_AT_RISK,
    ]
    assert (
        await _notifications_for(db_session, user_id=team_lead.user_id, ticket_id=ticket.ticket_id)
        == []
    )

    # BREACHED (100%) — the exact crossing that used to also trigger
    # escalation creation, redirecting this notification to the Team
    # Lead. Must still go to Staff, and no escalation may exist yet.
    await _set_fraction(db_session, resolution_sla, fraction=1.05)
    await service.run_sweep()
    staff_notifications = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    assert [n.notification_type for n in staff_notifications] == [
        NotificationType.SLA_HALF_ELAPSED,
        NotificationType.SLA_AT_RISK,
        NotificationType.SLA_BREACHED,
    ]
    assert (
        await _notifications_for(db_session, user_id=team_lead.user_id, ticket_id=ticket.ticket_id)
        == []
    )
    escalation_repo = TicketEscalationRepository(db_session)
    assert await escalation_repo.get_active_by_ticket_id(ticket.ticket_id) is None

    # ESCALATED (150%) — escalation is created now, Team Lead gets
    # exactly one Auto-Escalated notification, Staff gets nothing more.
    await _set_fraction(db_session, resolution_sla, fraction=1.55)
    await service.run_sweep()
    staff_notifications = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    assert [n.notification_type for n in staff_notifications] == [
        NotificationType.SLA_HALF_ELAPSED,
        NotificationType.SLA_AT_RISK,
        NotificationType.SLA_BREACHED,
    ]
    team_lead_notifications = await _notifications_for(
        db_session, user_id=team_lead.user_id, ticket_id=ticket.ticket_id
    )
    assert [n.notification_type for n in team_lead_notifications] == [
        NotificationType.ESCALATION_CREATED
    ]
    escalation = await escalation_repo.get_active_by_ticket_id(ticket.ticket_id)
    assert escalation is not None
    assert escalation.level == EscalationLevel.TEAM_LEAD


async def test_milestone_not_sent_before_its_own_threshold(db_session):
    (staff,) = await _get_staff_members(db_session, count=1)
    _client, ticket, _resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=staff.user_id, fraction=0.3
    )
    service = _build_sweep_service(db_session)

    await service.run_sweep()

    assert (
        await _notifications_for(db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id)
        == []
    )


# ---------------------------------------------------------------------
# Reassignment — Examples 3 & 4
# ---------------------------------------------------------------------


async def test_reassignment_before_milestone_routes_to_new_owner_only(db_session):
    """Example 3: reassigned before 50% — only the new owner gets it, never the old one."""

    staff_a, staff_b = await _get_staff_members(db_session, count=2)
    _client, ticket, resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=staff_a.user_id, fraction=0.3
    )
    service = _build_sweep_service(db_session)
    await service.run_sweep()  # below threshold — no-op, but exercises "runs before reassignment"

    ticket_repository = TicketRepository(db_session)
    await ticket_repository.update(ticket, TicketUpdate(agent_id=staff_b.user_id))

    await _set_fraction(db_session, resolution_sla, fraction=0.55)
    await service.run_sweep()

    assert (
        await _notifications_for(db_session, user_id=staff_a.user_id, ticket_id=ticket.ticket_id)
        == []
    )
    new_owner_notifications = await _notifications_for(
        db_session, user_id=staff_b.user_id, ticket_id=ticket.ticket_id
    )
    assert [n.notification_type for n in new_owner_notifications] == [
        NotificationType.SLA_HALF_ELAPSED
    ]


async def test_reassignment_after_milestone_keeps_old_notification_and_routes_future_ones_to_new_owner(
    db_session,
):
    """
    Example 4: Staff A gets Half-Elapsed, then the ticket is reassigned
    to Staff B before At-Risk. Staff A must keep the one notification
    already sent and never receive another; Staff B must receive
    At-Risk and Breached going forward, with no duplicate/historical
    Half-Elapsed of their own.
    """

    staff_a, staff_b = await _get_staff_members(db_session, count=2)
    _client, ticket, resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=staff_a.user_id, fraction=0.55
    )
    service = _build_sweep_service(db_session)
    await service.run_sweep()

    assert [
        n.notification_type
        for n in await _notifications_for(
            db_session, user_id=staff_a.user_id, ticket_id=ticket.ticket_id
        )
    ] == [NotificationType.SLA_HALF_ELAPSED]

    ticket_repository = TicketRepository(db_session)
    await ticket_repository.update(ticket, TicketUpdate(agent_id=staff_b.user_id))

    await _set_fraction(db_session, resolution_sla, fraction=0.85)
    await service.run_sweep()

    # Staff A: still exactly the one, already-valid Half-Elapsed notification.
    assert [
        n.notification_type
        for n in await _notifications_for(
            db_session, user_id=staff_a.user_id, ticket_id=ticket.ticket_id
        )
    ] == [NotificationType.SLA_HALF_ELAPSED]
    # Staff B: only At-Risk — no duplicate/historical Half-Elapsed.
    assert [
        n.notification_type
        for n in await _notifications_for(
            db_session, user_id=staff_b.user_id, ticket_id=ticket.ticket_id
        )
    ] == [NotificationType.SLA_AT_RISK]

    await _set_fraction(db_session, resolution_sla, fraction=1.05)
    await service.run_sweep()

    assert [
        n.notification_type
        for n in await _notifications_for(
            db_session, user_id=staff_a.user_id, ticket_id=ticket.ticket_id
        )
    ] == [NotificationType.SLA_HALF_ELAPSED]
    assert [
        n.notification_type
        for n in await _notifications_for(
            db_session, user_id=staff_b.user_id, ticket_id=ticket.ticket_id
        )
    ] == [NotificationType.SLA_AT_RISK, NotificationType.SLA_BREACHED]


# ---------------------------------------------------------------------
# Example 5: delayed scheduler
# ---------------------------------------------------------------------


async def test_delayed_scheduler_fires_every_genuinely_due_milestone_once_not_duplicated(
    db_session,
):
    """
    A clock discovered for the very first time already past 100%
    (simulating a long-delayed first sweep tick, or a long-delayed
    scheduler catching up) must fire every threshold it has genuinely
    already crossed — once each, not zero, not duplicated — to the
    current owner. Re-running the sweep immediately after must not
    resend any of them.
    """

    (staff,) = await _get_staff_members(db_session, count=1)
    _client, ticket, _resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=staff.user_id, fraction=1.05
    )
    service = _build_sweep_service(db_session)

    await service.run_sweep()
    first_pass = [
        n.notification_type
        for n in await _notifications_for(
            db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
        )
    ]
    # All three genuinely-crossed thresholds fire together in this one
    # tick, each exactly once — but try_record_many reports them as a
    # set, so the sweep's own notify loop (and therefore insertion
    # order) is NOT guaranteed to match the HALF_ELAPSED/AT_RISK/
    # BREACHED ladder order. Compare as a multiset, not an ordered list.
    assert sorted(first_pass) == sorted(
        [
            NotificationType.SLA_HALF_ELAPSED,
            NotificationType.SLA_AT_RISK,
            NotificationType.SLA_BREACHED,
        ]
    )

    await service.run_sweep()
    second_pass = [
        n.notification_type
        for n in await _notifications_for(
            db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
        )
    ]
    assert sorted(second_pass) == sorted(first_pass)


# ---------------------------------------------------------------------
# Mid-tick ownership staleness — regression test for fix 2
# ---------------------------------------------------------------------


async def test_escalation_starting_level_reflects_ownership_as_of_escalation_time_not_the_sweeps_initial_snapshot(
    db_session, monkeypatch
):
    """
    Regression test for fix 2 (see module docstring). Simulates a
    transfer_agent call from a *different* request landing on this
    ticket right after run_sweep's own initial batch snapshot of
    tickets_by_id is taken, but before its (potentially much later)
    auto-escalation-creation step reads ticket.agent_id. The DB row is
    updated via a raw, ORM-identity-map-bypassing UPDATE — the same
    shape a concurrent session's commit would take — so the objects
    already returned by the sweep's initial snapshot query keep
    reflecting the pre-reassignment state exactly as they would in a
    real race, and only a genuine re-fetch immediately before escalating
    would observe the change.

    The ticket starts at CRITICAL priority already (simulating a
    *re*-escalation, after a prior escalation cycle closed) rather than
    the default MEDIUM — deliberately, not incidentally: EscalationService.
    _set_ticket_priority_to_critical (the first thing _create_escalation
    does) itself calls session.refresh(ticket) as a side effect of its
    own update(), which would otherwise ALSO happen to observe the
    reassignment and mask whether this fix's own re-fetch is doing
    anything — confirmed empirically while writing this test: with the
    ticket starting at MEDIUM, the test passed identically whether the
    fix's explicit re-fetch was present or reverted, because that
    incidental refresh alone was already enough. It only no-ops (skips
    the refresh) when the ticket is already CRITICAL, which is exactly
    the gap this fix's own explicit, unconditional re-fetch closes.

    Ticket starts unclaimed (agent_id=None); the simulated concurrent
    reassignment hands it to the Team Lead themselves. If the sweep
    used its stale initial snapshot, _resolve_starting_level would see
    agent_id=None and start the escalation at TEAM_LEAD — re-notifying
    the very Team Lead who just took the ticket. With the fix, it sees
    the Team Lead now owns it and correctly skips to MANAGER instead.
    """

    team_lead = await _get_team_lead(db_session)
    _client, ticket, _resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=None, fraction=1.55, priority=TicketPriority.CRITICAL
    )
    service = _build_sweep_service(db_session)

    ticket_repository = service.ticket_repository
    original_list_by_ids = ticket_repository.list_by_ids

    async def _list_by_ids_then_simulate_concurrent_reassignment(ticket_ids, **kwargs):
        result = await original_list_by_ids(ticket_ids, **kwargs)
        if ticket.ticket_id in ticket_ids:
            # synchronize_session=False is required to genuinely
            # simulate a concurrent session's commit — SQLAlchemy 2.0's
            # ORM-enabled bulk UPDATE otherwise auto-synchronizes any
            # already-loaded, matching in-memory object by default
            # (synchronize_session="auto"), which would silently patch
            # up the very staleness this test exists to simulate and
            # make it pass regardless of whether the real fix is
            # present. With this option, the DB row changes but
            # `ticket` (already loaded above) is deliberately left
            # exactly as stale as a genuinely different session's
            # commit would leave it.
            await db_session.execute(
                sa_update(Ticket)
                .where(Ticket.ticket_id == ticket.ticket_id)
                .values(agent_id=team_lead.user_id)
                .execution_options(synchronize_session=False)
            )
        return result

    monkeypatch.setattr(
        ticket_repository, "list_by_ids", _list_by_ids_then_simulate_concurrent_reassignment
    )

    await service.run_sweep()

    escalation = await TicketEscalationRepository(db_session).get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    assert escalation.level == EscalationLevel.MANAGER


# ---------------------------------------------------------------------
# Regression test: a threshold whose recipient resolution comes back
# empty must never be silently, permanently lost — see
# SLASweepService._notify_resolution's own docstring. The idempotency
# ledger row is still recorded either way (unchanged, intentional — see
# SLABreachNotificationRepository.try_record_many's own docstring), but
# this must now be logged and counted, not invisible.
# ---------------------------------------------------------------------


async def test_empty_recipients_are_logged_and_counted_not_silently_lost(
    db_session, caplog
):
    """
    An unclaimed ticket whose category resolves (for this call) to no
    Team Lead/staff produces zero recipients. Uses a hand-seeded,
    deliberately-empty category_cache entry (which _get_category_team
    checks before ever querying the database) rather than depending on
    the real dev database happening to have a Team-Lead-less category —
    this makes the scenario deterministic regardless of seed data.
    """

    _client, ticket, resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=None, fraction=1.0
    )

    service = _build_sweep_service(db_session)
    global_inbox_ids = await service._global_inbox_user_ids()
    category_cache = {ticket.ticket_type: ([], [])}

    with caplog.at_level(
        logging.WARNING, logger="app.ticketing.services.sla_sweep_service"
    ):
        sent, recipients_were_empty = await service._notify_resolution(
            resolution_sla,
            "BREACHED",
            global_inbox_ids,
            category_cache,
            {ticket.ticket_id: ticket},
            {},
            {},
            {},
        )

    assert sent is False
    assert recipients_were_empty is True
    assert "SLA notification skipped" in caplog.text
    assert str(ticket.ticket_id) in caplog.text

    # This call alone must not have created a Notification row either,
    # since there was nobody to notify — the idempotency ledger write
    # itself is out of scope here (that's run_sweep's own
    # try_record_many, called before _notify_resolution ever runs).
    result = await db_session.execute(
        select(Notification).where(Notification.related_entity_id == ticket.ticket_id)
    )
    assert result.scalars().all() == []


async def test_missing_ticket_is_logged_and_counted_not_silently_lost(
    db_session, caplog
):
    """
    Sibling regression test for the OTHER silent-loss branch: a clock
    whose ticket isn't present in the batch-prefetched tickets_by_id
    dict at all (e.g. a genuinely deleted ticket, or a prefetch bug) —
    must also log and count, not just return False unnoticed.
    """

    _client, ticket, resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=None, fraction=1.0
    )

    service = _build_sweep_service(db_session)
    global_inbox_ids = await service._global_inbox_user_ids()

    with caplog.at_level(
        logging.WARNING, logger="app.ticketing.services.sla_sweep_service"
    ):
        sent, recipients_were_empty = await service._notify_resolution(
            resolution_sla,
            "BREACHED",
            global_inbox_ids,
            {},
            {},  # tickets_by_id deliberately empty — ticket "missing"
            {},
            {},
            {},
        )

    assert sent is False
    assert recipients_were_empty is True
    assert "SLA notification skipped" in caplog.text
    assert str(resolution_sla.resolution_sla_id) in caplog.text


# ---------------------------------------------------------------------
# Regression tests for fix 3 (see module docstring): deferring
# auto-escalation *execution* to strictly after the notify loop, so a
# same-tick pileup of thresholds can never have its own escalation
# pre-empt its own earlier-stage notifications.
# ---------------------------------------------------------------------


async def test_all_thresholds_crossed_in_one_tick_still_route_to_pre_escalation_owner(
    db_session,
):
    """
    A clock discovered already past 150% elapsed (e.g. a delayed sweep,
    or a short SLA target relative to the sweep interval) has
    HALF_ELAPSED/AT_RISK/BREACHED/ESCALATED all newly-crossed in a
    single run_sweep() call — unlike the multi-tick scenario above,
    where each threshold is recorded on its own separate tick. Auto-
    escalation creation must not pre-empt this same tick's own
    Half-Elapsed/At-Risk/Breached notifications: all three must still
    reach the pre-escalation Staff owner, never the freshly-created
    Team Lead escalation. Assertions use set comparison, not list order
    — newly_recorded is an unordered set, so iteration order across the
    four thresholds isn't guaranteed.
    """

    team_lead = await _get_team_lead(db_session)
    (staff,) = await _get_staff_members(db_session, count=1)
    _client, ticket, _resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=staff.user_id, fraction=1.55
    )
    service = _build_sweep_service(db_session)

    await service.run_sweep()

    staff_notifications = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    assert {n.notification_type for n in staff_notifications} == {
        NotificationType.SLA_HALF_ELAPSED,
        NotificationType.SLA_AT_RISK,
        NotificationType.SLA_BREACHED,
    }
    assert len(staff_notifications) == 3

    team_lead_notifications = await _notifications_for(
        db_session, user_id=team_lead.user_id, ticket_id=ticket.ticket_id
    )
    assert [n.notification_type for n in team_lead_notifications] == [
        NotificationType.ESCALATION_CREATED
    ]

    escalation = await TicketEscalationRepository(db_session).get_active_by_ticket_id(
        ticket.ticket_id
    )
    assert escalation is not None
    assert escalation.level == EscalationLevel.TEAM_LEAD


async def test_escalation_failure_does_not_block_notifications_and_retries_cleanly(
    db_session, monkeypatch
):
    """
    If auto-escalation *execution* fails (simulating e.g. a transient DB
    error) on a tick that also has newly-crossed HALF_ELAPSED/AT_RISK/
    BREACHED for the same ticket, those notifications must already have
    succeeded — escalation now runs strictly after the notify loop, so
    a failure there cannot roll back or block what already committed.
    The next sweep tick must retry only the escalation; the
    already-recorded thresholds must not be re-notified.
    """

    team_lead = await _get_team_lead(db_session)
    (staff,) = await _get_staff_members(db_session, count=1)
    _client, ticket, _resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=staff.user_id, fraction=1.55
    )
    service = _build_sweep_service(db_session)

    original_auto_escalate = service.escalation_service.auto_escalate_if_needed

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated auto-escalation failure")

    monkeypatch.setattr(service.escalation_service, "auto_escalate_if_needed", _boom)

    result = await service.run_sweep()

    staff_notifications = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    assert {n.notification_type for n in staff_notifications} == {
        NotificationType.SLA_HALF_ELAPSED,
        NotificationType.SLA_AT_RISK,
        NotificationType.SLA_BREACHED,
    }
    assert result.errors >= 1

    escalation_repo = TicketEscalationRepository(db_session)
    assert await escalation_repo.get_active_by_ticket_id(ticket.ticket_id) is None

    # Un-patch and retry — escalation should now succeed, and Staff's
    # already-recorded thresholds must not be re-notified.
    monkeypatch.setattr(
        service.escalation_service, "auto_escalate_if_needed", original_auto_escalate
    )
    await service.run_sweep()

    staff_notifications_after = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    assert len(staff_notifications_after) == len(staff_notifications)

    escalation = await escalation_repo.get_active_by_ticket_id(ticket.ticket_id)
    assert escalation is not None
    assert escalation.level == EscalationLevel.TEAM_LEAD

    team_lead_notifications = await _notifications_for(
        db_session, user_id=team_lead.user_id, ticket_id=ticket.ticket_id
    )
    assert [n.notification_type for n in team_lead_notifications] == [
        NotificationType.ESCALATION_CREATED
    ]


async def test_full_stage_lifecycle_staff_then_accepted_team_lead_never_cross_contaminate(
    db_session,
):
    """
    End-to-end lifecycle: Staff owns the ticket through its own three
    milestones, the ticket auto-escalates to Team Lead, Team Lead takes
    over and accepts (acknowledge + confirm_assignment), and their own
    handling-stage cycle then produces its own three milestones. Every
    notification must belong to the SLA stage that actually generated
    it — Staff's set must never gain a post-escalation entry, and Team
    Lead's set must never contain Staff's stage-1 entries. No duplicates
    anywhere.
    """

    team_lead = await _get_team_lead(db_session)
    (staff,) = await _get_staff_members(db_session, count=1)
    _client, ticket, resolution_sla = await _make_ticket_with_resolution_clock(
        db_session, agent_id=staff.user_id, fraction=0.55
    )
    service = _build_sweep_service(db_session)

    # Stage 1 (Staff) — one milestone per tick.
    await service.run_sweep()
    await _set_fraction(db_session, resolution_sla, fraction=0.85)
    await service.run_sweep()
    await _set_fraction(db_session, resolution_sla, fraction=1.05)
    await service.run_sweep()

    staff_notifications = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    assert len(staff_notifications) == 3
    assert {n.notification_type for n in staff_notifications} == {
        NotificationType.SLA_HALF_ELAPSED,
        NotificationType.SLA_AT_RISK,
        NotificationType.SLA_BREACHED,
    }

    # Auto-escalate to Team Lead.
    await _set_fraction(db_session, resolution_sla, fraction=1.55)
    await service.run_sweep()

    escalation_repo = TicketEscalationRepository(db_session)
    escalation = await escalation_repo.get_active_by_ticket_id(ticket.ticket_id)
    assert escalation is not None
    assert escalation.level == EscalationLevel.TEAM_LEAD

    # Staff must still show exactly the same 3 — nothing leaked in from
    # the escalation crossing itself.
    staff_notifications = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    assert len(staff_notifications) == 3
    assert {n.notification_type for n in staff_notifications} == {
        NotificationType.SLA_HALF_ELAPSED,
        NotificationType.SLA_AT_RISK,
        NotificationType.SLA_BREACHED,
    }

    # Team Lead takes over as the real assignee (mirrors what
    # InteractionService.transfer_agent's own agent_id reassignment
    # would do — done directly here since this file only exercises
    # SLASweepService/EscalationService, not the full interaction
    # layer) and then accepts: acknowledge + confirm_assignment ("keep
    # current assignee," now Team Lead) — this is what actually starts
    # their own handling-stage cycle and reshifts the Resolution SLA
    # clock to a fresh target (EscalationService._complete_acceptance).
    ticket_repo = TicketRepository(db_session)
    await ticket_repo.update(ticket, TicketUpdate(agent_id=team_lead.user_id))
    await service.escalation_service.acknowledge(ticket.ticket_id, team_lead)
    await service.escalation_service.confirm_assignment(ticket.ticket_id, team_lead)

    resolution_sla_repo = ResolutionSLARepository(db_session)
    reloaded_clock = await resolution_sla_repo.get_by_ticket_id(ticket.ticket_id)
    assert reloaded_clock.escalation_cycle == 1

    # Stage 2 (Team Lead's own new cycle) — their own
    # Half-Elapsed/At-Risk/Breached, against the reshifted target.
    await _set_fraction(db_session, reloaded_clock, fraction=0.55)
    await service.run_sweep()
    await _set_fraction(db_session, reloaded_clock, fraction=0.85)
    await service.run_sweep()
    await _set_fraction(db_session, reloaded_clock, fraction=1.05)
    await service.run_sweep()

    # Final assertions: Staff unchanged; Team Lead has exactly their
    # own escalation-created notice plus their own 3 stage-2
    # thresholds — never Staff's stage-1 ones; no duplicates anywhere.
    staff_notifications = await _notifications_for(
        db_session, user_id=staff.user_id, ticket_id=ticket.ticket_id
    )
    assert len(staff_notifications) == 3
    assert {n.notification_type for n in staff_notifications} == {
        NotificationType.SLA_HALF_ELAPSED,
        NotificationType.SLA_AT_RISK,
        NotificationType.SLA_BREACHED,
    }

    team_lead_notifications = await _notifications_for(
        db_session, user_id=team_lead.user_id, ticket_id=ticket.ticket_id
    )
    team_lead_types = [n.notification_type for n in team_lead_notifications]
    assert team_lead_types.count(NotificationType.ESCALATION_CREATED) == 1
    assert team_lead_types.count(NotificationType.SLA_HALF_ELAPSED) == 1
    assert team_lead_types.count(NotificationType.SLA_AT_RISK) == 1
    assert team_lead_types.count(NotificationType.SLA_BREACHED) == 1
    assert len(team_lead_notifications) == 4

    for n in staff_notifications + team_lead_notifications:
        assert n.related_entity_id == ticket.ticket_id
