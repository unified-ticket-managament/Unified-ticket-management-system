# test_assignment_team_lead_scope.py
#
# Team Lead + category Staff scoping for genuine ASSIGNMENT writes
# (TicketAssignmentService.add_users — the Assignments card's "Add
# Users" and Create Ticket's additional-assignee rows), plus regression
# proof that TRANSFER is untouched by the new rule.
#
# Self-contained world (tests/multi_assignment_support.py), always rolled
# back — no shared data is modified.

import uuid

import pytest
from fastapi import HTTPException
from shared_models.models import Category

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.schemas.ticket_action import TransferAgentRequest
from app.ticketing.services.ticket_assignment_service import build_ticket_assignment_service
from tests.multi_assignment_support import (
    STAFF_PERMISSIONS,
    TEAM_LEAD_PERMISSIONS,
    _make_user,
    _role,
    build_world,
    interaction_service,
    make_ticket,
)


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


@pytest.fixture
async def world(db_session):
    w = await build_world(db_session)
    staff_role = await _role(db_session, "Staff")
    tl_role = await _role(db_session, "Team Lead")

    # Another Team Lead (same category) with their own Staff member.
    w.rival_tl = _make_user(
        db_session, name="Rival TL", role=tl_role, tag=w.tag,
        categories=[w.billing], permissions=TEAM_LEAD_PERMISSIONS,
    )
    # A Team Lead with nobody linked.
    w.lonely_tl = _make_user(
        db_session, name="Lonely TL", role=tl_role, tag=w.tag,
        categories=[w.billing], permissions=TEAM_LEAD_PERMISSIONS,
    )
    await db_session.flush()
    w.rival_staff = _make_user(
        db_session, name="Rival Staff", role=staff_role, tag=w.tag,
        categories=[w.billing], permissions=STAFF_PERMISSIONS,
    )
    w.inactive_staff = _make_user(
        db_session, name="Inactive Staff", role=staff_role, tag=w.tag,
        categories=[w.billing], permissions=STAFF_PERMISSIONS,
    )
    w.inactive_staff.is_active = False
    # Linked to the main Team Lead only through the org-chart edge.
    w.org_chart_staff = _make_user(
        db_session, name="OrgChart Staff", role=staff_role, tag=w.tag,
        categories=[w.billing], permissions=STAFF_PERMISSIONS,
    )
    await db_session.flush()
    w.rival_staff.teamlead_id = w.rival_tl.user_id
    w.inactive_staff.teamlead_id = w.team_lead.user_id
    w.org_chart_staff.reporting_manager_id = w.team_lead.user_id
    await db_session.flush()
    return w


def svc(world):
    return build_ticket_assignment_service(world.session)


async def add(world, ticket, target, actor):
    return await svc(world).add_users(ticket.ticket_id, [target.user_id], actor)


# ------------------------------------------------------------ assignment


async def test_team_lead_can_add_in_team_in_category_staff(world):
    ticket = await make_ticket(world)
    await add(world, ticket, world.koushik, world.team_lead)  # teamlead_id link


async def test_team_lead_can_add_staff_linked_only_by_org_chart(world):
    ticket = await make_ticket(world)
    await add(world, ticket, world.org_chart_staff, world.team_lead)


async def test_team_lead_cannot_add_other_team_leads_staff_in_same_category(world):
    ticket = await make_ticket(world)
    with pytest.raises(HTTPException) as exc:
        await add(world, ticket, world.rival_staff, world.team_lead)
    assert exc.value.status_code == 400


async def test_team_lead_cannot_add_wrong_category_staff(world):
    ticket = await make_ticket(world)  # billing only; suresh is on the team but in claims
    with pytest.raises(HTTPException) as exc:
        await add(world, ticket, world.suresh, world.team_lead)
    assert exc.value.status_code == 400


async def test_multi_category_team_lead_adds_per_ticket_category(world):
    ticket = await make_ticket(world, categories=[world.billing, world.claims])
    await svc(world).add_users(
        ticket.ticket_id, [world.koushik.user_id, world.suresh.user_id], world.team_lead
    )


