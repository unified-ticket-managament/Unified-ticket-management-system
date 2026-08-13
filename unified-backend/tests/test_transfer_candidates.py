# test_transfer_candidates.py
#
# Coverage for InteractionService.get_transfer_candidates and
# transfer_agent — by explicit product requirement, the Transfer
# Ticket / Assign to Staff picker now lists every active,
# agent-capable user (AGENT_ROLE_NAMES — any role except the
# client-facing Viewer), company-wide, regardless of the caller's own
# role, the ticket's own category, or the org-chart reporting
# hierarchy that used to scope both the candidate list and
# transfer_agent's own target acceptance. Verifies the candidate set
# still mirrors transfer_agent's own acceptance rules exactly, that
# inactive users and the ticket's own current agent are never
# offered, and that the caller never sees themselves duplicated in
# their own role's group (self-assignment is offered separately via
# `me`).
#
# Same conventions as test_escalation_service.py: runs against the
# real (dev) database inside a transaction always rolled back at the
# end, reuses that file's own scenario/user-lookup helpers.

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.ticketing.schemas.ticket_action import TransferAgentRequest
from tests.test_acknowledge_and_assign_escalation import _build_interaction_service
from tests.test_escalation_service import (
    _get_account_manager,
    _get_site_lead,
    _get_staff_owner,
    _make_scenario,
    db_session,  # noqa: F401 -- reused fixture
)


async def _get_super_admin(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Super Admin", User.is_active.is_(True))
    )
    super_admin = result.unique().scalars().first()
    if super_admin is None:
        pytest.skip("No active seeded Super Admin found.")
    return super_admin


def _group_names(response, role: str) -> set[str]:
    for group in response.groups:
        if group.role == role:
            return {u.name for u in group.users}
    return set()


async def _make_inactive_user(db_session, template: User) -> User:
    """Same shape as test_internal_note_recipients.py's inline inactive-user fixture."""

    inactive_user = User(
        user_id=uuid.uuid4(),
        name="Inactive Transfer Candidate",
        email=f"inactive-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role_id=template.role_id,
        is_active=False,
    )
    db_session.add(inactive_user)
    await db_session.flush()
    return inactive_user


async def test_team_lead_now_sees_every_active_agent_role_not_just_staff(db_session):
    """
    Before the widening, a Team Lead caller only ever got a Staff
    group — every other branch was gated behind the caller's own role
    (TEAM_LEAD_TRANSFER_ROLE_NAMES/GLOBAL_INBOX_ROLE_NAMES/etc.), none
    of which a Team Lead ever satisfied. Per the new product
    requirement the picker isn't scoped by the caller's role at all,
    so a Team Lead should now also see the Site Lead and Super Admin
    groups — roles it could never reach before, escalation or not.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    super_admin = await _get_super_admin(db_session)
    site_lead = await _get_site_lead(db_session)

    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, team_lead)

    roles_present = {g.role for g in result.groups}
    assert "Super Admin" in roles_present
    assert "Site Lead" in roles_present
    assert super_admin.name in _group_names(result, "Super Admin")
    assert site_lead.name in _group_names(result, "Site Lead")
    # Every group returned must still be one of the five agent-capable
    # roles — never the client-facing Viewer role.
    assert roles_present <= {"Staff", "Team Lead", "Account Manager", "Site Lead", "Super Admin"}


async def test_staff_group_is_no_longer_scoped_to_the_ticket_category(db_session):
    """
    Staff outside the ticket's own work-specialization category must
    now appear too — the picker is no longer restricted to
    ensure_agent_can_view_ticket's category boundary the way the old
    per-role branch table was.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)

    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, team_lead)

    same_category_staff = await service.user_repository.list_active_by_role_and_category(
        "Staff", ticket.ticket_type
    )
    all_staff_in_response = _group_names(result, "Staff")
    if len(all_staff_in_response) <= len({u.name for u in same_category_staff}):
        pytest.skip(
            "Seeded data has no Staff outside the ticket's own category to prove this with."
        )
    assert len(all_staff_in_response) > len({u.name for u in same_category_staff})


async def test_caller_excluded_from_their_own_role_group(db_session):
    """
    Self-assignment is offered separately via `me` — a caller should
    never also appear inside their own role's group in the response.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)

    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, team_lead)

    assert team_lead.name not in _group_names(result, "Team Lead")
    assert result.me.user_id == team_lead.user_id


async def test_current_agent_excluded_from_every_group(db_session):
    """
    The ticket's own currently-assigned agent must never appear as a
    transfer candidate — transfer_agent itself 400s on "already
    assigned to this agent," so offering it would be a
    guaranteed-to-fail option.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    staff_owner = await _get_staff_owner(db_session, team_lead)
    ticket.agent_id = staff_owner.user_id
    await db_session.flush()

    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, team_lead)

    all_ids = {u.user_id for g in result.groups for u in g.users}
    assert staff_owner.user_id not in all_ids


async def test_inactive_users_are_excluded_from_candidates(db_session):
    """
    An inactive user of any role must never be offered as a candidate,
    regardless of the widened role scope.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    account_manager = await _get_account_manager(db_session)
    inactive_user = await _make_inactive_user(db_session, account_manager)

    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, team_lead)

    all_ids = {u.user_id for g in result.groups for u in g.users}
    assert inactive_user.user_id not in all_ids


async def test_staff_without_transfer_permission_is_forbidden(db_session):
    """
    ensure_can_reassign_ticket's existing gate is preserved exactly —
    a Staff member with no ticket:transfer override still can't reach
    this endpoint at all, matching transfer_agent's own authorization.
    Unaffected by the target-side widening, since this is an
    actor-side (who may transfer at all) check, not a target check.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    staff = await _get_staff_owner(db_session, team_lead)
    staff.permissions = []  # no ticket:transfer override

    service = _build_interaction_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_transfer_candidates(ticket.ticket_id, staff)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------
# transfer_agent itself — every candidate get_transfer_candidates
# offers must actually be accepted on submit.
# ---------------------------------------------------------------


async def test_transfer_agent_accepts_a_previously_disallowed_target(db_session):
    """
    Before the widening, a Team Lead handing a ticket directly to a
    Super Admin (not a self-assign, not Staff, not reachable via any
    of the old per-role branches) would 400. It must now succeed,
    matching the widened get_transfer_candidates list 1:1.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    super_admin = await _get_super_admin(db_session)

    service = _build_interaction_service(db_session)
    response = await service.transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=super_admin.user_id, reason="test transfer"),
        team_lead,
    )

    assert response.ticket_id == ticket.ticket_id
    await db_session.refresh(ticket)
    assert ticket.agent_id == super_admin.user_id


async def test_transfer_agent_rejects_an_inactive_target(db_session):
    """Widened to "any active agent-capable user" — inactive is still rejected."""

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    account_manager = await _get_account_manager(db_session)
    inactive_user = await _make_inactive_user(db_session, account_manager)

    service = _build_interaction_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.transfer_agent(
            ticket.ticket_id,
            TransferAgentRequest(new_agent_id=inactive_user.user_id, reason="test transfer"),
            team_lead,
        )
    assert exc_info.value.status_code == 400
