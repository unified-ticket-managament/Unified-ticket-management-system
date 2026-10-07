# test_multi_assignment.py
#
# Multi-user + multi-category ticket assignment — service/database level.
# Runs against the real (dev) database inside a transaction that is always
# rolled back (see tests/multi_assignment_support.py). Covers the business
# rules end to end through the same services the API calls:
#
#   - assignment / primary / duplicate / removal rules
#   - individual (per-assignee) status, only CLOSED universal
#   - per-assignee SLA runs, no category SLA, close/reopen history
#   - RBAC stays authoritative (secondary == primary capabilities)
#   - compatibility of the existing single-assignee flows
#   - audit, impersonation, concurrency, no lazy-load/N+1 regressions

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.impersonation_context import set_impersonator
from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import AuditEventType, SLAClockStatus, TicketStatus
from app.ticketing.models.audit_log import AuditLog
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_assignment import TicketAssignment
from app.ticketing.models.ticket_assignment_sla import TicketAssignmentSLA
from app.ticketing.models.ticket_category import TicketCategory
from app.ticketing.repositories.audit_log_repository import AuditLogRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket_action import StatusChangeRequest, TransferAgentRequest
from app.ticketing.services.access_control import ensure_agent_can_act_on_ticket
from app.ticketing.services.escalation_rules import build_chain_owner_ids
from app.ticketing.services.ticket_assignment_service import (
    COMPLETION_TICKET_CLOSED,
    build_ticket_assignment_service,
    sweep_assignment_sla_breaches,
)
from app.ticketing.services.ticket_service import TicketService
from tests.multi_assignment_support import build_world, interaction_service, make_ticket


@pytest.fixture(autouse=True)
def _no_real_emails(monkeypatch):
    # TICKET_ASSIGNED is email-eligible; its dispatcher runs on its own
    # session outside this test's rolled-back transaction — never let a
    # test send mail or commit anything.
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


@pytest.fixture
async def world(db_session):
    return await build_world(db_session)


def service(world):
    return build_ticket_assignment_service(world.session)


async def active(world, ticket_id) -> dict:
    rows = await service(world).list_assignments(ticket_id)
    return {a.user_id: a for a in rows}


async def runs(world, ticket_id) -> list[TicketAssignmentSLA]:
    return list(
        (
            await world.session.execute(
                select(TicketAssignmentSLA)
                .where(TicketAssignmentSLA.ticket_id == ticket_id)
                .order_by(TicketAssignmentSLA.run_number)
            )
        ).scalars()
    )


async def live_run(world, assignment) -> TicketAssignmentSLA | None:
    return await service(world).repository.get_live_run(assignment.assignment_id)


async def events(world, ticket_id, event_type) -> list[AuditLog]:
    return list(
        (
            await world.session.execute(
                select(AuditLog)
                .where(AuditLog.ticket_id == ticket_id, AuditLog.event_type == event_type)
                .order_by(AuditLog.created_at)
            )
        ).scalars()
    )


async def three_assignees(world, **kwargs):
    ticket = await make_ticket(world, categories=[world.billing, world.claims], **kwargs)
    await service(world).add_users(
        ticket.ticket_id,
        [world.koushik.user_id, world.ravi.user_id, world.suresh.user_id],
        world.team_lead,
        primary_user_id=world.koushik.user_id,
    )
    return ticket


# ---------------------------------------------------------------
# 1. Migration backfill of an existing single-assignee ticket
# ---------------------------------------------------------------


async def test_backfill_turns_legacy_single_assignee_ticket_into_primary_assignment(world):
    import importlib

    backfill = importlib.import_module(
        "alembic_ticketing.versions.c3e5a7b9d1f3_backfill_ticket_assignments_and_categories"
    )
    session = world.session
    legacy = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=world.client.client_id,
        agent_id=world.koushik.user_id,
        assigned_by=world.team_lead.user_id,
        title="legacy",
        ticket_type=world.billing.category_name,
        current_status=TicketStatus.IN_PROGRESS,
    )
    session.add(legacy)
    await session.flush()
    from app.ticketing.services.sla_service import build_sla_service

    await build_sla_service(session).start_resolution_clock(
        ticket_id=legacy.ticket_id, client_id=legacy.client_company_id, priority=legacy.current_priority
    )

    for statement in backfill.BACKFILL_STATEMENTS:
        await session.execute(text(statement))
    for statement in backfill.BACKFILL_STATEMENTS:  # idempotent: re-run inserts nothing
        await session.execute(text(statement))

    assignments = await active(world, legacy.ticket_id)
    assert list(assignments) == [world.koushik.user_id]
    primary = assignments[world.koushik.user_id]
    assert primary.is_primary and primary.status == TicketStatus.IN_PROGRESS
    assert primary.assigned_by == world.team_lead.user_id

    categories = await service(world).repository.list_categories(legacy.ticket_id)
    assert [(name, tc.is_primary) for tc, name in categories] == [(world.billing.category_name, True)]

    ticket_clock = (
        await session.execute(select(ResolutionSLA).where(ResolutionSLA.ticket_id == legacy.ticket_id))
    ).scalar_one()
    [run] = await runs(world, legacy.ticket_id)
    assert (run.status, run.due_at, run.started_at) == (ticket_clock.status, ticket_clock.due_at, ticket_clock.started_at)