async def test_team_lead_cannot_add_inactive_staff(world):
    ticket = await make_ticket(world)
    with pytest.raises(HTTPException) as exc:
        await add(world, ticket, world.inactive_staff, world.team_lead)
    assert exc.value.status_code == 400


async def test_unlinked_team_lead_falls_back_to_staff_in_their_own_categories(world):
    # lonely_tl has no linked Staff at all -> may assign active Staff in
    # the categories they belong to (billing), including other teams'.
    ticket = await make_ticket(world)
    for staff in (world.koushik, world.rival_staff, world.org_chart_staff):
        await add(world, ticket, staff, world.lonely_tl)


async def test_unlinked_team_lead_fallback_never_leaves_their_categories(world):
    claims_ticket = await make_ticket(world, categories=[world.claims])  # lonely_tl is billing only
    with pytest.raises(HTTPException) as exc:
        await add(world, claims_ticket, world.suresh, world.lonely_tl)
    assert exc.value.status_code == 400


async def test_unlinked_team_lead_fallback_excludes_inactive_staff(world):
    ticket = await make_ticket(world)
    with pytest.raises(HTTPException) as exc:
        await add(world, ticket, world.inactive_staff, world.lonely_tl)
    assert exc.value.status_code == 400


async def test_team_lead_with_a_team_stays_strict_no_fallback(world):
    # rival_tl HAS a team (rival_staff) -> must not see koushik (another TL's staff).
    ticket = await make_ticket(world)
    with pytest.raises(HTTPException) as exc:
        await add(world, ticket, world.koushik, world.rival_tl)
    assert exc.value.status_code == 400


async def test_team_lead_non_staff_targets_keep_existing_rules(world):
    ticket = await make_ticket(world)
    # The client-owning Account Manager is still addable, as before.
    await add(world, ticket, world.account_manager, world.team_lead)


# ----------------------------------------------------------- other roles


@pytest.mark.parametrize("actor", ["account_manager", "site_lead"])
async def test_other_roles_can_still_add_any_in_category_staff(world, actor):
    ticket = await make_ticket(world)
    # rival_staff is NOT in anyone's team link to these actors - unchanged:
    # only category overlap applies.
    await svc(world).add_users(
        ticket.ticket_id,
        [world.rival_staff.user_id, world.koushik.user_id],
        getattr(world, actor),
    )


# --------------------------------------- TRANSFER IS UNCHANGED (regression)


async def test_transfer_candidates_for_team_lead_are_not_team_scoped(world):
    ticket = await make_ticket(world, agent=world.koushik)
    response = await interaction_service(world.session).get_transfer_candidates(
        ticket.ticket_id, world.team_lead
    )
    ids = {u.user_id for g in response.groups for u in g.users}
    # Out-of-team Staff, another Team Lead, the Account Manager and the
    # outsider are all still offered - exactly the pre-change behavior.
    assert {
        world.rival_staff.user_id,
        world.outsider.user_id,
        world.rival_tl.user_id,
        world.account_manager.user_id,
        world.ravi.user_id,
    } <= ids


async def test_team_lead_transfer_to_out_of_team_staff_still_succeeds(world):
    ticket = await make_ticket(world, agent=world.koushik)
    await interaction_service(world.session).transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=world.rival_staff.user_id, reason="regression"),
        world.team_lead,
    )
    await world.session.refresh(ticket)
    assert ticket.agent_id == world.rival_staff.user_id


async def test_team_lead_transfer_upward_still_succeeds(world):
    ticket = await make_ticket(world, agent=world.koushik)
    await interaction_service(world.session).transfer_agent(
        ticket.ticket_id,
        TransferAgentRequest(new_agent_id=world.account_manager.user_id, reason="regression"),
        world.team_lead,
    )
    await world.session.refresh(ticket)
    assert ticket.agent_id == world.account_manager.user_id
