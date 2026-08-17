# test_category_transfer.py
#
# Regression coverage for cross-category ticket transfer —
# InteractionService.transfer_agent's category_will_change branch (see
# root CLAUDE.md's "Cross-Category Ticket Transfer" section). No new
# table/audit-system/timeline-system exists for this feature; it
# reuses transfer_agent's own existing AGENT_TRANSFERRED audit write,
# adding a second, dedicated CATEGORY_TRANSFERRED entry only when the
# caller's chosen category_name differs from the ticket's own current
# ticket_type.
#
# Same real-DB-rolled-back-transaction convention as
# test_transfer_candidates.py/test_escalation_service.py, reusing
# their scenario/user-lookup helpers rather than reinventing fixtures.
#
# IMPORTANT: every `current_user` passed into transfer_agent/
# get_transfer_candidates must have User.categories eagerly loaded —
# ensure_agent_can_view_ticket reads that relationship, and none of
# test_escalation_service.py's own user-lookup helpers eager-load it
# (they only joinedload the legacy singular User.category). Skipping
# this already makes test_transfer_candidates.py's and
# test_acknowledge_and_assign_escalation.py's own tests fail with
# sqlalchemy.exc.MissingGreenlet on this exact lazy load — confirmed
# to already reproduce identically on main before this feature's
# changes, i.e. a pre-existing, unrelated environment issue, not
# something introduced here. _with_categories below works around it
# locally rather than fixing the shared fixture helpers, keeping this
# file's changes scoped to the feature only.

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from shared_models.models import Category, User
from shared_models.models.category import CategoryName
from shared_models.models.user_category import user_categories as user_categories_table

from app.ticketing.enums import AuditEventType
from app.ticketing.models.audit_log import AuditLog
from app.ticketing.repositories.audit_log_repository import AuditLogRepository
from app.ticketing.schemas.ticket_action import TransferAgentRequest
from tests.test_acknowledge_and_assign_escalation import _build_interaction_service
from tests.test_escalation_service import (
    TEAM_LEAD_CATEGORY,
    _get_site_lead,
    _get_staff_owner,
    _make_scenario,
    db_session,  # noqa: F401 -- reused fixture
)


async def _with_categories(session, user: User) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), selectinload(User.categories))
        .where(User.user_id == user.user_id)
    )
    return result.unique().scalar_one()


async def _get_category(session, name: str) -> Category:
    result = await session.execute(
        select(Category).where(Category.category_name == CategoryName(name))
    )
    category = result.scalars().first()
    if category is None:
        pytest.skip(f"No seeded Category row for {name!r}.")
    return category


async def _get_active_user_in_category(
    session, category_name: str, *, exclude_user_id=None
) -> User:
    stmt = (
        select(User)
        .options(joinedload(User.role), selectinload(User.categories))
        .join(user_categories_table, user_categories_table.c.user_id == User.user_id)
        .join(Category, Category.category_id == user_categories_table.c.category_id)
        .where(
            Category.category_name == CategoryName(category_name),
            User.is_active.is_(True),
        )
    )
    result = await session.execute(stmt)
    for user in result.unique().scalars().all():
        if exclude_user_id is None or user.user_id != exclude_user_id:
            return user
    pytest.skip(f"No active seeded user found in category {category_name!r}.")