# ---------------------------------------------------------------
# 2-6. Assignment, duplicates, primary
# ---------------------------------------------------------------


async def test_multiple_users_assigned_with_one_primary_and_projection(world):
    ticket = await three_assignees(world)
    assignments = await active(world, ticket.ticket_id)
    assert set(assignments) == {world.koushik.user_id, world.ravi.user_id, world.suresh.user_id}
    assert [a.user_id for a in assignments.values() if a.is_primary] == [world.koushik.user_id]

    reloaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    assert reloaded.agent_id == world.koushik.user_id  # legacy projection = primary
    assert reloaded.assigned_by == world.team_lead.user_id
    assert reloaded.current_status == TicketStatus.IN_PROGRESS  # OPEN -> IN_PROGRESS, as before
    assert reloaded.active_assignee_ids == set(assignments)
    assert assignments[world.ravi.user_id].status == TicketStatus.OPEN  # secondaries start OPEN


async def test_duplicate_user_assignment_is_rejected_atomically(world):
    ticket = await three_assignees(world)
    with pytest.raises(HTTPException) as exc:
        await service(world).add_users(ticket.ticket_id, [world.ravi.user_id], world.team_lead)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        await service(world).add_users(
            ticket.ticket_id, [world.team_lead.user_id, world.team_lead.user_id], world.team_lead
        )
    assert exc.value.status_code == 400
    assert len(await active(world, ticket.ticket_id)) == 3


async def test_database_forbids_duplicate_active_user_and_second_primary(world):
    ticket = await three_assignees(world)
    session = world.session
    # The exception must propagate THROUGH begin_nested so the savepoint
    # rolls back cleanly and the outer test transaction stays usable.
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(TicketAssignment(ticket_id=ticket.ticket_id, user_id=world.ravi.user_id, status=TicketStatus.OPEN))
            await session.flush()
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(
                TicketAssignment(
                    ticket_id=ticket.ticket_id, user_id=world.team_lead.user_id, is_primary=True, status=TicketStatus.OPEN
                )
            )
            await session.flush()


async def test_bulk_assign_with_one_invalid_user_changes_nothing(world):
    ticket = await make_ticket(world)
    with pytest.raises(HTTPException) as exc:
        await service(world).add_users(
            ticket.ticket_id, [world.koushik.user_id, world.outsider.user_id], world.team_lead
        )
    assert exc.value.status_code == 400
    assert await active(world, ticket.ticket_id) == {}


async def test_change_primary_keeps_statuses_and_does_not_restart_sla(world):
    ticket = await three_assignees(world)
    before = await active(world, ticket.ticket_id)
    statuses = {uid: a.status for uid, a in before.items()}
    run_ids = {r.assignment_sla_id for r in await runs(world, ticket.ticket_id)}

    await service(world).change_primary(ticket.ticket_id, before[world.ravi.user_id].assignment_id, world.team_lead)

    after = await active(world, ticket.ticket_id)
    assert after[world.ravi.user_id].is_primary and not after[world.koushik.user_id].is_primary
    assert {uid: a.status for uid, a in after.items()} == statuses
    assert {r.assignment_sla_id for r in await runs(world, ticket.ticket_id)} == run_ids
    reloaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    assert reloaded.agent_id == world.ravi.user_id
    assert len(await events(world, ticket.ticket_id, AuditEventType.PRIMARY_CHANGED)) == 2


async def test_removing_primary_requires_a_new_primary_and_preserves_history(world):
    ticket = await three_assignees(world)
    koushik = (await active(world, ticket.ticket_id))[world.koushik.user_id]
    ravi = (await active(world, ticket.ticket_id))[world.ravi.user_id]

    with pytest.raises(HTTPException) as exc:
        await service(world).remove_assignment(ticket.ticket_id, koushik.assignment_id, world.team_lead)
    assert exc.value.status_code == 400

    await service(world).remove_assignment(
        ticket.ticket_id, koushik.assignment_id, world.team_lead, new_primary_assignment_id=ravi.assignment_id
    )
    after = await active(world, ticket.ticket_id)
    assert world.koushik.user_id not in after and after[world.ravi.user_id].is_primary
    removed = await service(world).repository.get(koushik.assignment_id)
    assert removed.removed_at is not None  # soft delete, history kept
    removed_run = [r for r in await runs(world, ticket.ticket_id) if r.assignment_id == koushik.assignment_id][0]
    assert removed_run.status == SLAClockStatus.COMPLETED and removed_run.completion_reason == "UNASSIGNED"
    assert len(await events(world, ticket.ticket_id, AuditEventType.USER_UNASSIGNED)) == 1

    # Re-adding the same user later is a NEW row with a NEW, single live run.
    await service(world).add_users(ticket.ticket_id, [world.koushik.user_id], world.team_lead)
    readded = (await active(world, ticket.ticket_id))[world.koushik.user_id]
    assert readded.assignment_id != koushik.assignment_id
    assert (await live_run(world, readded)) is not None


