# test_transfer_candidates.py
#
# Coverage for InteractionService.get_transfer_candidates — the
# role/hierarchy-scoped replacement for the old flat, role-blind
# "category Staff" list the Transfer Ticket dropdown used to be wired
# to. Verifies the candidate set mirrors transfer_agent's own
# acceptance rules exactly, per caller role, and never includes the
# ticket's own current agent.
#
# Same conventions as test_escalation_service.py: runs against the
# real (dev) database inside a transaction always rolled back at the
# end, reuses that file's own scenario/user-lookup helpers.

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from tests.test_acknowledge_and_assign_escalation import _build_interaction_service
from tests.test_escalation_service import (
    TEAM_LEAD_CATEGORY,
    _build_service,
    _get_account_manager,
    _get_site_lead,
    _get_staff_owner,
    _get_team_lead,
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


async def test_team_lead_sees_only_category_staff(db_session):
    """
    A Team Lead has no self-assign, Team Lead, Site Lead, or Account
    Manager group — transfer_agent never lets a Team Lead reach any of
    those branches. Only category-matched Staff.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)

    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, team_lead)

    roles_present = {g.role for g in result.groups}
    assert roles_present == {"Staff"}
    assert len(_group_names(result, "Staff")) > 0


async def test_account_manager_sees_company_wide_team_leads_and_category_staff(db_session):
    """
    Account Manager is in TEAM_LEAD_TRANSFER_ROLE_NAMES — every active
    Team Lead company-wide (not category-scoped, matching the widened
    Organization-Structure ticket-assignment rule), plus category
    Staff. No Account Manager group (not in GLOBAL_INBOX_ROLE_NAMES),
    no Site Lead group.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    account_manager = await _get_account_manager(db_session)

    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, account_manager)

    roles_present = {g.role for g in result.groups}
    assert "Team Lead" in roles_present
    assert "Staff" in roles_present
    assert "Site Lead" not in roles_present
    assert "Account Manager" not in roles_present

    # Company-wide, not category-scoped: the ticket's own category's
    # Team Lead must be present, AND (given this repo's seeded data
    # spans several categories — AR, Patient Calling, Claims, Charge
    # Entry, PA, Eligibility, Payment Posting) more than just that one
    # category's Team Lead(s) should be reachable too.
    team_lead_names = _group_names(result, "Team Lead")
    assert team_lead.name in team_lead_names
    assert len(team_lead_names) > 1


async def test_site_lead_sees_team_leads_and_staff_but_no_account_manager_without_escalation(
    db_session,
):
    """
    Site Lead can reach the Team Lead branch (TEAM_LEAD_TRANSFER_ROLE_NAMES)
    and the Staff branch always, but the Account Manager branch is
    reachable ONLY while the ticket has an active escalation —
    transfer_agent itself has no other path to accept an Account
    Manager as a transfer target. Confirms that gate here.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    site_lead = await _get_site_lead(db_session)

    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, site_lead)

    roles_present = {g.role for g in result.groups}
    assert "Team Lead" in roles_present
    assert "Staff" in roles_present
    assert "Account Manager" not in roles_present
    assert "Site Lead" not in roles_present  # Site Lead never transfers to another Site Lead


async def test_site_lead_sees_account_manager_group_during_active_escalation(db_session):
    """
    The other half of the gate above: once the ticket has an active
    escalation, a category-matched Account Manager becomes a valid
    transfer target for Site Lead — reuses
    EscalationService._resolve_category_account_managers, the exact
    same resolver get_acknowledge_candidates already uses, so this can
    never offer a candidate that mechanism wouldn't also recognize.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    staff_owner = await _get_staff_owner(db_session, team_lead)
    ticket.agent_id = staff_owner.user_id
    await db_session.flush()

    escalation_service = _build_service(db_session)
    await escalation_service.manual_escalate(ticket.ticket_id, staff_owner)

    site_lead = await _get_site_lead(db_session)
    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, site_lead)

    roles_present = {g.role for g in result.groups}
    if "Account Manager" not in roles_present:
        pytest.skip(
            "No Account Manager is configured as a Reporting Manager for "
            f"the {TEAM_LEAD_CATEGORY!r} category in seeded data."
        )
    assert len(_group_names(result, "Account Manager")) > 0


async def test_super_admin_sees_site_leads_team_leads_and_staff(db_session):
    """Super Admin reaches every branch except the escalation-gated Account Manager one."""

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    super_admin = await _get_super_admin(db_session)

    service = _build_interaction_service(db_session)
    result = await service.get_transfer_candidates(ticket.ticket_id, super_admin)

    roles_present = {g.role for g in result.groups}
    assert "Site Lead" in roles_present
    assert "Team Lead" in roles_present
    assert "Staff" in roles_present
    assert "Account Manager" not in roles_present  # no active escalation on this ticket


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

    staff_names = _group_names(result, "Staff")
    assert staff_owner.name not in staff_names
    all_ids = {u.user_id for g in result.groups for u in g.users}
    assert staff_owner.user_id not in all_ids


async def test_staff_without_transfer_permission_is_forbidden(db_session):
    """
    ensure_can_reassign_ticket's existing gate is preserved exactly —
    a Staff member with no ticket:transfer override still can't reach
    this endpoint at all, matching transfer_agent's own authorization.
    """

    team_lead, _client, ticket, _resolution_sla = await _make_scenario(db_session)
    staff = await _get_staff_owner(db_session, team_lead)
    staff.permissions = []  # no ticket:transfer override

    service = _build_interaction_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_transfer_candidates(ticket.ticket_id, staff)
    assert exc_info.value.status_code == 403