async def _make_multi_category_user(session, categories: list[Category], role_id) -> User:
    user = User(
        user_id=uuid.uuid4(),
        name="Multi-Category Transfer Test User",
        email=f"multi-category-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role_id=role_id,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    for category in categories:
        await session.execute(
            user_categories_table.insert().values(
                user_id=user.user_id, category_id=category.category_id
            )
        )
    await session.flush()
    return await _with_categories(session, user)


async def _category_audit_rows(session, ticket_id) -> list[AuditLog]:
    repo = AuditLogRepository(session)
    logs = await repo.list_by_ticket(ticket_id)
    return [log for log in logs if log.event_type == AuditEventType.CATEGORY_TRANSFERRED]


OTHER_CATEGORY = "AR"
THIRD_CATEGORY = "Authorization"


async def test_category_transfer_moves_ticket_and_writes_both_audit_entries(db_session):
    """
    AR -> Payment Posting-style flow (here: Payment Posting -> AR,
    since the seeded scenario ticket already starts in Payment
    Posting): ticket_type changes, exactly one AGENT_TRANSFERRED and
    one CATEGORY_TRANSFERRED audit row are written, and the ticket ID
    itself never changes.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    caller = await _with_categories(db_session, team_lead)
    target = await _get_active_user_in_category(db_session, OTHER_CATEGORY)

    original_ticket_id = ticket.ticket_id
    assert ticket.ticket_type == TEAM_LEAD_CATEGORY

    service = _build_interaction_service(db_session)
    response = await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(
            new_agent_id=target.user_id,
            reason="Moving to AR for the next stage",
            category_name=OTHER_CATEGORY,
        ),
        caller,
    )

    assert response.ticket_id == original_ticket_id

    await db_session.refresh(ticket)
    assert ticket.ticket_id == original_ticket_id
    assert ticket.ticket_type == OTHER_CATEGORY
    assert ticket.agent_id == target.user_id

    category_rows = await _category_audit_rows(db_session, ticket.ticket_id)
    assert len(category_rows) == 1
    assert category_rows[0].old_values["ticket_type"] == TEAM_LEAD_CATEGORY
    assert category_rows[0].new_values["ticket_type"] == OTHER_CATEGORY

    all_logs = await AuditLogRepository(db_session).list_by_ticket(ticket.ticket_id)
    agent_rows = [log for log in all_logs if log.event_type == AuditEventType.AGENT_TRANSFERRED]
    assert len(agent_rows) == 1


async def test_sequential_category_transfers_accumulate_without_overwriting(db_session):
    """
    Payment Posting -> AR -> Authorization -> Payment Posting: three
    distinct CATEGORY_TRANSFERRED rows, final ticket_type back at the
    starting category, no history overwritten.

    Uses a Site Lead as the caller for every hop — Site Lead's
    visibility isn't category-scoped (unlike Team Lead/Staff, see
    access_control.CATEGORY_SCOPED_ROLE_NAMES), which matters here
    because the ticket genuinely leaves the original Team Lead's own
    category after the first hop; a real multi-hop chain like this
    would naturally be driven by different people or an unrestricted
    supervisor role at each step, not the same category-scoped Team
    Lead throughout — that's the existing, unmodified
    ensure_agent_can_view_ticket rule at work, not something this test
    is about.
    """

    _team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    caller = await _get_site_lead(db_session)

    hops = [OTHER_CATEGORY, THIRD_CATEGORY, TEAM_LEAD_CATEGORY]
    service = _build_interaction_service(db_session)

    for destination in hops:
        target = await _get_active_user_in_category(db_session, destination)
        await service.transfer_agent(
            ticket.ticket_id,
            TransferAgentRequest(
                new_agent_id=target.user_id,
                reason=f"Move to {destination}",
                category_name=destination,
            ),
            caller,
        )
        await db_session.refresh(ticket)
        assert ticket.ticket_type == destination

    assert ticket.ticket_type == TEAM_LEAD_CATEGORY  # back where it started

    category_rows = await _category_audit_rows(db_session, ticket.ticket_id)
    assert len(category_rows) == 3
    transitions = [
        (row.old_values["ticket_type"], row.new_values["ticket_type"]) for row in category_rows
    ]
    assert (TEAM_LEAD_CATEGORY, OTHER_CATEGORY) in transitions
    assert (OTHER_CATEGORY, THIRD_CATEGORY) in transitions
    assert (THIRD_CATEGORY, TEAM_LEAD_CATEGORY) in transitions


async def test_invalid_destination_category_is_rejected(db_session):
    """Destination category validated before touching the ticket at all."""

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    caller = await _with_categories(db_session, team_lead)
    target = await _get_active_user_in_category(db_session, OTHER_CATEGORY)

    service = _build_interaction_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.transfer_agent(
            ticket.ticket_id,
            TransferAgentRequest(
                new_agent_id=target.user_id,
                reason="bogus category",
                category_name="Not A Real Category",
            ),
            caller,
        )
    assert exc_info.value.status_code == 400

    await db_session.refresh(ticket)
    assert ticket.ticket_type == TEAM_LEAD_CATEGORY  # unchanged
    assert ticket.agent_id is None  # unchanged
    assert await _category_audit_rows(db_session, ticket.ticket_id) == []


async def test_new_agent_outside_destination_category_is_rejected(db_session):
    """
    Selected user must belong to the selected destination category —
    backend-enforced, not just a frontend filter.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    caller = await _with_categories(db_session, team_lead)
    # A user in a category other than the destination we're claiming.
    mismatched_target = await _get_active_user_in_category(db_session, THIRD_CATEGORY)

    service = _build_interaction_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.transfer_agent(
            ticket.ticket_id,
            TransferAgentRequest(
                new_agent_id=mismatched_target.user_id,
                reason="mismatched category",
                category_name=OTHER_CATEGORY,
            ),
            caller,
        )
    assert exc_info.value.status_code == 400

    await db_session.refresh(ticket)
    assert ticket.ticket_type == TEAM_LEAD_CATEGORY  # unchanged
    assert await _category_audit_rows(db_session, ticket.ticket_id) == []