async def test_removing_the_only_assignee_returns_ticket_to_pool(world):
    ticket = await make_ticket(world)
    await service(world).add_users(ticket.ticket_id, [world.koushik.user_id], world.team_lead)
    only = (await active(world, ticket.ticket_id))[world.koushik.user_id]
    await service(world).remove_assignment(ticket.ticket_id, only.assignment_id, world.team_lead)
    reloaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    assert reloaded.agent_id is None


# ---------------------------------------------------------------
# 7-8, 20. Categories
# ---------------------------------------------------------------


async def test_multiple_categories_primary_projection_and_no_category_sla(world):
    ticket = await make_ticket(world, categories=[world.billing, world.claims])
    await service(world).add_users(ticket.ticket_id, [world.koushik.user_id], world.team_lead)
    run_count = len(await runs(world, ticket.ticket_id))

    await service(world).add_category(ticket.ticket_id, world.denials.category_id, world.account_manager)
    names = [(n, tc.is_primary) for tc, n in await service(world).repository.list_categories(ticket.ticket_id)]
    assert names == [
        (world.billing.category_name, True),
        (world.claims.category_name, False),
        (world.denials.category_name, False),
    ]
    assert (await TicketRepository(world.session).get_by_id(ticket.ticket_id)).ticket_type == world.billing.category_name
    assert len(await runs(world, ticket.ticket_id)) == run_count  # categories never own SLA
    assert len(await events(world, ticket.ticket_id, AuditEventType.CATEGORY_ADDED)) == 2


async def test_duplicate_category_rejected(world):
    ticket = await make_ticket(world, categories=[world.billing, world.claims])
    with pytest.raises(HTTPException) as exc:
        await service(world).add_category(ticket.ticket_id, world.claims.category_id, world.account_manager)
    assert exc.value.status_code == 409


async def test_removing_primary_category_promotes_next_and_never_strands_assignee(world):
    ticket = await make_ticket(world, categories=[world.billing, world.claims])
    await service(world).add_users(ticket.ticket_id, [world.suresh.user_id], world.team_lead)  # Suresh: claims only

    with pytest.raises(HTTPException) as exc:  # would hide the ticket from Suresh
        await service(world).remove_category(ticket.ticket_id, world.claims.category_id, world.account_manager)
    assert exc.value.status_code == 409

    await service(world).remove_category(ticket.ticket_id, world.billing.category_id, world.account_manager)
    reloaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    assert reloaded.ticket_type == world.claims.category_name

    with pytest.raises(HTTPException) as exc:  # never category-less
        await service(world).remove_category(ticket.ticket_id, world.claims.category_id, world.account_manager)
    assert exc.value.status_code in (400, 409)


# ---------------------------------------------------------------
# 9-12, 18-19. Individual status + independent SLA
# ---------------------------------------------------------------


@pytest.mark.parametrize("new_status", [TicketStatus.RESOLVED, TicketStatus.PENDING, TicketStatus.IN_PROGRESS])
async def test_secondary_status_change_touches_only_that_assignment(world, new_status):
    ticket = await three_assignees(world)
    before = await active(world, ticket.ticket_id)
    ticket_status_before = (await TicketRepository(world.session).get_by_id(ticket.ticket_id)).current_status

    await interaction_service(world.session).change_status(
        ticket.ticket_id, StatusChangeRequest(new_status=new_status), world.ravi
    )

    after = await active(world, ticket.ticket_id)
    assert after[world.ravi.user_id].status == new_status
    assert after[world.koushik.user_id].status == before[world.koushik.user_id].status
    assert after[world.suresh.user_id].status == before[world.suresh.user_id].status
    reloaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    assert reloaded.current_status == ticket_status_before  # ticket untouched by a secondary
    assert len(await events(world, ticket.ticket_id, AuditEventType.ASSIGNMENT_STATUS_CHANGED)) == 1


async def test_resolving_one_assignee_completes_only_their_sla(world):
    ticket = await three_assignees(world)
    a = await active(world, ticket.ticket_id)
    await interaction_service(world.session).change_status(
        ticket.ticket_id, StatusChangeRequest(new_status=TicketStatus.RESOLVED), world.suresh
    )
    assert (await live_run(world, a[world.suresh.user_id])) is None
    for other in (world.koushik, world.ravi):
        assert (await live_run(world, a[other.user_id])).status == SLAClockStatus.RUNNING
    ticket_clock = (
        await world.session.execute(select(ResolutionSLA).where(ResolutionSLA.ticket_id == ticket.ticket_id))
    ).scalar_one()
    assert ticket_clock.status == SLAClockStatus.RUNNING  # RESOLVED is not universal


async def test_every_assignee_has_an_independent_sla_run(world):
    ticket = await make_ticket(world, categories=[world.billing, world.claims])
    users = [world.koushik, world.ravi, world.suresh, world.team_lead]
    await service(world).add_users(ticket.ticket_id, [u.user_id for u in users], world.team_lead)
    all_runs = await runs(world, ticket.ticket_id)
    assert len(all_runs) == 4
    assert len({r.assignment_id for r in all_runs}) == 4
    assert all(r.status == SLAClockStatus.RUNNING for r in all_runs)


async def test_waiting_for_client_pauses_only_that_assignee_and_reply_resumes(world):
    ticket = await three_assignees(world)
    a = await active(world, ticket.ticket_id)
    await interaction_service(world.session).change_status(
        ticket.ticket_id, StatusChangeRequest(new_status=TicketStatus.WAITING_FOR_CLIENT), world.ravi
    )
    assert (await live_run(world, a[world.ravi.user_id])).status == SLAClockStatus.PAUSED
    assert (await live_run(world, a[world.koushik.user_id])).status == SLAClockStatus.RUNNING
    await service(world).on_customer_reply(ticket.ticket_id)
    assert (await live_run(world, a[world.ravi.user_id])).status == SLAClockStatus.RUNNING


async def test_primary_status_change_keeps_existing_ticket_level_behaviour(world):
    ticket = await three_assignees(world)
    await interaction_service(world.session).change_status(
        ticket.ticket_id, StatusChangeRequest(new_status=TicketStatus.RESOLVED), world.koushik
    )
    reloaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.RESOLVED  # unchanged single-assignee semantics
    ticket_clock = (
        await world.session.execute(select(ResolutionSLA).where(ResolutionSLA.ticket_id == ticket.ticket_id))
    ).scalar_one()
    assert ticket_clock.status == SLAClockStatus.COMPLETED
    a = await active(world, ticket.ticket_id)
    assert a[world.koushik.user_id].status == TicketStatus.RESOLVED
    assert a[world.ravi.user_id].status == TicketStatus.OPEN


# ---------------------------------------------------------------
# 13-17, 27, 32. Universal close / reopen
# ---------------------------------------------------------------


async def test_universal_close_closes_every_assignment_and_stops_every_sla(world):
    ticket = await three_assignees(world)
    a = await active(world, ticket.ticket_id)
    await interaction_service(world.session).change_status(
        ticket.ticket_id, StatusChangeRequest(new_status=TicketStatus.PENDING), world.ravi
    )
    await interaction_service(world.session).change_status(
        ticket.ticket_id, StatusChangeRequest(new_status=TicketStatus.RESOLVED), world.suresh
    )

    await interaction_service(world.session).close_ticket(ticket.ticket_id, world.account_manager)

    reloaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    assert reloaded.current_status == TicketStatus.CLOSED
    assert reloaded.closed_by == world.account_manager.user_id
    after = await active(world, ticket.ticket_id)
    assert {x.status for x in after.values()} == {TicketStatus.CLOSED}
    assert all(x.closed_by == world.account_manager.user_id for x in after.values())
    all_runs = await runs(world, ticket.ticket_id)
    assert all(r.status == SLAClockStatus.COMPLETED for r in all_runs)  # no live run on a closed ticket
    by_assignment = {r.assignment_id: r for r in all_runs}
    assert by_assignment[a[world.suresh.user_id].assignment_id].completion_reason == "RESOLVED"
    assert by_assignment[a[world.ravi.user_id].assignment_id].completion_reason == COMPLETION_TICKET_CLOSED

    [close_event] = await events(world, ticket.ticket_id, AuditEventType.TICKET_CLOSED)
    assert close_event.actor_id == world.account_manager.user_id
    previous = {row["user_id"]: row["status"] for row in close_event.old_values["assignments"]}
    assert previous == {
        str(world.koushik.user_id): "IN_PROGRESS",
        str(world.ravi.user_id): "PENDING",
        str(world.suresh.user_id): "RESOLVED",
    }
    assert close_event.new_values["current_status"] == "CLOSED"


async def test_second_close_is_rejected_and_status_change_cannot_close(world):
    ticket = await three_assignees(world)
    with pytest.raises(HTTPException):
        await interaction_service(world.session).change_status(
            ticket.ticket_id, StatusChangeRequest(new_status=TicketStatus.CLOSED), world.ravi
        )
    await interaction_service(world.session).close_ticket(ticket.ticket_id, world.account_manager)
    with pytest.raises(HTTPException) as exc:
        await interaction_service(world.session).close_ticket(ticket.ticket_id, world.account_manager)
    assert exc.value.status_code == 400


async def test_reopen_preserves_sla_history_and_starts_exactly_one_new_run_each(world):
    ticket = await three_assignees(world)
    await interaction_service(world.session).close_ticket(ticket.ticket_id, world.account_manager)
    closed_runs = {r.assignment_sla_id: (r.status, r.completed_at) for r in await runs(world, ticket.ticket_id)}

    await interaction_service(world.session).reopen_ticket(ticket.ticket_id, world.account_manager)

    after = await active(world, ticket.ticket_id)
    assert {x.status for x in after.values()} == {TicketStatus.OPEN}
    assert after[world.koushik.user_id].is_primary  # primary unchanged
    all_runs = await runs(world, ticket.ticket_id)
    for run in all_runs:
        if run.assignment_sla_id in closed_runs:
            assert (run.status, run.completed_at) == closed_runs[run.assignment_sla_id]  # history intact
    for assignment in after.values():
        mine = [r for r in all_runs if r.assignment_id == assignment.assignment_id]
        assert [r.run_number for r in mine] == [1, 2]
        assert sum(r.status != SLAClockStatus.COMPLETED for r in mine) == 1  # no duplicate timer