async def test_multi_category_user_eligible_for_either_category_not_a_third(db_session):
    """
    A user belonging to two categories (AR + Payment Posting) is a
    valid transfer target for a ticket in either, but not for a third
    category they don't belong to.

    Uses a Site Lead as the caller (see the sequential-transfers test
    above for why) — the ticket ends up outside the original Team
    Lead's own category partway through this test.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    caller = await _get_site_lead(db_session)

    ar_category = await _get_category(db_session, OTHER_CATEGORY)
    pp_category = await _get_category(db_session, TEAM_LEAD_CATEGORY)
    staff_role_id = team_lead.role_id
    # Use an existing Staff role id so the multi-category user is a
    # real agent-capable role, not the Team Lead's own role.
    staff_template = await _get_staff_owner(db_session, team_lead)
    multi_user = await _make_multi_category_user(
        db_session, [ar_category, pp_category], staff_template.role_id
    )

    service = _build_interaction_service(db_session)

    # Eligible for the ticket's own current category (Payment Posting) —
    # no category move, plain reassignment.
    response = await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(
            new_agent_id=multi_user.user_id,
            reason="assign to multi-category user",
            category_name=TEAM_LEAD_CATEGORY,
        ),
        caller,
    )
    assert response.ticket_id == ticket.ticket_id
    await db_session.refresh(ticket)
    assert ticket.agent_id == multi_user.user_id
    assert ticket.ticket_type == TEAM_LEAD_CATEGORY

    # Also eligible for their other category (AR) — a real cross-category
    # move, same agent stays assigned throughout (relaxed equality guard).
    response2 = await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(
            new_agent_id=multi_user.user_id,
            reason="move to AR, same owner",
            category_name=OTHER_CATEGORY,
        ),
        caller,
    )
    assert response2.ticket_id == ticket.ticket_id
    await db_session.refresh(ticket)
    assert ticket.ticket_type == OTHER_CATEGORY
    assert ticket.agent_id == multi_user.user_id

    # Not eligible for a third category they don't belong to.
    with pytest.raises(HTTPException) as exc_info:
        await service.transfer_agent(
            ticket.ticket_id,
            TransferAgentRequest(
                new_agent_id=multi_user.user_id,
                reason="not eligible here",
                category_name=THIRD_CATEGORY,
            ),
            caller,
        )
    assert exc_info.value.status_code == 400


async def test_caller_without_transfer_permission_is_still_forbidden(db_session):
    """
    A category_name on the request must not bypass the existing
    transfer-permission gate — permission is checked before any
    category logic runs.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    staff = await _get_staff_owner(db_session, team_lead)
    staff = await _with_categories(db_session, staff)
    staff.permissions = []  # no ticket:transfer override
    target = await _get_active_user_in_category(db_session, OTHER_CATEGORY)

    service = _build_interaction_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.transfer_agent(
            ticket.ticket_id,
            TransferAgentRequest(
                new_agent_id=target.user_id,
                reason="should be forbidden",
                category_name=OTHER_CATEGORY,
            ),
            staff,
        )
    assert exc_info.value.status_code == 403

    await db_session.refresh(ticket)
    assert ticket.ticket_type == TEAM_LEAD_CATEGORY  # unchanged
    assert await _category_audit_rows(db_session, ticket.ticket_id) == []


async def test_category_name_omitted_or_unchanged_leaves_ticket_type_untouched(db_session):
    """
    Regression check: the pre-existing, category-blind reassignment
    behavior must stay byte-identical. Omitting category_name, or
    supplying the ticket's own current category, must never write a
    CATEGORY_TRANSFERRED row or change ticket_type.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    caller = await _with_categories(db_session, team_lead)
    staff_owner = await _get_staff_owner(db_session, team_lead)

    service = _build_interaction_service(db_session)

    # category_name omitted entirely.
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=staff_owner.user_id, reason="plain reassignment"),
        caller,
    )
    await db_session.refresh(ticket)
    assert ticket.ticket_type == TEAM_LEAD_CATEGORY
    assert ticket.agent_id == staff_owner.user_id
    assert await _category_audit_rows(db_session, ticket.ticket_id) == []

    # category_name supplied but equal to the ticket's current category.
    other_target = await _get_active_user_in_category(
        db_session, TEAM_LEAD_CATEGORY, exclude_user_id=staff_owner.user_id
    )
    await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(
            new_agent_id=other_target.user_id,
            reason="same category filter",
            category_name=TEAM_LEAD_CATEGORY,
        ),
        caller,
    )
    await db_session.refresh(ticket)
    assert ticket.ticket_type == TEAM_LEAD_CATEGORY
    assert await _category_audit_rows(db_session, ticket.ticket_id) == []