async def test_close_lock_blocks_a_concurrent_close_on_the_same_ticket():
    """
    Concurrency: lock_for_close takes SELECT ... FOR UPDATE, so a second
    transaction trying to close the same ticket waits instead of racing.
    Uses an existing committed ticket purely as a lock target — nothing
    is written, both transactions roll back.
    """

    async with AsyncSessionLocal() as probe:
        ticket_id = (await probe.execute(select(Ticket.ticket_id).limit(1))).scalar_one_or_none()
    if ticket_id is None:
        pytest.skip("No ticket in the connected database to lock.")

    async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
        try:
            await build_ticket_assignment_service(first).lock_for_close(ticket_id)
            await second.execute(text("SET LOCAL lock_timeout = '1500ms'"))
            with pytest.raises(Exception) as exc:
                await build_ticket_assignment_service(second).lock_for_close(ticket_id)
            assert "lock" in str(exc.value).lower()
        finally:
            await second.rollback()
            await first.rollback()
    await engine.dispose()


# ---------------------------------------------------------------
# 21-25. RBAC stays authoritative
# ---------------------------------------------------------------


async def test_secondary_has_same_operational_access_as_primary(world):
    ticket = await three_assignees(world)
    loaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    for user in (world.koushik, world.ravi):
        await ensure_agent_can_act_on_ticket(loaded, user)  # no exception for either


async def test_rbac_denial_still_applies_to_a_secondary(world):
    ticket = await three_assignees(world)
    world.ravi.permissions = [p for p in world.ravi.permissions if p != "ticket:editown_ticket"]
    loaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    with pytest.raises(HTTPException) as exc:
        await ensure_agent_can_act_on_ticket(loaded, world.ravi)
    assert exc.value.status_code == 403

    world.ravi.permissions = [p for p in world.ravi.permissions if p != "ticket:update_status"]
    with pytest.raises(HTTPException):
        await interaction_service(world.session).change_status(
            ticket.ticket_id, StatusChangeRequest(new_status=TicketStatus.PENDING), world.ravi
        )


async def test_assignee_cannot_change_another_assignees_status(world):
    ticket = await three_assignees(world)
    koushik = (await active(world, ticket.ticket_id))[world.koushik.user_id]
    ravi = (await active(world, ticket.ticket_id))[world.ravi.user_id]
    with pytest.raises(HTTPException) as exc:
        await interaction_service(world.session).change_status(
            ticket.ticket_id,
            StatusChangeRequest(new_status=TicketStatus.PENDING, assignment_id=koushik.assignment_id),
            world.ravi,
        )
    assert exc.value.status_code == 403
    # A supervisor may.
    await interaction_service(world.session).change_status(
        ticket.ticket_id,
        StatusChangeRequest(new_status=TicketStatus.PENDING, assignment_id=ravi.assignment_id),
        world.team_lead,
    )
    assert (await active(world, ticket.ticket_id))[world.ravi.user_id].status == TicketStatus.PENDING


async def test_unauthorized_user_cannot_assign_users(world):
    ticket = await make_ticket(world)
    with pytest.raises(HTTPException) as exc:
        await service(world).add_users(ticket.ticket_id, [world.ravi.user_id], world.koushik)  # Staff
    assert exc.value.status_code == 403


async def test_unauthorized_user_cannot_change_categories(world):
    ticket = await make_ticket(world)
    with pytest.raises(HTTPException) as exc:
        await service(world).add_category(ticket.ticket_id, world.claims.category_id, world.team_lead)
    assert exc.value.status_code == 403


async def test_users_outside_the_tickets_scope_cannot_be_assigned(world):
    ticket = await make_ticket(world)  # billing only, AM's own client
    for target in (world.outsider, world.other_account_manager):
        with pytest.raises(HTTPException) as exc:
            await service(world).add_users(ticket.ticket_id, [target.user_id], world.account_manager)
        assert exc.value.status_code == 400
    # And another AM can't manage this client's ticket at all.
    with pytest.raises(HTTPException) as exc:
        await service(world).add_users(ticket.ticket_id, [world.koushik.user_id], world.other_account_manager)
    assert exc.value.status_code == 403


async def test_assignment_never_makes_an_unrelated_ticket_visible(world):
    mine = await three_assignees(world)
    other = await make_ticket(world, categories=[world.denials])
    rows, _total = await TicketService(
        ticket_repository=TicketRepository(world.session),
        user_repository=UserRepository(world.session),
        client_repository=ClientRepository(world.session),
    ).list_all(world.ravi, limit=200, view="all")
    ids = {r.ticket_id for r in rows}
    assert mine.ticket_id in ids
    assert other.ticket_id not in ids


# ---------------------------------------------------------------
# 26. Audit, 28-31 compatibility of existing flows
# ---------------------------------------------------------------


async def test_assignment_audit_events(world):
    ticket = await three_assignees(world)
    assert len(await events(world, ticket.ticket_id, AuditEventType.USER_ASSIGNED)) == 3
    [primary_event] = await events(world, ticket.ticket_id, AuditEventType.PRIMARY_CHANGED)
    assert primary_event.new_values["agent_id"] == str(world.koushik.user_id)
    assert primary_event.actor_id == world.team_lead.user_id


async def test_claim_creates_primary_assignment_with_its_own_sla(world):
    ticket = await make_ticket(world)
    await interaction_service(world.session).claim_ticket(ticket.ticket_id, world.koushik)
    [assignment] = (await active(world, ticket.ticket_id)).values()
    assert assignment.user_id == world.koushik.user_id and assignment.is_primary
    assert assignment.status == TicketStatus.IN_PROGRESS
    assert (await live_run(world, assignment)) is not None


async def test_transfer_replaces_primary_and_promotes_an_existing_secondary(world):
    ticket = await three_assignees(world)
    ravi_before = (await active(world, ticket.ticket_id))[world.ravi.user_id]
    ravi_run = await live_run(world, ravi_before)

    await interaction_service(world.session).transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=world.ravi.user_id, reason="handover"),
        world.team_lead,
    )

    after = await active(world, ticket.ticket_id)
    assert world.koushik.user_id not in after  # transfer semantics unchanged: old primary replaced
    assert after[world.ravi.user_id].is_primary
    assert after[world.ravi.user_id].assignment_id == ravi_before.assignment_id
    assert (await live_run(world, after[world.ravi.user_id])).assignment_sla_id == ravi_run.assignment_sla_id
    assert (await TicketRepository(world.session).get_by_id(ticket.ticket_id)).agent_id == world.ravi.user_id


async def test_cross_category_transfer_moves_the_primary_category(world):
    ticket = await make_ticket(world)
    await interaction_service(world.session).transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=world.suresh.user_id, reason="move", category_name=world.claims.category_name),
        world.account_manager,
    )
    names = [(n, tc.is_primary) for tc, n in await service(world).repository.list_categories(ticket.ticket_id)]
    assert names == [(world.claims.category_name, True)]


async def test_secondaries_never_enter_the_escalation_chain(world):
    ticket = await make_ticket(world, categories=[world.billing, world.claims])
    await interaction_service(world.session).transfer_agent(
        ticket.ticket_id, TransferAgentRequest(new_agent_id=world.koushik.user_id, reason="assign"), world.team_lead
    )
    loaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    chain_before = await build_chain_owner_ids(loaded, AuditLogRepository(world.session))

    await service(world).add_users(ticket.ticket_id, [world.ravi.user_id, world.suresh.user_id], world.team_lead)
    loaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    assert await build_chain_owner_ids(loaded, AuditLogRepository(world.session)) == chain_before


async def test_primary_change_feeds_the_escalation_chain_like_a_transfer(world):
    ticket = await three_assignees(world)
    ravi = (await active(world, ticket.ticket_id))[world.ravi.user_id]
    await service(world).change_primary(ticket.ticket_id, ravi.assignment_id, world.account_manager)
    loaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    chain = await build_chain_owner_ids(loaded, AuditLogRepository(world.session))
    assert chain[0] == world.account_manager.user_id


async def test_my_tickets_includes_secondary_and_primary_only_filter(world):
    ticket = await three_assignees(world)
    svc = TicketService(
        ticket_repository=TicketRepository(world.session),
        user_repository=UserRepository(world.session),
        client_repository=ClientRepository(world.session),
    )
    for user in (world.koushik, world.ravi):
        rows, _ = await svc.list_all(user, limit=200, view="mine")
        assert ticket.ticket_id in {r.ticket_id for r in rows}

    rows, _ = await svc.list_all(world.team_lead, limit=200, view="all", assignee_id_filter=world.ravi.user_id)
    assert ticket.ticket_id in {r.ticket_id for r in rows}
    rows, _ = await svc.list_all(
        world.team_lead, limit=200, view="all", assignee_id_filter=world.ravi.user_id, primary_only=True
    )
    assert ticket.ticket_id not in {r.ticket_id for r in rows}
    rows, _ = await svc.list_all(
        world.team_lead, limit=200, view="all", assignee_id_filter=world.koushik.user_id, primary_only=True
    )
    [row] = [r for r in rows if r.ticket_id == ticket.ticket_id]
    assert row.agent_id == world.koushik.user_id  # legacy field still the primary
    assert {a.user_id for a in row.assignees} == {world.koushik.user_id, world.ravi.user_id, world.suresh.user_id}
    assert {c.category_name for c in row.categories} == {world.billing.category_name, world.claims.category_name}


async def test_ticket_detail_keeps_legacy_fields_and_adds_lists(world):
    ticket = await three_assignees(world)
    detail = await TicketService(
        ticket_repository=TicketRepository(world.session),
        user_repository=UserRepository(world.session),
        client_repository=ClientRepository(world.session),
    ).get_by_id(ticket.ticket_id, world.ravi)
    assert detail.agent_id == world.koushik.user_id
    assert detail.ticket_type == world.billing.category_name
    assert len(detail.assignees) == 3 and len(detail.categories) == 2


# ---------------------------------------------------------------
# SLA sweep, impersonation, async safety, N+1
# ---------------------------------------------------------------


async def test_sweep_stamps_each_breached_assignee_run_once(world):
    from datetime import datetime, timedelta, timezone

    ticket = await three_assignees(world)
    a = await active(world, ticket.ticket_id)
    run = await live_run(world, a[world.ravi.user_id])
    run.due_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await world.session.flush()

    now = datetime.now(timezone.utc)
    assert await sweep_assignment_sla_breaches(world.session, now=now) >= 1
    assert run.breached_at is not None
    stamped = run.breached_at
    await sweep_assignment_sla_breaches(world.session, now=now)
    assert run.breached_at == stamped  # idempotent
    assert (await live_run(world, a[world.koushik.user_id])).breached_at is None


async def test_impersonated_assignment_records_the_real_admin(world):
    ticket = await make_ticket(world)
    set_impersonator(world.site_lead.user_id, world.site_lead.name)
    try:
        await service(world).add_users(ticket.ticket_id, [world.koushik.user_id], world.team_lead)
    finally:
        set_impersonator(None, None)
    [assigned] = await events(world, ticket.ticket_id, AuditEventType.USER_ASSIGNED)
    assert assigned.actor_id == world.team_lead.user_id  # effective user
    assert assigned.impersonator_id == world.site_lead.user_id  # actual admin


async def test_impersonation_does_not_bypass_the_effective_users_rbac(world):
    ticket = await make_ticket(world)
    set_impersonator(world.site_lead.user_id, world.site_lead.name)
    try:
        with pytest.raises(HTTPException) as exc:
            await service(world).add_users(ticket.ticket_id, [world.ravi.user_id], world.koushik)
        assert exc.value.status_code == 403
    finally:
        set_impersonator(None, None)


async def test_no_lazy_load_after_mutations(world):
    ticket = await three_assignees(world)
    # Sync access (like access_control does) to every attribute the
    # checks read — a lazy load here would raise MissingGreenlet.
    loaded = await TicketRepository(world.session).get_by_id(ticket.ticket_id)
    _ = (loaded.agent_id, loaded.ticket_type, loaded.active_assignee_ids, loaded.category_names)
    for assignment in await service(world).list_assignments(ticket.ticket_id):
        _ = (assignment.status, assignment.is_primary, assignment.assigned_at, assignment.removed_at)


async def test_list_assignment_enrichment_is_constant_query_count(world):
    small = [await three_assignees(world)]
    large = [await three_assignees(world) for _ in range(4)]
    svc = TicketService(
        ticket_repository=TicketRepository(world.session),
        user_repository=UserRepository(world.session),
        client_repository=ClientRepository(world.session),
    )

    async def count_queries(tickets) -> int:
        rows, _ = await svc.list_all(world.team_lead, limit=200, view="all")
        page = [r for r in rows if r.ticket_id in {t.ticket_id for t in tickets}]
        statements: list[str] = []

        def on_execute(conn, cursor, statement, *args):
            statements.append(statement)

        sync_engine = world.session.bind.sync_engine if hasattr(world.session.bind, "sync_engine") else engine.sync_engine
        event.listen(sync_engine, "before_cursor_execute", on_execute)
        try:
            await svc._attach_assignment_summaries(page)
        finally:
            event.remove(sync_engine, "before_cursor_execute", on_execute)
        assert all(len(r.assignees) == 3 for r in page)
        return len(statements)

    assert await count_queries(small) == await count_queries(large) == 2


# ---------------------------------------------------------------
# Multi-assignment at ticket creation (Create Ticket From This Email)
# ---------------------------------------------------------------


async def _pending_email(world):
    from datetime import datetime, timezone

    from app.ticketing.enums import InteractionDirection, InteractionStatus
    from app.ticketing.models.interaction import Interaction

    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        status=InteractionStatus.PENDING,
        payload={"message": "please help"},
        client_id=world.client.client_id,
        is_visible=True,
        subject="Help needed",
        received_at=datetime.now(timezone.utc),
    )
    world.session.add(interaction)
    await world.session.flush()
    return interaction


def _inbox_service(world):
    from app.ticketing.repositories.interaction_repository import InteractionRepository
    from app.ticketing.services.assignment_service import AssignmentService
    from app.ticketing.services.inbox_ticket_service import InboxTicketService

    return InboxTicketService(
        ticket_repository=TicketRepository(world.session),
        interaction_repository=InteractionRepository(world.session),
        assignment_service=AssignmentService(UserRepository(world.session)),
        client_repository=ClientRepository(world.session),
    )


async def test_create_ticket_with_multiple_assignees(world):
    from app.ticketing.schemas.ticket_from_interaction import TicketFromInteractionCreate

    email = await _pending_email(world)
    response = await _inbox_service(world).create_ticket_from_interaction(
        TicketFromInteractionCreate(
            interaction_id=email.interaction_id,
            title="Multi-assigned at creation",
            ticket_type=world.billing.category_name,
            agent_id=world.koushik.user_id,
            additional_agent_ids=[world.ravi.user_id],
        ),
        current_user=world.account_manager,
    )
    assignments = await active(world, response.ticket_id)
    assert set(assignments) == {world.koushik.user_id, world.ravi.user_id}
    assert assignments[world.koushik.user_id].is_primary
    assert not assignments[world.ravi.user_id].is_primary
    assert len(await runs(world, response.ticket_id)) == 2  # one SLA run per assignee
    ticket = await TicketRepository(world.session).get_by_id(response.ticket_id)
    assert ticket.agent_id == world.koushik.user_id
    assert ticket.current_status == TicketStatus.IN_PROGRESS


async def test_create_ticket_additional_assignees_require_a_primary(world):
    from app.ticketing.schemas.ticket_from_interaction import TicketFromInteractionCreate

    email = await _pending_email(world)
    with pytest.raises(HTTPException) as exc:
        await _inbox_service(world).create_ticket_from_interaction(
            TicketFromInteractionCreate(
                interaction_id=email.interaction_id,
                title="x",
                ticket_type=world.billing.category_name,
                additional_agent_ids=[world.ravi.user_id],
            ),
            current_user=world.account_manager,
        )
    assert exc.value.status_code == 400


async def test_create_ticket_with_an_out_of_scope_additional_assignee_creates_nothing(world):
    from app.ticketing.schemas.ticket_from_interaction import TicketFromInteractionCreate

    email = await _pending_email(world)
    before = (await world.session.execute(select(func.count()).select_from(Ticket))).scalar_one()
    with pytest.raises(HTTPException) as exc:
        await _inbox_service(world).create_ticket_from_interaction(
            TicketFromInteractionCreate(
                interaction_id=email.interaction_id,
                title="x",
                ticket_type=world.billing.category_name,
                agent_id=world.koushik.user_id,
                additional_agent_ids=[world.outsider.user_id],
            ),
            current_user=world.account_manager,
        )
    assert exc.value.status_code == 400
    after = (await world.session.execute(select(func.count()).select_from(Ticket))).scalar_one()
    assert after == before  # rejected before anything was written


async def test_create_ticket_with_people_picked_per_category(world):
    from app.ticketing.schemas.ticket_from_interaction import (
        AdditionalAssignmentIn,
        TicketFromInteractionCreate,
    )

    email = await _pending_email(world)
    response = await _inbox_service(world).create_ticket_from_interaction(
        TicketFromInteractionCreate(
            interaction_id=email.interaction_id,
            title="Billing + Claims work",
            ticket_type=world.billing.category_name,
            agent_id=world.koushik.user_id,  # primary, from Billing
            additional_assignments=[
                AdditionalAssignmentIn(category_name=world.billing.category_name, user_id=world.ravi.user_id),
                AdditionalAssignmentIn(category_name=world.claims.category_name, user_id=world.suresh.user_id),
            ],
        ),
        current_user=world.account_manager,
    )
    categories = [(n, tc.is_primary) for tc, n in await service(world).repository.list_categories(response.ticket_id)]
    assert categories == [(world.billing.category_name, True), (world.claims.category_name, False)]
    assignments = await active(world, response.ticket_id)
    assert set(assignments) == {world.koushik.user_id, world.ravi.user_id, world.suresh.user_id}
    assert [u for u, a in assignments.items() if a.is_primary] == [world.koushik.user_id]
    assert len(await runs(world, response.ticket_id)) == 3  # categories add no SLA
    assert len(await events(world, response.ticket_id, AuditEventType.CATEGORY_ADDED)) == 1


async def test_create_ticket_rejects_a_person_outside_their_rows_category(world):
    from app.ticketing.schemas.ticket_from_interaction import (
        AdditionalAssignmentIn,
        TicketFromInteractionCreate,
    )

    email = await _pending_email(world)
    before = (await world.session.execute(select(func.count()).select_from(Ticket))).scalar_one()
    with pytest.raises(HTTPException) as exc:
        await _inbox_service(world).create_ticket_from_interaction(
            TicketFromInteractionCreate(
                interaction_id=email.interaction_id,
                title="x",
                ticket_type=world.billing.category_name,
                agent_id=world.koushik.user_id,
                # Suresh works Claims, not Billing — this row's category.
                additional_assignments=[
                    AdditionalAssignmentIn(category_name=world.billing.category_name, user_id=world.suresh.user_id)
                ],
            ),
            current_user=world.account_manager,
        )
    assert exc.value.status_code == 400
    after = (await world.session.execute(select(func.count()).select_from(Ticket))).scalar_one()
    assert after == before
